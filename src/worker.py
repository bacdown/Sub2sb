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
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from workers import Response, WorkerEntrypoint, fetch

# Cloudflare Worker 文件所在目录：项目的 src/
WORKER_DIR = Path(__file__).resolve().parent

# 项目根目录，主要用于本地开发或 Vercel 结构
ROOT = WORKER_DIR.parent

# 允许导入 src/converter.py 以及根目录中的兼容模块
for path in (WORKER_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from converter import convert_contents  # noqa: E402

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

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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


def _load_template(name: str | None) -> dict:
    resolved = _resolve_template_name(name)
    candidates = (
        ROOT / "templates" / resolved,
        ROOT / resolved,
        Path(__file__).resolve().parent / "templates" / resolved,
    )
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise ValueError(f"找不到模板文件：{resolved}")
    data = json.loads(path.read_text(encoding="utf-8"))
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
    urls: list[str] = []
    for key in ("url", "urls"):
        for raw in query.get(key, []):
            if not isinstance(raw, str):
                continue
            for part in raw.split(","):
                part = part.strip()
                if part:
                    urls.append(part)
    return list(dict.fromkeys(urls))


def _validate_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("订阅链接必须是有效的 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("订阅链接不能包含用户名或密码")
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        raise ValueError("订阅链接不能指向本机或内网地址")
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("169.254."):
        raise ValueError("订阅链接不能指向内网地址")
    # 粗略拦截 172.16.0.0/12
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            if 16 <= second <= 31:
                raise ValueError("订阅链接不能指向内网地址")
        except (IndexError, ValueError):
            pass
    return url


async def _fetch_subscription(url: str) -> str:
    _validate_public_http_url(url)
    response = await fetch(
        url,
        {
            "headers": {"User-Agent": "yaml2sb/1.0"},
            "redirect": "follow",
        },
    )
    status = int(response.status)
    if status < 200 or status >= 300:
        raise ValueError(f"下载订阅失败：HTTP {status}")

    # workers Response：优先 text()
    if hasattr(response, "text"):
        text = await response.text()
    else:
        text = str(await response.body)

    if not isinstance(text, str):
        text = str(text)
    if len(text.encode("utf-8", errors="replace")) > MAX_SUBSCRIPTION_BYTES:
        raise ValueError("订阅内容不能超过 2 MiB")
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
    contents: list[str],
    template_name: str | None = None,
    template_obj: dict | None = None,
) -> tuple[dict, int]:
    if template_obj is not None:
        template = template_obj
    else:
        template = _load_template(template_name)
    config, node_count = convert_contents(contents, template)
    return config, node_count


def _load_index_html() -> str:
    candidates = (
        ROOT / "index.html",
        ROOT / "public" / "index.html",
        WORKER_DIR / "index.html",
        WORKER_DIR / "public" / "index.html",
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

        if not _is_authorized(request, self.env, query):
            return _json_response(401, {"error": "Unauthorized"})

        try:
            if method == "GET" and path in ("/sub", "/api/sub"):
                return await self._handle_sub(query)

            if method == "GET" and path == "/api":
                return self._handle_info()

            if method == "POST" and path in ("/api", "/"):
                return await self._handle_post(request)

            return _json_response(404, {"error": "Not found"})
        except ValueError as exc:
            return _json_response(400, {"error": str(exc)})
        except Exception:
            return _json_response(500, {"error": "转换失败，请检查订阅链接和模板"})

    def _handle_info(self):
        return _json_response(
            200,
            {
                "name": "yaml2sb",
                "platform": "cloudflare-workers",
                "methods": ["GET /", "GET /sub", "GET /api", "POST /api"],
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
        config, _node_count = _convert(contents, template_name)
        body = json.dumps(config, ensure_ascii=False)
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

        config, node_count = _convert(
            contents,
            template_name=template_name,
            template_obj=template_obj,
        )
        return _json_response(200, {"config": config, "node_count": node_count})
