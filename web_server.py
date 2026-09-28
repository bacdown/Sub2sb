#!/usr/bin/env python3
"""Serve the browser interface alongside the existing conversion API."""

import argparse
import json
import logging
from http.server import ThreadingHTTPServer
from pathlib import Path

from api.index import MAX_REQUEST_BYTES, convert_request, handler as ApiHandler
from remote_subscription import fetch_remote_subscription, validate_public_url

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_PAGE = PROJECT_ROOT / "public" / "index.html"
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

            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求 JSON 根节点必须是对象")

            urls = payload.get("urls")
            if urls is None:
                url = payload.get("url")
                urls = [url.strip()] if isinstance(url, str) else []
            if (
                not isinstance(urls, list)
                or not urls
                or any(not isinstance(item, str) or not item.strip() for item in urls)
            ):
                raise ValueError("请提供至少一个有效订阅链接")
            subscriptions = [fetch_remote_subscription(item.strip()) for item in urls]
            conversion_request = {
                "contents": subscriptions,
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
