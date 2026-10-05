import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import quote, urlparse


class _WorkerResponse:
    def __init__(self, body="", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    async def text(self):
        return self.body


class _WorkerEntrypoint:
    env = None


class _WorkerAssets:
    async def fetch(self, resource):
        path = worker.ROOT / "templates" / urlparse(resource).path.lstrip("/")
        if not path.is_file():
            return _WorkerResponse(status=404)
        return _WorkerResponse(path.read_text(encoding="utf-8"))


def _entrypoint():
    entrypoint = worker.Default()
    entrypoint.env = types.SimpleNamespace(ASSETS=_WorkerAssets())
    return entrypoint


class _WorkerKV:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def put(self, key, value):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)

    async def list(self, options):
        prefix = options.get("prefix", "")
        return {
            "keys": [
                {"name": key}
                for key in self.values
                if key.startswith(prefix)
            ]
        }


class _WorkerRequest:
    def __init__(self, method, url, headers=None, body=""):
        self.method = method
        self.url = url
        self.headers = headers or {}
        self.body = body

    async def text(self):
        return self.body


workers_stub = types.ModuleType("workers")
workers_stub.Response = _WorkerResponse
workers_stub.WorkerEntrypoint = _WorkerEntrypoint
workers_stub.fetch = None
with patch.dict(sys.modules, {"workers": workers_stub}):
    worker = importlib.import_module("worker")


class WorkerSubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sub_endpoint_returns_sing_box_json_for_remote_subscription(self):
        url = quote("https://subscriptions.example/sub", safe="")
        request = _WorkerRequest(
            "GET",
            f"https://worker.example/sub?url={url}&template=phone",
        )
        entrypoint = _entrypoint()
        subscription = """proxies:
  - name: Japan HY2
    type: hysteria2
    server: japan.example
    port: 443
    password: test-password
    skip-cert-verify: true
"""

        with patch.object(worker, "_fetch_subscription", return_value=subscription):
            response = await entrypoint.fetch(request)

        self.assertEqual(response.status, 200)
        self.assertIn("application/json", response.headers["Content-Type"])
        self.assertIn('\n  "dns": {', response.body)
        config = json.loads(response.body)
        node = next(item for item in config["outbounds"] if item.get("tag") == "Japan HY2")
        self.assertTrue(node["tls"]["insecure"])

    async def test_saved_profile_uses_kv_and_public_short_link(self):
        kv = _WorkerKV()
        entrypoint = _entrypoint()
        entrypoint.env.SUBSCRIPTIONS = kv
        entrypoint.env.YAML2SB_API_KEY = "test-secret"
        profile_content = """proxies:
  - name: Japan 01
    type: hysteria2
    server: japan.example
    port: 443
    password: test-password
    skip-cert-verify: true
  - name: US West
    type: socks5
    server: us.example
    port: 1080
"""
        created = await entrypoint.fetch(
            _WorkerRequest(
                "POST",
                "https://worker.example/api/subscriptions",
                {"Authorization": "Bearer test-secret"},
                json.dumps({
                    "name": "Phone",
                    "contents": [profile_content],
                    "template": "phone",
                    "node_filter": {"include_names": ["japan"]},
                }),
            )
        )

        self.assertEqual(created.status, 201)
        summary = json.loads(created.body)
        config_response = await entrypoint.fetch(
            _WorkerRequest("GET", f"https://worker.example{summary['short_path']}")
        )
        self.assertEqual(config_response.status, 200)
        self.assertIn('\n  "dns": {', config_response.body)
        config = json.loads(config_response.body)
        node_tags = [item.get("tag") for item in config["outbounds"]]
        self.assertIn("Japan 01", node_tags)
        self.assertNotIn("US West", node_tags)
        node = next(item for item in config["outbounds"] if item.get("tag") == "Japan 01")
        self.assertTrue(node["tls"]["insecure"])

        listed = await entrypoint.fetch(
            _WorkerRequest(
                "GET",
                "https://worker.example/api/subscriptions",
                {"Authorization": "Bearer test-secret"},
            )
        )
        self.assertEqual(len(json.loads(listed.body)), 1)

    async def test_template_options_endpoint_is_available_without_api_key(self):
        request = types.SimpleNamespace(
            method="GET",
            url="https://worker.example/api/options?template=config_phone.json",
            headers={},
        )
        response = await _entrypoint().fetch(request)

        self.assertEqual(response.status, 200)
        options = json.loads(response.body)
        self.assertIn("dns_servers", options)
        self.assertIn("groups", options)
        self.assertIn("rule_sets", options)

    async def test_homepage_is_loaded_from_worker_bundle(self):
        request = types.SimpleNamespace(
            method="GET",
            url="https://worker.example/",
            headers={},
        )
        response = await worker.Default().fetch(request)

        self.assertEqual(response.status, 200)
        self.assertIn("text/html", response.headers["Content-Type"])
        self.assertIn("yaml2sb", response.body)

    async def test_fetch_subscription_passes_fetch_options_as_keywords(self):
        call = {}

        async def fake_fetch(resource, **options):
            call["resource"] = resource
            call["options"] = options
            return _WorkerResponse("proxies: []")

        with patch.object(worker, "fetch", fake_fetch):
            content = await worker._fetch_subscription(
                "https://subscriptions.example/sub"
            )

        self.assertEqual(content, "proxies: []")
        self.assertEqual(call["resource"], "https://subscriptions.example/sub")
        self.assertEqual(
            call["options"],
            {
                "headers": {"User-Agent": "yaml2sb/1.0"},
                "redirect": "manual",
            },
        )

    async def test_fetch_subscription_validates_redirect_destination(self):
        requested = []

        async def fake_fetch(resource, **options):
            requested.append(resource)
            return _WorkerResponse(status=302, headers={"location": "http://127.0.0.1/"})

        with patch.object(worker, "fetch", fake_fetch):
            with self.assertRaisesRegex(
                ValueError, "不能指向(?:本机或内网|内网或非公网)"
            ):
                await worker._fetch_subscription("https://subscriptions.example/sub")

        self.assertEqual(requested, ["https://subscriptions.example/sub"])

    async def test_fetch_subscription_rejects_oversized_content_length(self):
        async def fake_fetch(resource, **options):
            return _WorkerResponse(
                status=200,
                headers={"content-length": str(worker.MAX_SUBSCRIPTION_BYTES + 1)},
            )

        with patch.object(worker, "fetch", fake_fetch):
            with self.assertRaisesRegex(
                worker.SubscriptionTooLargeError, "不能超过 2 MiB"
            ):
                await worker._fetch_subscription("https://subscriptions.example/sub")

    async def test_fetch_subscription_follows_validated_public_redirect(self):
        responses = iter(
            [
                _WorkerResponse(status=302, headers={"location": "https://cdn.example/sub"}),
                _WorkerResponse("proxies: []"),
            ]
        )
        requested = []

        async def fake_fetch(resource, **options):
            requested.append(resource)
            return next(responses)

        with patch.object(worker, "fetch", fake_fetch):
            content = await worker._fetch_subscription("https://subscriptions.example/sub")

        self.assertEqual(content, "proxies: []")
        self.assertEqual(
            requested,
            ["https://subscriptions.example/sub", "https://cdn.example/sub"],
        )

    async def test_sub_endpoint_maps_upstream_errors_to_502(self):
        url = quote("https://subscriptions.example/sub", safe="")
        request = types.SimpleNamespace(
            method="GET",
            url=f"https://worker.example/sub?url={url}",
            headers={},
        )
        entrypoint = _entrypoint()

        with patch.object(
            worker,
            "_fetch_subscription",
            side_effect=worker.SubscriptionFetchError("远程服务器无法访问"),
        ):
            response = await entrypoint.fetch(request)

        self.assertEqual(response.status, 502)
        self.assertEqual(json.loads(response.body), {"error": "远程服务器无法访问"})

    async def test_sub_endpoint_explains_upstream_403(self):
        url = quote("https://subscriptions.example/sub", safe="")
        request = types.SimpleNamespace(
            method="GET",
            url=f"https://worker.example/sub?url={url}",
            headers={},
        )

        async def fake_fetch(resource, **options):
            return _WorkerResponse(status=403)

        with patch.object(worker, "fetch", fake_fetch):
            response = await _entrypoint().fetch(request)

        self.assertEqual(response.status, 502)
        self.assertIn("HTTP 403", json.loads(response.body)["error"])
        self.assertIn("Cloudflare Worker", json.loads(response.body)["error"])


if __name__ == "__main__":
    unittest.main()