"""回归测试：自定义模板挂载、模板注册表、Worker/API 的 template_options 一致性。"""

import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from api.index import convert_request
from sub2singbox import convert_contents
from template_registry import (
    alias_file_map,
    resolve_template_file,
    template_files,
)

SAMPLE = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@1.2.3.4:8388#TestNode"


def _groups(config):
    return {
        item["tag"]: item
        for item in config["outbounds"]
        if item.get("type") in ("selector", "urltest")
    }


class CustomTemplateMountTests(unittest.TestCase):
    def test_generic_group_names_receive_nodes(self):
        template = {
            "outbounds": [
                {"tag": "proxy", "type": "selector", "outbounds": ["auto", "直连"]},
                {"tag": "auto", "type": "urltest", "outbounds": []},
                {"tag": "直连", "type": "direct"},
            ],
            "route": {"final": "proxy"},
        }
        config, count = convert_contents([SAMPLE], template=template)
        self.assertEqual(count, 1)
        groups = _groups(config)
        self.assertIn("TestNode", groups["auto"]["outbounds"])

    def test_final_selector_receives_nodes(self):
        template = {
            "outbounds": [
                {"tag": "默认代理", "type": "selector", "outbounds": []},
                {"tag": "直连", "type": "direct"},
            ],
            "route": {"final": "默认代理"},
        }
        config, _ = convert_contents([SAMPLE], template=template)
        self.assertIn("TestNode", _groups(config)["默认代理"]["outbounds"])

    def test_unmountable_groups_raise(self):
        template = {
            "outbounds": [
                {"tag": "weird", "type": "selector", "outbounds": ["直连"]},
                {"tag": "直连", "type": "direct"},
            ],
            "route": {"final": "直连"},
        }
        with self.assertRaises(ValueError):
            convert_contents([SAMPLE], template=template)

    def test_minimal_template_without_groups_still_converts(self):
        config, count = convert_contents([SAMPLE], template={"outbounds": []})
        self.assertEqual(count, 1)
        self.assertTrue(any(item.get("tag") == "TestNode" for item in config["outbounds"]))


class TemplateRegistryTests(unittest.TestCase):
    def test_openwrt_is_deprecated_alias_of_linux(self):
        for name in ("openwrt", "config_openwrt", "config_openwrt.json"):
            self.assertEqual(resolve_template_file(name), "config_linux.json")

    def test_canonical_names_resolve(self):
        self.assertEqual(resolve_template_file("phone"), "config_phone.json")
        self.assertEqual(resolve_template_file("linux"), "config_linux.json")
        self.assertEqual(resolve_template_file("windows"), "config_windows.json")
        self.assertEqual(resolve_template_file("momo"), "momo.json")
        self.assertEqual(resolve_template_file(None), "config_phone.json")

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            resolve_template_file("does-not-exist")

    def test_registry_files_exist(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for filename in template_files():
            self.assertTrue((root / "templates" / filename).is_file(), filename)
        self.assertEqual(
            set(alias_file_map().values()),
            template_files(),
        )

    def test_openwrt_alias_output_matches_linux(self):
        via_alias = convert_request({"content": SAMPLE, "template": "openwrt"})
        via_linux = convert_request({"content": SAMPLE, "template": "linux"})
        self.assertEqual(via_alias, via_linux)

    def test_windows_template_converts(self):
        result = convert_request({"content": SAMPLE, "template": "windows"})
        self.assertEqual(result["node_count"], 1)


# --- Worker harness (mirrors tests/test_worker.py) ---


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


class _WorkerRequest:
    def __init__(self, method, url, headers=None, body=""):
        self.method = method
        self.url = url
        self.headers = headers or {}
        self.body = body

    async def text(self):
        return self.body


if "worker" in sys.modules:
    worker = sys.modules["worker"]
else:
    _stub = types.ModuleType("workers")
    _stub.Response = _WorkerResponse
    _stub.WorkerEntrypoint = _WorkerEntrypoint
    _stub.fetch = None
    with patch.dict(sys.modules, {"workers": _stub}):
        worker = importlib.import_module("worker")


def _entrypoint():
    entrypoint = worker.Default()
    entrypoint.env = types.SimpleNamespace(ASSETS=_WorkerAssets())
    return entrypoint


class WorkerTemplateOptionsParityTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_post_applies_template_options_like_api(self):
        payload = {
            "content": SAMPLE,
            "template": "phone",
            "template_options": {"dns_servers": ["alibaba-cloud-dns"]},
        }
        api_result = convert_request(payload)

        response = await _entrypoint().fetch(
            _WorkerRequest(
                "POST",
                "https://worker.example/api",
                {"Content-Type": "application/json"},
                json.dumps(payload),
            )
        )
        self.assertEqual(response.status, 200)
        worker_result = json.loads(response.body)

        self.assertEqual(worker_result["config"], api_result["config"])
        dns_tags = {
            server["tag"] for server in worker_result["config"]["dns"]["servers"]
        }
        self.assertIn("alibaba-cloud-dns", dns_tags)
        self.assertNotIn("google-public-dns", dns_tags)


if __name__ == "__main__":
    unittest.main()
