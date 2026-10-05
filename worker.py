#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare Workers 入口：在线将订阅转换为 sing-box JSON。

支持：
  GET  /             网页 UI（与 Vercel 相同结构）
  GET  /sub?url=...&template=phone|openwrt|momo
  GET  /api          API 说明
  POST /api          JSON 转换（content / url / urls / template_json）
  OPTIONS *          CORS
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import sys
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from workers import Response, WorkerEntrypoint, fetch

# Cloudflare Worker 文件所在目录：项目根目录
WORKER_DIR = Path(__file__).resolve().parent

# Worker 入口与共用 Python 模块位于同一打包根目录
ROOT = WORKER_DIR

# 转换核心与订阅工具以项目根目录为唯一来源
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from converter import convert_contents  # noqa: E402
from sub2singbox import normalize_certificate_policies  # noqa: E402
from template_options import get_template_options  # noqa: E402
from subscription_utils import (  # noqa: E402
    SubscriptionFetchError,
    SubscriptionTooLargeError,
    collect_subscription_urls,
    validate_public_url_syntax,
)

DEFAULT_TEMPLATE = "config_phone.json"
TEMPLATE_ALIASES = {
    "phone": "config_phone.json",
    "config_phone": "config_phone.json",
    "config_phone.json": "config_phone.json",
    "openwrt": "config_openwrt.json",
    "config_openwrt": "config_openwrt.json",
    "config_openwrt.json": "config_openwrt.json",
    "momo": "momo.json",
    "momo.json": "momo.json",
}
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_SUBSCRIPTION_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
PROFILE_PREFIX = "yaml2sb:profile:"
MAX_PROFILE_COUNT = 1000

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-API-Key",
}


def _json_response(status: int, payload: dict | list, extra_headers: dict | None = None):
    body = json.dumps(payload, ensure_ascii=False)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        **CORS_HEADERS,
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(body, status=status, headers=headers)


def _resolve_template_name(name: str | None) -> str:
    if not name or not str(name).strip():
        return DEFAULT_TEMPLATE
    key = str(name).strip().lower()
    resolved = TEMPLATE_ALIASES.get(key) or TEMPLATE_ALIASES.get(str(name).strip())
    if resolved is None:
        raise ValueError(
            "不支持的模板名称；可选：phone / openwrt / momo "
            "（或 config_phone.json / config_openwrt.json / momo.json）"
        )
    return resolved


async def _load_asset_text(env, name: str) -> str:
    assets = getattr(env, "ASSETS", None)
    if assets is None:
        raise FileNotFoundError(name)
    response = await assets.fetch(f"https://assets.local/{name}")
    if int(response.status) != 200:
        raise FileNotFoundError(name)
    return await response.text()


async def _load_template(env, name: str | None) -> dict:
    resolved = _resolve_template_name(name)
    try:
        text = await _load_asset_text(env, resolved)
    except FileNotFoundError as exc:
        raise ValueError(f"找不到模板文件：{resolved}") from exc
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("配置模板 JSON 根节点必须是对象")
    return data


def _api_key_from_env(env) -> str | None:
    try:
        value = getattr(env, "YAML2SB_API_KEY", None)
    except Exception:
        value = None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_authorized(request, env, query: dict) -> bool:
    expected = _api_key_from_env(env)
    if not expected:
        return True

    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth:
        parts = str(auth).split()
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == expected:
            return True

    header_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if header_key == expected:
        return True

    for item in query.get("api_key", []):
        if item == expected:
            return True
    return False


def _collect_urls(query: dict) -> list[str]:
    return collect_subscription_urls(query)


def _validate_public_http_url(url: str) -> str:
    validate_public_url_syntax(url)
    return url


