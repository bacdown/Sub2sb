"""Vercel serverless API for converting proxy subscriptions to sing-box JSON."""

import copy
import json
import logging
import os
import sys
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from converter import convert_contents
from remote_subscription import fetch_remote_subscription
from subscription_utils import SubscriptionFetchError, collect_subscription_urls
from subscription_lab import (
    SubscriptionStoreUnavailable,
    get_subscription_store,
    validate_profile,
)
from template_options import (
    apply_template_options as _apply_template_options,
    get_template_options as _template_options,
)

MAX_REQUEST_BYTES = 2 * 1024 * 1024
# 模板注册表是单一事实源：别名（含 openwrt 弃用别名）与文件映射都在
# template_registry.py 中定义，方便订阅链接里写 template=phone
from template_registry import (
    alias_file_map as _alias_file_map,
    resolve_template_file as _resolve_template_file,
    short_aliases as _short_aliases,
    template_files as _template_files,
)

DEFAULT_TEMPLATE = "config_phone.json"
TEMPLATE_FILES = _template_files()
TEMPLATE_ALIASES = _alias_file_map()

# When set, the Vercel serverless function requires requests to present this
# key. Leave unset to keep the API public (backwards compatible behaviour).
API_KEY = os.environ.get("SUB2SB_API_KEY")


def _resolve_template_name(name):
    """将短名或文件名解析为标准模板文件名。"""
    if not isinstance(name, str) or not name.strip():
        return DEFAULT_TEMPLATE
    return _resolve_template_file(name)


def _load_named_template(name):
    resolved = _resolve_template_name(name)
    # 兼容 templates/ 子目录与项目根目录两种布局
    candidates = (
        PROJECT_ROOT / "templates" / resolved,
        PROJECT_ROOT / resolved,
    )
    template_path = next((path for path in candidates if path.is_file()), None)
    if template_path is None:
        raise ValueError(f"找不到模板文件：{resolved}")
    with template_path.open("r", encoding="utf-8") as template_file:
        template = json.load(template_file)
    if not isinstance(template, dict):
        raise ValueError("配置模板 JSON 根节点必须是对象")
    return template


