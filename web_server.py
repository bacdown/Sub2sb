#!/usr/bin/env python3
"""Serve the browser interface alongside the existing conversion API."""

import argparse
import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from api.index import MAX_REQUEST_BYTES, convert_request, handler as ApiHandler

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_PAGE = PROJECT_ROOT / "web" / "index.html"
MAX_SUBSCRIPTION_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 5


def validate_public_url(url):
    """Allow public HTTP(S) subscription URLs and reject private destinations."""
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("订阅链接格式无效") from exc

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("订阅链接必须是有效的 HTTP 或 HTTPS 公网地址")

    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                parsed.hostname,
                port if port is not None else (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise ValueError("无法解析订阅链接的服务器地址") from exc

    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError("订阅链接不能指向内网或非公网地址")

    return parsed


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS
    max_repeats = MAX_REDIRECTS

    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_public_url(new_url)
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def fetch_remote_subscription(url):
    """Fetch a bounded subscription response without following redirects to private hosts."""
    validate_public_url(url)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        PublicRedirectHandler(),
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "yaml2sb/1.0"},
    )

    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_SUBSCRIPTION_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ValueError(f"下载订阅失败：{exc}") from exc

    if len(data) > MAX_SUBSCRIPTION_BYTES:
        raise ValueError("订阅内容不能超过 2 MiB")

    return data.decode("utf-8", errors="replace")


class WebHandler(ApiHandler):
    def do_GET(self):
        if self.path.rstrip("/") == "":
            try:
                page = WEB_PAGE.read_bytes()
            except OSError:
                logging.exception("Unable to read the web interface")
                self._send_json(500, {"error": "网页界面暂时不可用"})
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") != "/fetch":
            super().do_POST()
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                self._send_json(400, {"error": "请求体不能为空"})
                return
            if content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "请求体不能超过 2 MiB"})
                return

            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求 JSON 根节点必须是对象")

            url = payload.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError("请提供订阅链接")

            subscription = fetch_remote_subscription(url.strip())
            conversion_request = {
                "content": subscription,
                **{
                    key: value
                    for key, value in payload.items()
                    if key in ("template", "template_json")
                },
            }
            result = convert_request(conversion_request)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"请求 JSON 无效：{exc}"})
            return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except Exception:
            logging.exception("Subscription link conversion failed")
            self._send_json(500, {"error": "转换失败，请检查输入和模板"})
            return

        self._send_json(200, result)


def main():
    parser = argparse.ArgumentParser(description="启动 yaml2sb 网页版")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8080, help="监听端口（默认 8080）")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    logging.info("yaml2sb 网页版已启动：http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("正在关闭 yaml2sb 网页版")
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    main()
