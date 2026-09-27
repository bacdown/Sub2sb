"""Vercel serverless API for converting proxy subscriptions to sing-box JSON."""

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from converter import convert_contents
from remote_subscription import fetch_remote_subscription

MAX_REQUEST_BYTES = 2 * 1024 * 1024
DEFAULT_TEMPLATE = "config_phone.json"
TEMPLATE_FILES = {
    "config_phone.json",
    "config_openwrt.json",
    "momo.json",
}


def _load_named_template(name):
    if name not in TEMPLATE_FILES:
        raise ValueError(
            "不支持的模板名称；可选模板："
            + ", ".join(sorted(TEMPLATE_FILES))
        )

    template_path = PROJECT_ROOT / "templates" / name
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

    if "template_json" in payload:
        if "template" in payload:
            raise ValueError("template 与 template_json 不能同时使用")
        template = _load_custom_template(payload["template_json"])
    else:
        template_name = payload.get("template", DEFAULT_TEMPLATE)
        if not isinstance(template_name, str):
            raise ValueError("template 必须是模板文件名")
        template = _load_named_template(template_name)

    config, node_count = convert_contents(contents, template)
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
            if key in ("template", "template_json")
        },
    }


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") not in ("/", "/api"):
            self._send_json(404, {"error": "Not found"})
            return

        self._send_json(
            200,
            {
                "name": "yaml2sb",
                "method": "POST",
                "templates": sorted(TEMPLATE_FILES),
                "default_template": DEFAULT_TEMPLATE,
                "request": {
                    "content": "YAML 或订阅文本",
                    "template": "已有模板文件名（可选）",
                    "template_json": "自定义 sing-box JSON 模板对象（可选）",
                },
            },
        )

    def do_POST(self):
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
            if isinstance(payload, dict) and ("url" in payload or "urls" in payload):
                payload = _request_with_remote_urls(payload)
            result = convert_request(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"请求 JSON 无效：{exc}"})
            return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except Exception:
            logging.exception("Conversion API request failed")
            self._send_json(500, {"error": "转换失败，请检查输入和模板"})
            return

        self._send_json(200, result)

    def log_message(self, format, *args):
        logging.info("%s - %s", self.address_string(), format % args)