async def _fetch_subscription(url: str) -> str:
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        _validate_public_http_url(current_url)
        try:
            response = await fetch(
                current_url,
                headers={"User-Agent": "yaml2sb/1.0"},
                redirect="manual",
            )
        except OSError as exc:
            logging.exception("Remote subscription fetch failed")
            raise ValueError("下载订阅失败：远程服务器无法访问") from exc

        status = int(response.status)
        if status in REDIRECT_STATUSES:
            if redirect_count >= MAX_REDIRECTS:
                raise ValueError("订阅链接重定向次数过多")
            location = response.headers.get("location")
            if not location:
                raise ValueError("订阅服务器返回了无效的重定向")
            current_url = urljoin(current_url, location)
            continue
        break

    if status < 200 or status >= 300:
        message = f"下载订阅失败：HTTP {status}"
        if status == 403:
            message += (
                "。请检查订阅地址和授权是否有效；如果该地址在本地可访问但 Worker 返回 403，"
                "可能是服务商限制了 Cloudflare Worker 的出口请求。"
                "如果已取得 Base64 订阅内容，可切换到网页的粘贴模式直接转换。"
            )
        raise SubscriptionFetchError(message)

    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise ValueError("订阅服务器返回了无效的内容长度") from exc
        if declared_length > MAX_SUBSCRIPTION_BYTES:
            raise SubscriptionTooLargeError("订阅内容不能超过 2 MiB")

    try:
        text = await response.text()
    except OSError as exc:
        logging.exception("Remote subscription response read failed")
        raise SubscriptionFetchError("读取订阅内容失败") from exc

    if not isinstance(text, str):
        text = str(text)
    if len(text.encode("utf-8", errors="replace")) > MAX_SUBSCRIPTION_BYTES:
        raise SubscriptionTooLargeError("订阅内容不能超过 2 MiB")
    if not text.strip():
        raise ValueError("订阅内容为空")
    return text


def _load_custom_template(value) -> dict:
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
    if any(not isinstance(item, dict) for item in outbounds):
        raise ValueError("自定义模板中的 outbounds 每一项都必须是对象")
    return value


def _convert(
    contents: list[str], template: dict, node_filter: dict | None = None
) -> tuple[dict, int]:
    config, node_count = convert_contents(contents, template, node_filter=node_filter)
    return config, node_count


