def get_template_options(template):
    dns = template.get("dns", {})
    dns_servers = dns.get("servers", []) if isinstance(dns, dict) else []
    outbounds = template.get("outbounds", [])
    outbound_tags = {
        item["tag"]
        for item in outbounds
        if isinstance(item, dict) and isinstance(item.get("tag"), str)
    }
    route = template.get("route", {})
    protected_groups = {
        route.get("final")
    } if isinstance(route, dict) else set()
    protected_groups.update(
        server.get("detour")
        for server in dns_servers
        if isinstance(server, dict) and server.get("detour")
    )
    non_application_groups = {
        "默认代理", "手动选择", "自动选择", "漏网之鱼", "GLOBAL", "延迟辅助",
    }
    groups = [
        {
            "tag": item["tag"],
            "type": item["type"],
            "members": item.get("outbounds", []),
            "required": item["tag"] in protected_groups,
            "application": (
                item["type"] == "selector"
                and item["tag"] not in non_application_groups
                and not item["tag"].endswith(("手动", "自动"))
            ),
            "rule_target": item["tag"] not in {
                "日本手动", "狮城手动", "香港手动", "台湾手动", "美国手动",
                "日本自动", "狮城自动", "香港自动", "台湾自动", "美国自动",
                "延迟辅助",
            },
        }
        for item in outbounds
        if isinstance(item, dict)
        and item.get("type") in ("selector", "urltest")
        and isinstance(item.get("tag"), str)
    ]
    rule_sets = []
    if isinstance(route, dict):
        for item in route.get("rule_set", []):
            if not isinstance(item, dict):
                continue
            tags = item.get("tag")
            for tag in tags if isinstance(tags, list) else [tags]:
                if isinstance(tag, str):
                    rule_sets.append({"tag": tag, "url": item.get("url", "")})
    matching_rules = []
    if isinstance(route, dict):
        for index, item in enumerate(route.get("rules", [])):
            if not isinstance(item, dict) or not isinstance(item.get("outbound"), str):
                continue
            match = {
                key: value for key, value in item.items()
                if key not in ("outbound", "action")
            }
            if match:
                matching_rules.append({
                    "index": index,
                    "match": match,
                    "outbound": item["outbound"],
                })
    return {
        "dns_servers": [
            {
                "tag": item["tag"],
                "type": item.get("type", ""),
                "server": item.get("server", ""),
                "name": {
                    "alibaba-cloud-dns": "阿里云 DNS（223.5.5.5）",
                    "tencent-dnspod-dns": "腾讯 DNSPod",
                    "google-public-dns": "Google Public DNS",
                    "local": "本地 DNS",
                    "hosts": "Hosts",
                    "fakeip": "FakeIP DNS",
                }.get(item["tag"], item["tag"]),
                "category": (
                    "builtin"
                    if item.get("type") in ("local", "hosts", "fakeip")
                    else "domestic"
                    if item["tag"] in (
                        "alibaba-cloud-dns", "tencent-dnspod-dns",
                        "dns-alibaba-cloud-doh", "dns-tencent-dnspod-doh",
                        "dns-114-udp", "dns-tencent-dnspod-udp",
                        "dns-alibaba-cloud-dot",
                    )
                    else "international"
                ),
            }
            for item in dns_servers
            if isinstance(item, dict) and isinstance(item.get("tag"), str)
        ],
        "dns_final": dns.get("final", "") if isinstance(dns, dict) else "",
        "groups": groups,
        "rule_sets": rule_sets,
        "matching_rules": matching_rules,
        "rule_targets": [
            *[item["tag"] for item in groups if item["rule_target"]],
            *( ["直连"] if "直连" in outbound_tags else []),
        ],
        "matching_targets": [
            *[
                item["tag"] for item in groups
                if item["tag"] != "延迟辅助" and not item["application"]
            ],
            *( ["直连"] if "直连" in outbound_tags else []),
        ],
        "outbounds": [
            item["tag"]
            for item in outbounds
            if isinstance(item, dict) and isinstance(item.get("tag"), str)
        ],
    }