import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from web_server import WebHandler, validate_public_url
from subscription_utils import collect_subscription_urls
from subscription_utils import SubscriptionFetchError


SAMPLE_SUBSCRIPTION = """proxies:
  - name: Japan 01
    type: vless
    server: example.com
    port: 443
    uuid: 00000000-0000-0000-0000-000000000000
    tls: true
"""


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), WebHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post_json(self, path, payload, headers=None):
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        with urlopen(request) as response:
            return response.status, json.loads(response.read())

    def test_homepage_serves_web_interface(self):
        with urlopen(self.base_url + "/") as response:
            page = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("粘贴 / 上传文件", page)
        self.assertIn("远程订阅链接", page)
        self.assertIn("iPhone 配置", page)
        self.assertIn('href="https://github.com/bacdown"', page)
        self.assertIn("<h1>yaml2sb · sing-box</h1>", page)
        self.assertIn("修改 YAML 配置文件或订阅链接转换为 sing-box JSON", page)
        self.assertIn("可本地、Docker 及 Vercel 部署", page)
        self.assertIn("默认配置文件均支持 sing-box 1.14.x", page)
        self.assertIn('const endpoint = "/api";', page)
        self.assertIn('type="file" multiple', page)
        self.assertIn("let uploadedFiles = [];", page)
        self.assertIn('id="api-key" type="password"', page)
        self.assertIn("Authorization: `Bearer ${apiKey.value}`", page)
        self.assertLess(page.index('id="file-name"'), page.index('id="file"'))
        self.assertIn("已添加 ${uploadedFiles.length} 个文件", page)
        self.assertIn("#f7f6f3", page)

    def test_local_api_and_fetch_require_configured_api_key(self):
        with patch("api.index.API_KEY", "test-secret"):
            requests = [
                Request(self.base_url + "/api"),
                Request(
                    self.base_url + "/api",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                Request(
                    self.base_url + "/fetch",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
            ]
            for request in requests:
                with self.subTest(path=request.full_url, method=request.get_method()):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request)
                    self.assertEqual(error.exception.code, 401)

            with urlopen(self.base_url + "/") as response:
                self.assertEqual(response.status, 200)

    def test_local_api_key_authorizes_api_and_fetch(self):
        with patch("api.index.API_KEY", "test-secret"):
            request = Request(
                self.base_url + "/api",
                headers={"Authorization": "Bearer test-secret"},
            )
            with urlopen(request) as response:
                self.assertEqual(response.status, 200)

            with patch(
                "web_server.fetch_remote_subscription",
                return_value=SAMPLE_SUBSCRIPTION,
            ) as fetch:
                status, result = self.post_json(
                    "/fetch",
                    {"url": "https://subscriptions.example/sub"},
                    headers={"X-API-Key": "test-secret"},
                )

        self.assertEqual(status, 200)
        self.assertEqual(result["node_count"], 1)
        fetch.assert_called_once_with("https://subscriptions.example/sub")

    def test_existing_api_remains_available(self):
        with urlopen(self.base_url + "/api") as response:
            payload = json.loads(response.read())

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["default_template"], "config_phone.json")

    def test_paste_api_returns_converted_configuration(self):
        status, result = self.post_json(
            "/api",
            {"content": SAMPLE_SUBSCRIPTION, "template": "config_phone.json"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["node_count"], 1)
        self.assertTrue(
            any(item.get("server") == "example.com" for item in result["config"]["outbounds"])
        )

    def test_custom_template_with_minimum_dependencies_converts(self):
        status, result = self.post_json(
            "/api",
            {
                "content": SAMPLE_SUBSCRIPTION,
                "template_json": {"outbounds": []},
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["node_count"], 1)
        self.assertTrue(
            any(item.get("server") == "example.com" for item in result["config"]["outbounds"])
        )

    def test_custom_template_requires_outbounds_array(self):
        request = Request(
            self.base_url + "/api",
            data=json.dumps({
                "content": SAMPLE_SUBSCRIPTION,
                "template_json": {"route": {}},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request)

        self.assertEqual(error.exception.code, 400)
        self.assertIn("outbounds 必须是数组", error.exception.read().decode("utf-8"))

    def test_custom_template_requires_outbound_objects(self):
        request = Request(
            self.base_url + "/api",
            data=json.dumps({
                "content": SAMPLE_SUBSCRIPTION,
                "template_json": {"outbounds": ["not-an-outbound"]},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request)

        self.assertEqual(error.exception.code, 400)
        self.assertIn("每一项都必须是对象", error.exception.read().decode("utf-8"))

    def test_link_endpoint_fetches_then_converts_subscription(self):
        with patch("web_server.fetch_remote_subscription", return_value=SAMPLE_SUBSCRIPTION) as fetch:
            status, result = self.post_json(
                "/fetch",
                {"url": "https://subscriptions.example/sub", "template": "momo.json"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["node_count"], 1)
        fetch.assert_called_once_with("https://subscriptions.example/sub")

    def test_link_endpoint_accepts_custom_template(self):
        with patch("web_server.fetch_remote_subscription", return_value=SAMPLE_SUBSCRIPTION):
            status, result = self.post_json(
                "/fetch",
                {
                    "url": "https://subscriptions.example/sub",
                    "template_json": {"outbounds": []},
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["node_count"], 1)

    def test_vercel_api_accepts_remote_url_list(self):
        with patch("api.index.fetch_remote_subscription", return_value=SAMPLE_SUBSCRIPTION) as fetch:
            status, result = self.post_json(
                "/api",
                {
                    "urls": [
                        "https://subscriptions.example/first",
                        "https://subscriptions.example/second",
                    ],
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["node_count"], 2)
        self.assertEqual(fetch.call_count, 2)

    def test_sub_endpoint_maps_upstream_errors_to_502(self):
        request = Request(
            self.base_url + "/sub?url=https%3A%2F%2Fsubscriptions.example%2Fsub"
        )
        with patch(
            "api.index.fetch_remote_subscription",
            side_effect=SubscriptionFetchError("远程服务器无法访问"),
        ):
            with self.assertRaises(HTTPError) as error:
                urlopen(request)

        self.assertEqual(error.exception.code, 502)
        self.assertIn("远程服务器无法访问", error.exception.read().decode("utf-8"))

    def test_link_endpoint_rejects_private_destinations(self):
        request = Request(
            self.base_url + "/fetch",
            data=json.dumps({"url": "http://127.0.0.1/private"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request)

        self.assertEqual(error.exception.code, 400)
        self.assertIn("公网", error.exception.read().decode("utf-8"))

    def test_url_validator_requires_http_or_https(self):
        with self.assertRaisesRegex(ValueError, "HTTP 或 HTTPS"):
            validate_public_url("file:///etc/passwd")

    def test_subscription_query_preserves_commas_in_single_url(self):
        self.assertEqual(
            collect_subscription_urls(
                {"url": ["https://subscriptions.example/sub?regions=jp,us"]}
            ),
            ["https://subscriptions.example/sub?regions=jp,us"],
        )

    def test_subscription_query_splits_multiple_urls_and_caps_count(self):
        self.assertEqual(
            collect_subscription_urls(
                {"urls": ["https://one.example/sub,https://two.example/sub"]}
            ),
            ["https://one.example/sub", "https://two.example/sub"],
        )
        with self.assertRaisesRegex(ValueError, "最多支持"):
            collect_subscription_urls(
                {"url": [f"https://{index}.example/sub" for index in range(11)]}
            )


if __name__ == "__main__":
    unittest.main()