def _validate_profile(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("订阅配置必须是 JSON 对象")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError("名称必须为 1 到 80 个字符")
    urls = payload.get("urls")
    contents = payload.get("contents")
    if urls is not None and contents is not None:
        raise ValueError("远程订阅链接与 YAML 内容只能选择一种来源")
    if urls is not None:
        urls = collect_subscription_urls({"urls": urls})
        if not urls:
            raise ValueError("请至少提供一个订阅链接")
        for url in urls:
            validate_public_url_syntax(url)
        source = {"urls": urls}
    elif (
        isinstance(contents, list)
        and contents
        and all(isinstance(item, str) and item.strip() for item in contents)
    ):
        if sum(len(item.encode("utf-8")) for item in contents) > MAX_BODY_BYTES:
            raise ValueError("订阅内容总大小不能超过 2 MiB")
        source = {"contents": contents}
    else:
        raise ValueError("请提供 urls 或 contents 作为订阅来源")

    node_filter = payload.get("node_filter", {})
    if not isinstance(node_filter, dict):
        raise ValueError("node_filter 必须是对象")
    normalized_filter = {}
    for key in ("include_names", "exclude_names"):
        values = node_filter.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > 50
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise ValueError(f"node_filter.{key} 必须是最多 50 项的非空字符串数组")
        normalized_filter[key] = [value.strip() for value in values]
    normalized_filter["tls_insecure"] = normalize_certificate_policies(
        node_filter.get("tls_insecure", {})
    )

    template_name = payload.get("template", DEFAULT_TEMPLATE)
    if not isinstance(template_name, str):
        raise ValueError("template 必须是模板名称")
    try:
        _resolve_template_name(template_name)
    except ValueError as exc:
        raise ValueError("template 必须是 phone、openwrt 或 momo") from exc
    if payload.get("template_json") is not None:
        _load_custom_template(payload["template_json"])
        if payload.get("template_options") is not None:
            raise ValueError("自定义模板不能与 template_options 同时使用")
    if payload.get("template_options") is not None and not isinstance(
        payload["template_options"], dict
    ):
        raise ValueError("template_options 必须是对象")

    result = {
        "name": name.strip(),
        **source,
        "template": template_name.strip(),
        "node_filter": normalized_filter,
    }
    for key in ("template_json", "template_options"):
        if payload.get(key) is not None:
            result[key] = payload[key]
    return result


def _load_index_html() -> str:
    candidates = (
        ROOT / "public" / "index.html",
    )
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError("找不到网页文件 index.html")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        method = (request.method or "GET").upper()
        parsed = urlparse(request.url)
        path = (parsed.path or "/").rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if method == "OPTIONS":
            return Response("", status=204, headers=CORS_HEADERS)

        # 首页不需要 API Key，与 Vercel/本地网页版一致
        if method == "GET" and path == "/":
            try:
                html = _load_index_html()
            except FileNotFoundError:
                return _json_response(500, {"error": "网页界面暂时不可用"})
            return Response(
                html,
                status=200,
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "Cache-Control": "public, max-age=300",
                    **CORS_HEADERS,
                },
            )

        if method == "GET" and path.startswith("/s/"):
            profile_id = path.removeprefix("/s/")
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,24}", profile_id):
                return _json_response(404, {"error": "订阅配置不存在"})
            try:
                return await self._handle_saved_profile(profile_id)
            except SubscriptionFetchError as exc:
                return _json_response(exc.status_code, {"error": str(exc)})
            except ValueError as exc:
                return _json_response(400, {"error": str(exc)})
            except RuntimeError as exc:
                return _json_response(503, {"error": str(exc)})
            except Exception:
                logging.exception("Saved subscription conversion failed")
                return _json_response(500, {"error": "订阅配置转换失败"})

        if not _is_authorized(request, self.env, query):
            return _json_response(401, {"error": "Unauthorized"})

        try:
            if path == "/api/subscriptions" or path.startswith("/api/subscriptions/"):
                if not _api_key_from_env(self.env):
                    return _json_response(503, {"error": "订阅管理需要先配置 YAML2SB_API_KEY"})
                return await self._handle_profiles(request, method, path)

            if method == "GET" and path == "/api/options":
                template_name = (query.get("template") or [DEFAULT_TEMPLATE])[0]
                template = await _load_template(self.env, template_name)
                return _json_response(
                    200,
                    get_template_options(template),
                )

            if method == "GET" and path in ("/sub", "/api/sub"):
                return await self._handle_sub(query)

            if method == "GET" and path == "/api":
                return self._handle_info()

            if method == "POST" and path in ("/api", "/"):
                return await self._handle_post(request)

            return _json_response(404, {"error": "Not found"})
        except SubscriptionFetchError as exc:
            return _json_response(exc.status_code, {"error": str(exc)})
        except ValueError as exc:
            return _json_response(400, {"error": str(exc)})
        except RuntimeError as exc:
            return _json_response(503, {"error": str(exc)})
        except Exception:
            logging.exception("Worker request failed")
            return _json_response(500, {"error": "转换失败，请检查订阅链接和模板"})

    def _profile_kv(self):
        binding = getattr(self.env, "SUBSCRIPTIONS", None)
        if binding is None:
            raise RuntimeError("请为 Worker 配置名为 SUBSCRIPTIONS 的 KV namespace")
        return binding

    async def _read_profile(self, profile_id):
        value = await self._profile_kv().get(PROFILE_PREFIX + profile_id)
        if not value:
            return None
        return json.loads(value) if isinstance(value, str) else value

    def _profile_summary(self, profile_id, profile):
        source = "urls" if "urls" in profile else "contents"
        return {
            "id": profile_id,
            "name": profile["name"],
            "source_type": source,
            "source_count": len(profile[source]),
            "template": profile.get("template", DEFAULT_TEMPLATE),
            "node_filter": profile.get("node_filter", {}),
            "created_at": profile["created_at"],
            "updated_at": profile["updated_at"],
            "short_path": f"/s/{profile_id}",
        }

    async def _handle_profiles(self, request, method, path):
        binding = self._profile_kv()
        profile_id = path.removeprefix("/api/subscriptions").strip("/")
        if method == "GET":
            if profile_id:
                profile = await self._read_profile(profile_id)
                if profile is None:
                    return _json_response(404, {"error": "订阅配置不存在"})
                return _json_response(200, {"id": profile_id, **profile})
            page = await binding.list({"prefix": PROFILE_PREFIX, "limit": MAX_PROFILE_COUNT})
            summaries = []
            for key in page.get("keys", []):
                key_name = key["name"] if isinstance(key, dict) else key.name
                current_id = key_name.removeprefix(PROFILE_PREFIX)
                profile = await self._read_profile(current_id)
                if profile is not None:
                    summaries.append(self._profile_summary(current_id, profile))
            summaries.sort(key=lambda item: item["updated_at"], reverse=True)
            return _json_response(200, summaries)

        if method not in ("POST", "PATCH", "PUT", "DELETE"):
            return _json_response(405, {"error": "Method not allowed"})
        if method == "DELETE":
            if not profile_id:
                return _json_response(404, {"error": "Not found"})
            existing = await self._read_profile(profile_id)
            if existing is None:
                return _json_response(404, {"error": "订阅配置不存在"})
            await binding.delete(PROFILE_PREFIX + profile_id)
            return _json_response(200, {"deleted": True})

        raw = await request.text()
        if not raw or len(raw.encode("utf-8")) > MAX_BODY_BYTES:
            return _json_response(413, {"error": "请求体为空或超过 2 MiB"})
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("请求 JSON 根节点必须是对象")
        if method == "POST":
            if profile_id:
                return _json_response(404, {"error": "Not found"})
            record = _validate_profile(payload)
            for _ in range(5):
                profile_id = secrets.token_urlsafe(12)
                if await self._read_profile(profile_id) is None:
                    break
            else:
                raise RuntimeError("无法生成唯一的短链接 ID")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            record.update({"created_at": now, "updated_at": now})
        else:
            if not profile_id:
                return _json_response(404, {"error": "Not found"})
            existing = await self._read_profile(profile_id)
            if existing is None:
                return _json_response(404, {"error": "订阅配置不存在"})
            record = _validate_profile({**existing, **payload})
            record["created_at"] = existing["created_at"]
            record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        await binding.put(PROFILE_PREFIX + profile_id, json.dumps(record, ensure_ascii=False))
        return _json_response(
            201 if method == "POST" else 200,
            self._profile_summary(profile_id, record),
        )

    async def _handle_saved_profile(self, profile_id):
        profile = await self._read_profile(profile_id)
        if profile is None:
            return _json_response(404, {"error": "订阅配置不存在"})
        if "urls" in profile:
            contents = [await _fetch_subscription(url) for url in profile["urls"]]
        else:
            contents = profile["contents"]
        template = (
            _load_custom_template(profile["template_json"])
            if "template_json" in profile
            else await _load_template(self.env, profile.get("template", DEFAULT_TEMPLATE))
        )
        config, _node_count = _convert(contents, template, profile.get("node_filter", {}))
        return Response(
            json.dumps(config, ensure_ascii=False, indent=2),
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "public, max-age=60",
                "Content-Disposition": f'inline; filename="sing-box-{profile_id}.json"',
                **CORS_HEADERS,
            },
        )

    def _handle_info(self):
        return _json_response(
            200,
            {
                "name": "yaml2sb",
                "platform": "cloudflare-workers",
                "methods": [
                    "GET /",
                    "GET /sub",
                    "GET /api/sub",
                    "GET /s/{id}",
                    "GET/POST /api/subscriptions",
                    "GET/PATCH/DELETE /api/subscriptions/{id}",
                    "GET /api/options",
                    "GET /api",
                    "POST /api",
                ],
                "templates": sorted(set(TEMPLATE_ALIASES.values())),
                "template_aliases": {
                    "phone": "config_phone.json",
                    "openwrt": "config_openwrt.json",
                    "momo": "momo.json",
                },
                "default_template": DEFAULT_TEMPLATE,
                "web_ui": "/",
                "subscription": {
                    "path": "/sub",
                    "query": {
                        "url": "原订阅链接（必填）",
                        "urls": "多个订阅，逗号分隔（可选）",
                        "template": "phone | openwrt | momo（默认 phone）",
                        "api_key": "若配置了 YAML2SB_API_KEY 则必填",
                    },
                    "example": "/sub?url=https%3A%2F%2Fexample.com%2Fsubscribe&template=phone",
                },
                "request": {
                    "content": "YAML 或订阅文本",
                    "url": "远程订阅链接",
                    "template": "内置模板文件名或短名",
                    "template_json": "自定义 sing-box JSON 模板对象",
                },
            },
        )

    async def _handle_sub(self, query: dict):
        urls = _collect_urls(query)
        if not urls:
            raise ValueError(
                "请提供订阅链接参数 url，例如 /sub?url=https%3A%2F%2Fexample.com%2Fsub&template=phone"
            )
        template_name = (query.get("template") or [DEFAULT_TEMPLATE])[0]
        contents = [await _fetch_subscription(u) for u in urls]
        template = await _load_template(self.env, template_name)
        config, _node_count = _convert(contents, template)
        body = json.dumps(config, ensure_ascii=False, indent=2)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "public, max-age=60",
            "Content-Disposition": 'inline; filename="sing-box.json"',
            **CORS_HEADERS,
        }
        return Response(body, status=200, headers=headers)

    async def _handle_post(self, request):
        raw = await request.text()
        if not raw or not str(raw).strip():
            raise ValueError("请求体不能为空")
        if len(str(raw).encode("utf-8")) > MAX_BODY_BYTES:
            raise ValueError("请求体不能超过 2 MiB")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"请求 JSON 无效：{exc.msg}") from exc

        if not isinstance(payload, dict):
            raise ValueError("请求 JSON 根节点必须是对象")

        template_obj = None
        template_name = payload.get("template", DEFAULT_TEMPLATE)
        if "template_json" in payload:
            if "template" in payload:
                raise ValueError("template 与 template_json 不能同时使用")
            template_obj = _load_custom_template(payload["template_json"])
        else:
            template_obj = await _load_template(self.env, template_name)

        contents: list[str] = []
        if "url" in payload or "urls" in payload:
            urls = payload.get("urls")
            if urls is None:
                url = payload.get("url")
                urls = [url] if isinstance(url, str) else []
            if not isinstance(urls, list) or not urls:
                raise ValueError("请提供至少一个有效订阅链接")
            for item in urls:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("请提供至少一个有效订阅链接")
                contents.append(await _fetch_subscription(item.strip()))
        else:
            raw_contents = payload.get("contents")
            if raw_contents is None:
                raw_contents = [payload.get("content")]
            if (
                not isinstance(raw_contents, list)
                or not raw_contents
                or any(
                    not isinstance(c, str) or not c.strip() for c in raw_contents
                )
            ):
                raise ValueError("请在 content 字段中提供 YAML 或订阅文本")
            contents = raw_contents

        config, node_count = _convert(contents, template_obj, payload.get("node_filter"))
        return _json_response(200, {"config": config, "node_count": node_count})
