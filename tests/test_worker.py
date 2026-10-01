import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import quote


class _WorkerResponse:
    def __init__(self, body="", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    async def text(self):
        return self.body


class _WorkerEntrypoint:
    env = None


workers_stub = types.ModuleType("workers")
workers_stub.Response = _WorkerResponse
workers_stub.WorkerEntrypoint = _WorkerEntrypoint
workers_stub.fetch = None
with patch.dict(sys.modules, {"workers": workers_stub}):
    worker = importlib.import_module("src.worker")


class WorkerSubscriptionTests(unittest.IsolatedAsyncioTestCase):
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
        entrypoint = worker.Default()

        with patch.object(
            worker,
            "_fetch_subscription",
            side_effect=worker.SubscriptionFetchError("远程服务器无法访问"),
        ):
            response = await entrypoint.fetch(request)

        self.assertEqual(response.status, 502)
        self.assertEqual(json.loads(response.body), {"error": "远程服务器无法访问"})


if __name__ == "__main__":
    unittest.main()