def _load_custom_template(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"自定义模板不是有效 JSON：{exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("自定义模板必须是 JSON 对象")
    outbounds = value.get("outbounds")
    if not isinstance(outbounds, list):
        raise ValueError("自定义模板缺少必要项：outbounds 必须是数组")
    if any(not isinstance(outbound, dict) for outbound in outbounds):
        raise ValueError("自定义模板中的 outbounds 每一项都必须是对象")
    return value




def convert_request(payload):
    """Validate one API request and return its converted configuration."""
    if not isinstance(payload, dict):
        raise ValueError("请求 JSON 根节点必须是对象")

    contents = payload.get("contents")
    if contents is None:
        contents = [payload.get("content")]
    if (
        not isinstance(contents, list)
        or not contents
        or any(not isinstance(content, str) or not content.strip() for content in contents)
    ):
        raise ValueError("请在 content 字段中提供 YAML 或订阅文本")

    template_options = None
    template_metadata = None
    if "template_json" in payload:
        if "template" in payload:
            raise ValueError("template 与 template_json 不能同时使用")
        if "template_options" in payload:
            raise ValueError("template_json 不能与 template_options 同时使用")
        template = _load_custom_template(payload["template_json"])
    else:
        template_name = payload.get("template", DEFAULT_TEMPLATE)
        if not isinstance(template_name, str):
            raise ValueError("template 必须是模板文件名")
        template = _load_named_template(template_name)
        if "template_options" in payload:
            template_options = payload["template_options"]
            template_metadata = _template_options(template)
            template = _apply_template_options(template, template_options)

    config, node_count = convert_contents(
        contents, template, node_filter=payload.get("node_filter")
    )
    if isinstance(template_options, dict) and isinstance(template_metadata, dict):
        group_destinations = {}
        rule_outbounds = template_options.get("rule_outbounds", {})
        default_rule_groups = {
            str(item["index"]): item["outbound"]
            for item in template_metadata["matching_rules"]
        }
        for rule_id, destination in template_options.get("rule_destinations", {}).items():
            group_tag = rule_outbounds.get(rule_id, default_rule_groups.get(rule_id))
            if isinstance(group_tag, str) and isinstance(destination, str):
                group_destinations[group_tag] = destination
        for rule in template_options.get("custom_matching_rules", []):
            if (
                isinstance(rule, dict)
                and isinstance(rule.get("name"), str)
                and isinstance(rule.get("destination"), str)
            ):
                group_destinations[rule["name"]] = rule["destination"]
        for group in config.get("outbounds", []):
            if (
                isinstance(group, dict)
                and group.get("tag") in group_destinations
                and isinstance(group.get("outbounds"), list)
            ):
                destination = group_destinations[group["tag"]]
                group["outbounds"] = [
                    destination,
                    *(item for item in group["outbounds"] if item != destination),
                ]
    return {"config": config, "node_count": node_count}


def _request_with_remote_urls(payload):
    urls = payload.get("urls")
    if urls is None:
        url = payload.get("url")
        urls = [url] if isinstance(url, str) else []
    if (
        not isinstance(urls, list)
        or not urls
        or any(not isinstance(url, str) or not url.strip() for url in urls)
    ):
        raise ValueError("请提供至少一个有效订阅链接")
    return {
        "contents": [fetch_remote_subscription(url.strip()) for url in urls],
        **{
            key: value
            for key, value in payload.items()
            if key in ("template", "template_json", "template_options", "node_filter")
        },
    }


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Allow Authorization and X-API-Key for token-based access
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # Always allow preflight so browsers can check CORS before sending credentials
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _is_authorized(self):
        # If no API key is configured, API remains public (backwards compatible).
        if not API_KEY:
            return True

        # Authorization: Bearer <key>
        auth_hdr = self.headers.get("Authorization")
        if auth_hdr:
            parts = auth_hdr.split()
            if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == API_KEY:
                return True

        # X-API-Key header
        if self.headers.get("X-API-Key") == API_KEY:
            return True

        # query parameter ?api_key=...
        try:
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            if params.get("api_key") and API_KEY in params.get("api_key"):
                return True
        except Exception:
            pass

        return False

    def _send_unauthorized(self):
        self._send_json(401, {"error": "Unauthorized"})

    def _request_path(self):
        """去掉查询串后的路径，兼容 /api 前缀。"""
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        return path

    def _query_params(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _collect_subscription_urls(self, params):
        """从 query 收集 url / urls 参数。"""
        return collect_subscription_urls(params)

    def _handle_sub_get(self):
        """
        GET /sub 或 /api/sub
        拉取远程订阅并返回可直接导入客户端的 sing-box JSON（纯配置，非包装对象）。

        查询参数：
          url / urls   原订阅链接（至少一个，可重复或逗号分隔）
          template     模板：phone | linux | windows | momo
                       或 config_phone.json | config_linux.json | config_windows.json | momo.json
          api_key      若服务端配置了 SUB2SB_API_KEY 则必填（也可用 Header）
        """
        if not self._is_authorized():
            self._send_unauthorized()
            return

        try:
            params = self._query_params()
            urls = self._collect_subscription_urls(params)
            if not urls:
                raise ValueError(
                    "请提供订阅链接参数 url（或 urls），"
                    "例如 /sub?url=https%3A%2F%2Fexample.com%2Fsub&template=phone"
                )

            template_name = (params.get("template") or [DEFAULT_TEMPLATE])[0]
            payload = _request_with_remote_urls(
                {"urls": urls, "template": template_name}
            )
            result = convert_request(payload)
            # 客户端远程配置需要纯 sing-box JSON，不要外层包装
            config = result["config"]
            body = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, X-API-Key",
            )
            # 订阅宜短缓存，避免节点长期过期
            self.send_header("Cache-Control", "public, max-age=60")
            self.send_header(
                "Content-Disposition",
                'inline; filename="sing-box.json"',
            )
            self.end_headers()
            self.wfile.write(body)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except SubscriptionFetchError as exc:
            self._send_json(exc.status_code, {"error": str(exc)})
        except Exception:
            logging.exception("GET /sub conversion failed")
            self._send_json(500, {"error": "转换失败，请检查订阅链接和模板"})

    def _management_enabled(self):
        if API_KEY:
            return True
        self._send_json(503, {"error": "订阅管理需要先配置 SUB2SB_API_KEY"})
        return False

    def _profile_summary(self, profile):
        source = "urls" if "urls" in profile else "contents"
        return {
            "id": profile["id"],
            "name": profile["name"],
            "source_type": source,
            "source_count": len(profile[source]),
            "template": profile.get("template", "phone"),
            "node_filter": profile.get("node_filter", {}),
            "created_at": profile["created_at"],
            "updated_at": profile["updated_at"],
            "short_path": f"/s/{profile['id']}",
        }

    def _handle_profiles_get(self, path):
        if not self._management_enabled():
            return
        try:
            store = get_subscription_store()
            profile_id = path.removeprefix("/api/subscriptions").strip("/")
            if profile_id:
                profile = store.get(profile_id)
                if profile is None:
                    self._send_json(404, {"error": "订阅配置不存在"})
                    return
                self._send_json(200, profile)
                return
            self._send_json(200, [self._profile_summary(item) for item in store.list()])
        except SubscriptionStoreUnavailable as exc:
            self._send_json(503, {"error": str(exc)})

    def _handle_profile_create(self, payload):
        if not self._management_enabled():
            return
        try:
            record = validate_profile(payload)
            profile = get_subscription_store().create(record)
            self._send_json(201, self._profile_summary(profile))
        except (ValueError, SubscriptionStoreUnavailable) as exc:
            self._send_json(400 if isinstance(exc, ValueError) else 503, {"error": str(exc)})

    def _handle_profile_update(self, profile_id, payload):
        if not self._management_enabled():
            return
        try:
            store = get_subscription_store()
            existing = store.get(profile_id)
            if existing is None:
                self._send_json(404, {"error": "订阅配置不存在"})
                return
            merged = {**existing, **payload}
            profile = store.update(profile_id, validate_profile(merged))
            self._send_json(200, self._profile_summary(profile))
        except (ValueError, SubscriptionStoreUnavailable) as exc:
            self._send_json(400 if isinstance(exc, ValueError) else 503, {"error": str(exc)})

    def _handle_profile_delete(self, profile_id):
        if not self._management_enabled():
            return
        try:
            deleted = get_subscription_store().delete(profile_id)
            if not deleted:
                self._send_json(404, {"error": "订阅配置不存在"})
                return
            self._send_json(200, {"deleted": True})
        except SubscriptionStoreUnavailable as exc:
            self._send_json(503, {"error": str(exc)})

    def _handle_saved_sub_get(self, profile_id):
        try:
            profile = get_subscription_store().get(profile_id)
            if profile is None:
                self._send_json(404, {"error": "订阅配置不存在"})
                return
            if "urls" in profile:
                contents = [fetch_remote_subscription(url) for url in profile["urls"]]
            else:
                contents = profile["contents"]
            payload = {
                "contents": contents,
                "node_filter": profile.get("node_filter", {}),
            }
            if "template_json" in profile:
                payload["template_json"] = profile["template_json"]
            else:
                payload["template"] = profile.get("template", "phone")
                if "template_options" in profile:
                    payload["template_options"] = profile["template_options"]
            config = convert_request(payload)["config"]
            body = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=60")
            self.send_header("Content-Disposition", f'inline; filename="sing-box-{profile_id}.json"')
            self.end_headers()
            self.wfile.write(body)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except SubscriptionFetchError as exc:
            self._send_json(exc.status_code, {"error": str(exc)})
        except SubscriptionStoreUnavailable as exc:
            self._send_json(503, {"error": str(exc)})
        except Exception:
            logging.exception("Saved subscription conversion failed")
            self._send_json(500, {"error": "订阅配置转换失败"})

    def do_GET(self):
        path = self._request_path()

        if path == "/api/options":
            if not self._is_authorized():
                self._send_unauthorized()
                return
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            template_name = query.get("template", [DEFAULT_TEMPLATE])[0]
            try:
                self._send_json(200, _template_options(_load_named_template(template_name)))
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            return

        if path == "/api/subscriptions" or path.startswith("/api/subscriptions/"):
            if not self._is_authorized():
                self._send_unauthorized()
                return
            self._handle_profiles_get(path)
            return

        if path.startswith("/s/") or path.startswith("/api/s/"):
            prefix = "/api/s/" if path.startswith("/api/s/") else "/s/"
            profile_id = path.removeprefix(prefix)
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,24}", profile_id):
                self._send_json(404, {"error": "订阅配置不存在"})
                return
            self._handle_saved_sub_get(profile_id)
            return

        # 远程订阅转换：客户端可直接填此 URL 作为远程配置
        if path in ("/sub", "/api/sub"):
            self._handle_sub_get()
            return

        if path not in ("/", "/api"):
            self._send_json(404, {"error": "Not found"})
            return

        if not self._is_authorized():
            self._send_unauthorized()
            return

        self._send_json(
            200,
            {
                "name": "Sub2sb",
                "methods": [
                    "GET /sub",
                    "GET /s/{id}",
                    "POST /api",
                    "GET/POST /api/subscriptions",
                    "GET/PATCH/DELETE /api/subscriptions/{id}",
                ],
                "templates": sorted(TEMPLATE_FILES),
                "template_aliases": _short_aliases(),
                "default_template": DEFAULT_TEMPLATE,
                "subscription": {
                    "path": "/sub",
                    "query": {
                        "url": "原订阅链接（必填，可重复或与 urls 同用）",
                        "urls": "多个订阅链接，逗号分隔（可选）",
                        "template": "phone | linux | windows | momo（默认 phone；openwrt 为 linux 的弃用别名）",
                        "api_key": "若启用了 SUB2SB_API_KEY 则必填",
                    },
                    "example": (
                        "/sub?url=https%3A%2F%2Fexample.com%2Fsubscribe"
                        "&template=phone"
                    ),
                },
                "request": {
                    "content": "YAML 或订阅文本",
                    "url": "远程订阅链接（POST 时由服务端拉取）",
                    "template": "已有模板文件名或短名（可选）",
                    "template_json": "自定义 sing-box JSON 模板对象（可选）",
                },
            },
        )

    def do_POST(self):
        # Require authorization before reading body to avoid unnecessary work
        if not self._is_authorized():
            self._send_unauthorized()
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                self._send_json(400, {"error": "请求体不能为空"})
                return
            if content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "请求体不能超过 2 MiB"})
                return

            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))
            if self._request_path() == "/api/subscriptions":
                self._handle_profile_create(payload)
                return
            if isinstance(payload, dict) and ("url" in payload or "urls" in payload):
                payload = _request_with_remote_urls(payload)
            result = convert_request(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"请求 JSON 无效：{exc}"})
            return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except SubscriptionFetchError as exc:
            self._send_json(exc.status_code, {"error": str(exc)})
            return
        except Exception:
            logging.exception("Conversion API request failed")
            self._send_json(500, {"error": "转换失败，请检查输入和模板"})
            return

        self._send_json(200, result)

    def do_PATCH(self):
        if not self._is_authorized():
            self._send_unauthorized()
            return
        path = self._request_path()
        prefix = "/api/subscriptions/"
        if not path.startswith(prefix) or not path[len(prefix):]:
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("请求体为空或超过 2 MiB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求 JSON 根节点必须是对象")
            self._handle_profile_update(path[len(prefix):], payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"error": f"请求无效：{exc}"})

    def do_DELETE(self):
        if not self._is_authorized():
            self._send_unauthorized()
            return
        prefix = "/api/subscriptions/"
        path = self._request_path()
        if not path.startswith(prefix) or not path[len(prefix):]:
            self._send_json(404, {"error": "Not found"})
            return
        self._handle_profile_delete(path[len(prefix):])

    def log_message(self, format, *args):
        logging.info("%s - %s", self.address_string(), format % args)
