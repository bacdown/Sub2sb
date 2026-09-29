import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.index import _template_options, _load_named_template, convert_request
from web_server import WebHandler, validate_public_url


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
        self.assertIn("自定义制作配置", page)
        self.assertIn("/api/options?template=", page)
        self.assertIn('id="dns-domestic-options"', page)
        self.assertIn('id="dns-international-options"', page)
        self.assertIn('type="checkbox"', page)
        self.assertIn("点击 DNS 项即可选中或取消", page)
        self.assertNotIn("按住 Ctrl / Command", page)
        self.assertIn('class="base-template-controls"', page)
        self.assertIn('id="reload-options"', page)
        self.assertIn("MAX_DNS_SERVERS_PER_CATEGORY = 2", page)
        self.assertNotIn('id="dns-builtin-choices"', page)
        self.assertNotIn('id="dns-final"', page)
        self.assertIn("匹配规则与顺序", page)
        self.assertIn("出站（地区 / 手动自动）", page)
        self.assertIn('id="match-name"', page)
        self.assertIn('id="match-rule-set"', page)
        self.assertIn('id="match-outbound"', page)
        self.assertIn('id="add-match-rule"', page)
        self.assertIn('id="new-rule-outbound"', page)
        self.assertIn("renderRuleOutboundOptions(matchOutbound", page)
        self.assertIn('remove.className = "remove-item"', page)
        self.assertIn('remove.textContent = "移除"', page)
        self.assertIn('class="rule-link-details"', page)
        self.assertIn("已选择的 DNS", page)
        self.assertNotIn("保留模板设置", page)
        self.assertNotIn("<h3>应用分流</h3>", page)
        self.assertNotIn("<h3>规则集</h3>", page)
        self.assertNotIn('id="add-group"', page)
        self.assertIn('id="group-choices"', page)
        self.assertIn('id="rule-set-choices"', page)
        self.assertIn("template_options", page)
        self.assertIn("rule_set_links_only: false", page)
        self.assertIn('type="file" multiple', page)
        self.assertIn("let uploadedFiles = [];", page)
        self.assertIn('id="api-key" type="password"', page)
        self.assertIn('class="api-key-field"', page)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", page)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(0, 2fr)", page)
        self.assertIn("#template, #api-key, #base-template { height: 50px; font-size: 13px; }", page)
        self.assertIn("padding-top: 29px", page)
        self.assertIn('class="api-key-input-wrap"', page)
        self.assertIn("#api-key { height: 50px; padding: 6px 10px; }", page)
        self.assertIn("apiKeyHint.hidden = Boolean(apiKey.value);", page)
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

    def test_template_options_endpoint_requires_configured_api_key(self):
        with patch("api.index.API_KEY", "test-secret"):
            request = Request(self.base_url + "/api/options?template=config_phone.json")
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 401)

            request = Request(
                self.base_url + "/api/options?template=config_phone.json",
                headers={"X-API-Key": "test-secret"},
            )
            with urlopen(request) as response:
                options = json.loads(response.read())

        self.assertIn("dns_servers", options)
        self.assertIn("groups", options)

    def test_existing_api_remains_available(self):
        with urlopen(self.base_url + "/api") as response:
            payload = json.loads(response.read())

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["default_template"], "config_phone.json")

    def test_template_options_endpoint_returns_profile_choices(self):
        request = Request(
            self.base_url + "/api/options?template=config_phone.json",
        )
        with urlopen(request) as response:
            options = json.loads(response.read())

        self.assertIn("dns_servers", options)
        self.assertIn("groups", options)
        self.assertIn("rule_sets", options)
        self.assertIn(
            "alibaba-cloud-dns",
            [item["tag"] for item in options["dns_servers"]],
        )
        self.assertEqual(
            next(item for item in options["dns_servers"] if item["tag"] == "alibaba-cloud-dns")["server"],
            "223.5.5.5",
        )
        self.assertEqual(
            next(item for item in options["dns_servers"] if item["tag"] == "alibaba-cloud-dns")["type"],
            "udp",
        )
        self.assertNotIn(
            "ali",
            [item["tag"] for item in options["dns_servers"]],
        )
        self.assertIn(
            "google-public-dns",
            [
                item["tag"] for item in options["dns_servers"]
                if item["category"] == "international"
            ],
        )
        self.assertIn("YouTube", [item["tag"] for item in options["groups"]])
        self.assertIn("日本自动", [item["tag"] for item in options["groups"]])
        application_groups = {
            item["tag"] for item in options["groups"] if item["application"]
        }
        self.assertIn("AI", application_groups)
        self.assertIn("Google", application_groups)
        self.assertNotIn("日本自动", application_groups)
        self.assertNotIn("自动选择", application_groups)
        self.assertIn("直连", options["matching_targets"])
        self.assertNotIn("AI", options["matching_targets"])
        self.assertIn("geosite-youtube", [item["tag"] for item in options["rule_sets"]])
        rule_targets = {
            item["tag"] for item in options["groups"] if item["rule_target"]
        }
        self.assertNotIn("日本手动", rule_targets)
        self.assertNotIn("日本自动", rule_targets)
        self.assertNotIn("延迟辅助", rule_targets)
        self.assertTrue(options["matching_rules"])
        self.assertIn("直连", options["rule_targets"])
        self.assertIn("直连", options["matching_targets"])
        self.assertIn("日本自动", options["matching_targets"])
        self.assertNotIn("延迟辅助", options["matching_targets"])

    def test_all_builtin_templates_use_udp_for_alibaba_ip_dns(self):
        for template_name in ("config_phone.json", "config_openwrt.json", "momo.json"):
            with self.subTest(template=template_name):
                alibaba_dns = next(
                    server for server in _load_named_template(template_name)["dns"]["servers"]
                    if server["tag"] == "alibaba-cloud-dns"
                )
                self.assertEqual(
                    alibaba_dns,
                    {
                        "tag": "alibaba-cloud-dns",
                        "type": "udp",
                        "server": "223.5.5.5",
                    },
                )

    def test_composed_template_options_customize_dns_groups_and_rule_sets(self):
        template = _load_named_template("config_phone.json")
        options = _template_options(template)
        selected_rule_sets = [
            item["tag"] for item in options["rule_sets"]
            if item["tag"] != "geosite-youtube"
        ]
        selected_groups = [
            item["tag"] for item in options["groups"]
            if item["tag"] != "YouTube"
        ]
        selected_dns = [
            item["tag"] for item in options["dns_servers"]
            if item["tag"] != "tencent-dnspod-dns"
        ]
        configuration_options = {
            "dns_servers": selected_dns,
            "dns_final": "custom-dns",
            "custom_dns_servers": [
                {"tag": "custom-dns", "type": "https", "server": "1.1.1.1"},
            ],
            "groups": selected_groups,
            "custom_groups": [
                {"tag": "Games", "rule_sets": ["geosite-google"]},
            ],
            "rule_sets": selected_rule_sets,
            "custom_rule_sets": [
                {
                    "tag": "geosite-games",
                    "url": "https://example.com/games.srs",
                    "format": "binary",
                    "outbound": "Games",
                },
            ],
        }

        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": configuration_options,
        })
        config = result["config"]
        outbound_tags = {item["tag"] for item in config["outbounds"]}

        self.assertEqual(result["node_count"], 1)
        self.assertEqual(config["dns"]["final"], "custom-dns")
        self.assertNotIn("tencent-dnspod-dns", {item["tag"] for item in config["dns"]["servers"]})
        self.assertIn("Games", outbound_tags)
        self.assertNotIn("YouTube", outbound_tags)
        self.assertTrue(all(
            "YouTube" not in item.get("outbounds", [])
            for item in config["outbounds"]
        ))
        self.assertNotIn(
            "geosite-youtube",
            {tag for item in config["route"]["rule_set"] for tag in (
                item["tag"] if isinstance(item["tag"], list) else [item["tag"]]
            )},
        )
        self.assertTrue(any(
            item.get("rule_set") == "geosite-games" and item.get("outbound") == "Games"
            for item in config["route"]["rules"]
        ))
        self.assertTrue(any(
            item.get("rule_set") == "geosite-google" and item.get("outbound") == "Games"
            for item in config["route"]["rules"]
        ))
        games_group = next(item for item in config["outbounds"] if item["tag"] == "Games")
        self.assertIn("默认代理", games_group["outbounds"])

    def test_empty_composition_options_preserve_each_builtin_template(self):
        for template_name in ("config_phone.json", "config_openwrt.json", "momo.json"):
            with self.subTest(template=template_name):
                original = convert_request({
                    "content": SAMPLE_SUBSCRIPTION,
                    "template": template_name,
                })
                composed = convert_request({
                    "content": SAMPLE_SUBSCRIPTION,
                    "template": template_name,
                    "template_options": {},
                })
                self.assertEqual(composed, original)

    def test_composition_rejects_dns_final_not_in_selected_servers(self):
        with self.assertRaisesRegex(ValueError, "已保留或新添加"):
            convert_request({
                "content": SAMPLE_SUBSCRIPTION,
                "template": "config_phone.json",
                "template_options": {
                    "dns_servers": ["alibaba-cloud-dns"],
                    "dns_final": "google",
                },
            })

    def test_composition_reorders_default_match_rules_and_changes_targets(self):
        template = _load_named_template("config_phone.json")
        options = _template_options(template)
        ordered_indexes = [
            str(item["index"]) for item in reversed(options["matching_rules"])
        ]
        changed_rule = options["matching_rules"][0]
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "rule_order": ordered_indexes,
                "rule_outbounds": {str(changed_rule["index"]): "手动选择"},
            },
        })

        actual_matching = [
            {key: value for key, value in rule.items() if key != "outbound"}
            for rule in result["config"]["route"]["rules"]
            if isinstance(rule, dict)
            and isinstance(rule.get("outbound"), str)
            and any(key not in ("outbound", "action") for key in rule)
        ]
        expected_matching = [
            item["match"] for item in reversed(options["matching_rules"])
        ]
        self.assertEqual(actual_matching, expected_matching)
        target_rule = next(
            rule for rule in result["config"]["route"]["rules"]
            if rule.get("outbound") == "手动选择"
            and {
                key: value for key, value in rule.items() if key != "outbound"
            } == changed_rule["match"]
        )
        self.assertEqual(target_rule["outbound"], "手动选择")

    def test_composition_removes_default_matching_rule_missing_from_order(self):
        template = _load_named_template("config_phone.json")
        options = _template_options(template)
        removed_rule = options["matching_rules"][0]
        remaining_order = [
            str(item["index"])
            for item in options["matching_rules"][1:]
        ]
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {"rule_order": remaining_order},
        })

        matches = [
            rule for rule in result["config"]["route"]["rules"]
            if isinstance(rule, dict)
            and isinstance(rule.get("outbound"), str)
            and any(key not in ("outbound", "action") for key in rule)
        ]
        self.assertEqual(sum(
            {key: value for key, value in rule.items() if key != "outbound"}
            == removed_rule["match"]
            for rule in matches
        ), 1)

    def test_composition_orders_custom_rule_group_with_default_rules(self):
        template = _load_named_template("config_phone.json")
        options = _template_options(template)
        rule_order = [
            "custom:geosite-games",
            *(str(item["index"]) for item in options["matching_rules"]),
        ]
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "custom_groups": [{
                    "tag": "Games",
                    "rule_sets": ["geosite-games"],
                }],
                "custom_rule_sets": [{
                    "tag": "geosite-games",
                    "url": "https://example.com/games.srs",
                    "format": "binary",
                    "outbound": "默认代理",
                }],
                "rule_order": rule_order,
            },
        })

        matching_rules = [
            rule for rule in result["config"]["route"]["rules"]
            if isinstance(rule, dict)
            and isinstance(rule.get("outbound"), str)
            and any(key not in ("outbound", "action") for key in rule)
        ]
        self.assertEqual(matching_rules[0]["rule_set"], "geosite-games")
        self.assertEqual(matching_rules[0]["outbound"], "Games")

    def test_composition_adds_named_matching_rules_and_orders_them(self):
        template = _load_named_template("config_phone.json")
        options = _template_options(template)
        rule_order = [
            "builder-1",
            *(str(item["index"]) for item in options["matching_rules"]),
        ]
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "custom_matching_rules": [{
                    "id": "builder-1",
                    "name": "自定义应用",
                    "rule_set": "geosite-google",
                    "outbound": "自定义应用",
                    "destination": "日本自动",
                }],
                "rule_order": rule_order,
            },
        })

        matching_rules = [
            rule for rule in result["config"]["route"]["rules"]
            if isinstance(rule, dict)
            and isinstance(rule.get("outbound"), str)
            and any(key not in ("outbound", "action") for key in rule)
        ]
        self.assertEqual(matching_rules[0]["rule_set"], "geosite-google")
        self.assertEqual(matching_rules[0]["outbound"], "自定义应用")
        self.assertNotIn("__builder_rule_id", matching_rules[0])
        application_group = next(
            item for item in result["config"]["outbounds"]
            if item["tag"] == "自定义应用"
        )
        self.assertEqual(application_group["outbounds"][0], "日本自动")

    def test_composition_allows_direct_as_custom_application_default(self):
        options = _template_options(_load_named_template("config_phone.json"))
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "custom_matching_rules": [{
                    "id": "builder-1",
                    "name": "直连应用",
                    "rule_set": "geosite-google",
                    "outbound": "直连应用",
                    "destination": "直连",
                }],
                "rule_order": [
                    "builder-1",
                    *(str(item["index"]) for item in options["matching_rules"]),
                ],
            },
        })

        application_group = next(
            item for item in result["config"]["outbounds"]
            if item["tag"] == "直连应用"
        )
        self.assertEqual(application_group["outbounds"][0], "直连")

    def test_composition_allows_direct_as_existing_rule_outbound(self):
        template = _load_named_template("config_phone.json")
        options = _template_options(template)
        ai_rule = next(
            item for item in options["matching_rules"]
            if item["outbound"] == "AI"
        )
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "rule_outbounds": {str(ai_rule["index"]): "直连"},
            },
        })

        direct_rules = [
            rule for rule in result["config"]["route"]["rules"]
            if rule.get("outbound") == "直连"
            and rule.get("rule_set") == ai_rule["match"].get("rule_set")
        ]
        self.assertEqual(len(direct_rules), 1)

    def test_composition_allows_direct_as_custom_rule_set_outbound(self):
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "custom_rule_sets": [{
                    "tag": "geosite-direct",
                    "url": "https://example.com/geosite-direct.srs",
                    "format": "binary",
                    "outbound": "直连",
                }],
                "rule_order": [
                    "custom:geosite-direct",
                    *(
                        str(item["index"])
                        for item in _template_options(
                            _load_named_template("config_phone.json")
                        )["matching_rules"]
                    ),
                ],
                "rule_set_links_only": False,
            },
        })

        direct_rule = next(
            rule for rule in result["config"]["route"]["rules"]
            if rule.get("rule_set") == "geosite-direct"
        )
        self.assertEqual(direct_rule["outbound"], "直连")

    def test_custom_rule_set_used_by_builder_adds_only_one_matching_rule(self):
        options = _template_options(_load_named_template("config_phone.json"))
        rule_id = "builder-1"
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "custom_rule_sets": [{
                    "tag": "geosite-custom",
                    "url": "https://example.com/geosite-custom.srs",
                    "format": "binary",
                    "outbound": "直连",
                }],
                "custom_matching_rules": [{
                    "id": rule_id,
                    "name": "AI",
                    "rule_set": "geosite-custom",
                    "outbound": "AI",
                    "destination": "直连",
                }],
                "rule_order": [
                    rule_id,
                    *(str(item["index"]) for item in options["matching_rules"]),
                ],
                "rule_destinations": {rule_id: "直连"},
            },
        })

        rules = [
            rule for rule in result["config"]["route"]["rules"]
            if rule.get("rule_set") == "geosite-custom"
        ]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["outbound"], "AI")
        application_group = next(
            item for item in result["config"]["outbounds"]
            if item["tag"] == "AI"
        )
        self.assertEqual(application_group["outbounds"][0], "直连")

    def test_composition_preserves_selected_default_for_manual_application_outbound(self):
        template = _load_named_template("config_phone.json")
        options = _template_options(template)
        ai_rule = next(
            item for item in options["matching_rules"]
            if item["outbound"] == "AI"
        )
        rule_id = str(ai_rule["index"])
        result = convert_request({
            "content": SAMPLE_SUBSCRIPTION,
            "template": "config_phone.json",
            "template_options": {
                "rule_order": [str(item["index"]) for item in options["matching_rules"]],
                "rule_destinations": {rule_id: "香港手动"},
            },
        })

        group = next(
            item for item in result["config"]["outbounds"]
            if item["tag"] == "AI"
        )
        self.assertEqual(group["outbounds"][0], "香港手动")

    def test_composed_template_rejects_custom_rule_sets_without_http_url(self):
        with self.assertRaisesRegex(ValueError, "HTTP 或 HTTPS"):
            convert_request({
                "content": SAMPLE_SUBSCRIPTION,
                "template": "config_phone.json",
                "template_options": {
                    "custom_rule_sets": [{
                        "tag": "example",
                        "url": "file:///tmp/rules.srs",
                        "format": "binary",
                        "outbound": "默认代理",
                    }],
                },
            })

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

    def test_paste_api_applies_configuration_options(self):
        status, result = self.post_json(
            "/api",
            {
                "content": SAMPLE_SUBSCRIPTION,
                "template": "config_phone.json",
                "template_options": {
                    "dns_final": "alibaba-cloud-dns",
                    "rule_sets": ["geosite-ai"],
                },
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["config"]["dns"]["final"], "alibaba-cloud-dns")
        self.assertEqual(
            {item["tag"] for item in result["config"]["route"]["rule_set"]},
            {"geosite-ai"},
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

    def test_link_endpoint_applies_configuration_options(self):
        with patch(
            "web_server.fetch_remote_subscription",
            return_value=SAMPLE_SUBSCRIPTION,
        ):
            status, result = self.post_json(
                "/fetch",
                {
                    "url": "https://subscriptions.example/sub",
                    "template": "config_phone.json",
                    "template_options": {"dns_final": "alibaba-cloud-dns"},
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["config"]["dns"]["final"], "alibaba-cloud-dns")

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


if __name__ == "__main__":
    unittest.main()
