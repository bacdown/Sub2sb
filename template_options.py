import copy
import re
import urllib.parse


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
                    "alibaba-cloud-dns": "阿里云 DNS",
                    "tencent-dnspod-dns": "腾讯DNS",
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


def _filter_rule_sets(value, selected_tags):
    if isinstance(value, list):
        return [
            filtered
            for item in value
            if (filtered := _filter_rule_sets(item, selected_tags)) is not None
        ]
    if not isinstance(value, dict):
        return value

    filtered = copy.deepcopy(value)
    if "rule_set" in filtered:
        tags = filtered["rule_set"]
        if isinstance(tags, list):
            tags = [tag for tag in tags if tag in selected_tags]
        elif tags not in selected_tags:
            return None
        if not tags:
            return None
        filtered["rule_set"] = tags
    if "rules" in filtered:
        filtered["rules"] = _filter_rule_sets(filtered["rules"], selected_tags)
        if not filtered["rules"]:
            return None
    return filtered


def _custom_tag(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    value = value.strip()
    if not re.fullmatch(r"[\w.-]+", value, flags=re.UNICODE):
        raise ValueError(f"{label}只能包含字母、数字、下划线、连字符和点")
    return value


def apply_template_options(template, options):
    if not isinstance(options, dict):
        raise ValueError("template_options 必须是对象")

    result = copy.deepcopy(template)
    metadata = get_template_options(result)
    dns = result.get("dns")
    route = result.get("route")
    if not isinstance(dns, dict) or not isinstance(route, dict):
        raise ValueError("所选模板不支持自定义 DNS 和分流配置")
    for item in metadata["matching_rules"]:
        route["rules"][item["index"]]["__builder_rule_id"] = str(item["index"])

    dns_tag_order = [item["tag"] for item in metadata["dns_servers"]]
    dns_tags = set(dns_tag_order)
    selected_dns = options.get("dns_servers", dns_tag_order)
    if not isinstance(selected_dns, list) or any(
        not isinstance(tag, str) or tag not in dns_tags for tag in selected_dns
    ):
        raise ValueError("dns_servers 包含模板中不存在的 DNS 标签")
    selected_dns = set(selected_dns)
    builtin_dns_tags = {
        item["tag"] for item in metadata["dns_servers"]
        if item["category"] == "builtin"
    }
    selected_dns.update(builtin_dns_tags)
    custom_dns = options.get("custom_dns_servers", [])
    if not isinstance(custom_dns, list):
        raise ValueError("custom_dns_servers 必须是数组")
    custom_dns_tags = set()
    for item in custom_dns:
        if not isinstance(item, dict):
            raise ValueError("自定义 DNS 必须是对象")
        tag = _custom_tag(item.get("tag"), "DNS 标签")
        if tag in dns_tags or tag in custom_dns_tags:
            raise ValueError(f"DNS 标签重复：{tag}")
        if item.get("type") not in ("local", "https", "tls", "udp", "tcp", "quic", "h3"):
            raise ValueError(f"不支持的自定义 DNS 类型：{item.get('type')}")
        if item["type"] != "local" and (
            not isinstance(item.get("server"), str) or not item["server"].strip()
        ):
            raise ValueError(f"DNS {tag} 缺少 server")
        if "server_port" in item and (
            not isinstance(item["server_port"], int)
            or not 1 <= item["server_port"] <= 65535
        ):
            raise ValueError(f"DNS {tag} 的 server_port 必须是 1 到 65535 的整数")
        custom_dns_tags.add(tag)
    if selected_dns == builtin_dns_tags and not custom_dns:
        raise ValueError("至少保留一个 DNS 服务器")

    old_final = dns.get("final")
    dns_final = options.get("dns_final", old_final)
    available_dns = selected_dns | custom_dns_tags
    if not isinstance(dns_final, str):
        raise ValueError("dns_final 必须是 DNS 标签")
    if dns_final not in available_dns:
        if "dns_final" in options:
            raise ValueError("dns_final 必须指向已保留或新添加的 DNS 服务器")
        dns_final = next(
            (
                tag for tag in dns_tag_order
                if tag in selected_dns and tag not in builtin_dns_tags
            ),
            next(iter(custom_dns_tags), None),
        )
        if dns_final is None:
            dns_final = next(iter(builtin_dns_tags), None)
    if dns_final is None:
        raise ValueError("DNS final 必须指向一个可用的 DNS 标签")

    dns["servers"] = [
        server for server in dns.get("servers", [])
        if isinstance(server, dict) and server.get("tag") in selected_dns
    ]
    dns["servers"].extend(copy.deepcopy(custom_dns))
    dns["final"] = dns_final

    removed_dns = dns_tags - selected_dns
    fallback_dns = dns_final

    def replace_dns_references(value):
        if isinstance(value, list):
            for index, item in enumerate(value):
                value[index] = replace_dns_references(item)
            return value
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if (
                    key in ("server", "domain_resolver")
                    and isinstance(item, str)
                    and item in removed_dns
                ):
                    value[key] = fallback_dns
                else:
                    value[key] = replace_dns_references(item)
            return value
        return value

    result = replace_dns_references(result)

    group_tags = {item["tag"] for item in metadata["groups"]}
    selected_groups = options.get("groups", list(group_tags))
    if not isinstance(selected_groups, list) or any(
        not isinstance(tag, str) or tag not in group_tags for tag in selected_groups
    ):
        raise ValueError("groups 包含模板中不存在的分流组")
    selected_groups = set(selected_groups)
    required_groups = {
        item["tag"] for item in metadata["groups"] if item["required"]
    }
    if not required_groups.issubset(selected_groups):
        raise ValueError("不能移除被模板默认 DNS 或路由引用的分流组")

    custom_groups = options.get("custom_groups", [])
    if not isinstance(custom_groups, list):
        raise ValueError("custom_groups 必须是数组")
    removed_groups = group_tags - selected_groups
    all_outbound_tags = set(metadata["outbounds"]) - removed_groups
    group_definitions = []
    for item in custom_groups:
        if not isinstance(item, dict):
            raise ValueError("自定义分流组必须是对象")
        tag = _custom_tag(item.get("tag"), "分流组标签")
        if tag in metadata["outbounds"] or tag in all_outbound_tags:
            raise ValueError(f"分流组标签重复：{tag}")
        members = item.get("outbounds", [])
        member_rule_sets = item.get("rule_sets", [])
        if not isinstance(members, list) or any(
            not isinstance(member, str)
            or member not in all_outbound_tags | {group["tag"] for group in group_definitions}
            for member in members
        ):
            raise ValueError(f"分流组 {tag} 包含模板中不存在的成员")
        if not isinstance(member_rule_sets, list) or any(
            not isinstance(rule_tag, str) for rule_tag in member_rule_sets
        ):
            raise ValueError(f"分流组 {tag} 的规则集必须是标签数组")
        resolved_members = list(dict.fromkeys(members))
        if not resolved_members:
            resolved_members = [
                member for member in ("默认代理", "手动选择", "自动选择")
                if member in all_outbound_tags
            ]
        group_definitions.append(
            {
                "tag": tag,
                "type": "selector",
                "outbounds": resolved_members,
                "rule_sets": list(dict.fromkeys(member_rule_sets)),
            }
        )
        all_outbound_tags.add(tag)

    result["outbounds"] = [
        item for item in result.get("outbounds", [])
        if not isinstance(item, dict) or item.get("tag") not in removed_groups
    ]
    for outbound in result["outbounds"]:
        members = outbound.get("outbounds")
        if isinstance(members, list):
            outbound["outbounds"] = [
                tag for tag in members if tag not in removed_groups
            ]
    result["outbounds"].extend(group_definitions)

    rule_set_tags = {item["tag"] for item in metadata["rule_sets"]}
    selected_rule_sets = options.get(
        "rule_sets", [item["tag"] for item in metadata["rule_sets"]]
    )
    if not isinstance(selected_rule_sets, list) or any(
        not isinstance(tag, str) or tag not in rule_set_tags
        for tag in selected_rule_sets
    ):
        raise ValueError("rule_sets 包含模板中不存在的规则集")
    selected_rule_sets = set(selected_rule_sets)
    rule_set_entries = []
    for item in route.get("rule_set", []):
        tags = item.get("tag") if isinstance(item, dict) else None
        if isinstance(tags, list):
            retained = [tag for tag in tags if tag in selected_rule_sets]
            if not retained:
                continue
            item = {**item, "tag": retained}
        elif tags not in selected_rule_sets:
            continue
        rule_set_entries.append(item)

    custom_rule_sets = options.get("custom_rule_sets", [])
    if not isinstance(custom_rule_sets, list):
        raise ValueError("custom_rule_sets 必须是数组")
    custom_matching_rules = options.get("custom_matching_rules", [])
    if not isinstance(custom_matching_rules, list):
        raise ValueError("custom_matching_rules 必须是数组")
    builder_rule_sets = {
        item.get("rule_set")
        for item in custom_matching_rules
        if isinstance(item, dict) and isinstance(item.get("rule_set"), str)
    }
    rule_set_links_only = options.get("rule_set_links_only", False)
    if not isinstance(rule_set_links_only, bool):
        raise ValueError("rule_set_links_only 必须是布尔值")
    custom_rules = []
    known_rule_set_tags = rule_set_tags | {
        item["tag"]
        for item in custom_rule_sets
        if isinstance(item, dict) and isinstance(item.get("tag"), str)
    }
    grouped_rule_sets = set()
    grouped_rule_targets = {}
    for group in group_definitions:
        for rule_tag in group.pop("rule_sets"):
            if rule_tag not in known_rule_set_tags:
                raise ValueError(
                    f"分流组 {group['tag']} 引用了不存在的规则集：{rule_tag}"
                )
            if rule_tag in grouped_rule_sets:
                raise ValueError(f"规则集不能同时加入多个分流组：{rule_tag}")
            grouped_rule_sets.add(rule_tag)
            grouped_rule_targets[rule_tag] = group["tag"]

    default_matching_rules = {
        str(item["index"]): route["rules"][item["index"]]
        for item in metadata["matching_rules"]
    }
    available_rule_targets = (
        set(metadata["rule_targets"]) - removed_groups
    ) | {group["tag"] for group in group_definitions}
    if "直连" in metadata["outbounds"]:
        available_rule_targets.add("直连")
    for rule_tag, group_tag in grouped_rule_targets.items():
        if rule_tag not in selected_rule_sets:
            continue
        for rule in default_matching_rules.values():
            tags = rule.get("rule_set")
            tags = tags if isinstance(tags, list) else [tags]
            if rule_tag in tags:
                rule["outbound"] = group_tag

    for item in custom_rule_sets:
        if not isinstance(item, dict):
            raise ValueError("自定义规则集必须是对象")
        tag = _custom_tag(item.get("tag"), "规则集标签")
        url = item.get("url")
        rule_format = item.get("format")
        outbound = item.get("outbound")
        if tag in rule_set_tags or sum(
            1 for other in custom_rule_sets
            if isinstance(other, dict) and other.get("tag") == tag
        ) > 1:
            raise ValueError(f"规则集标签重复：{tag}")
        parsed_url = urllib.parse.urlsplit(url.strip()) if isinstance(url, str) else None
        if (
            parsed_url is None
            or parsed_url.scheme not in ("http", "https")
            or not parsed_url.hostname
        ):
            raise ValueError(f"规则集 {tag} 的链接必须使用 HTTP 或 HTTPS")
        if rule_format not in ("binary", "source"):
            raise ValueError(f"规则集 {tag} 的 format 必须是 binary 或 source")
        if tag in rule_set_tags:
            raise ValueError(f"规则集标签重复：{tag}")
        outbound = grouped_rule_targets.get(tag, outbound)
        if not isinstance(outbound, str) or outbound not in available_rule_targets:
            raise ValueError(f"规则集 {tag} 指向了不存在的分流组")
        rule_set_entries.append(
            {"tag": tag, "type": "remote", "format": rule_format, "url": url.strip()}
        )
        if tag not in builder_rule_sets and not rule_set_links_only:
            custom_rules.append({
                "rule_set": tag,
                "outbound": outbound,
                "__builder_rule_id": f"custom:{tag}",
            })

    builder_rules = []
    builder_rule_ids = set()
    builder_destinations = {}
    application_tags = {
        item["tag"] for item in metadata["groups"] if item["application"]
    }
    valid_application_tags = application_tags - removed_groups
    valid_application_tags.update(group["tag"] for group in group_definitions)
    default_group = next(
        (
            item for item in result["outbounds"]
            if isinstance(item, dict)
            and item.get("tag") == "默认代理"
            and item.get("type") == "selector"
        ),
        None,
    )
    default_members = (
        default_group.get("outbounds", [])
        if isinstance(default_group, dict)
        and isinstance(default_group.get("outbounds"), list)
        else []
    )
    for item in custom_matching_rules:
        if not isinstance(item, dict):
            raise ValueError("自定义匹配规则必须是对象")
        rule_id = _custom_tag(item.get("id"), "匹配规则 ID")
        name = item.get("name")
        rule_set = item.get("rule_set")
        outbound = item.get("outbound")
        destination = item.get("destination")
        if not rule_id.startswith("builder-") or rule_id in builder_rule_ids:
            raise ValueError(f"自定义匹配规则 ID 无效或重复：{rule_id}")
        name = _custom_tag(name, "应用分流名称")
        if name not in valid_application_tags:
            if name in metadata["outbounds"] or name in all_outbound_tags:
                raise ValueError(f"名称 {name} 不是可用的应用分流组")
            if not isinstance(destination, str) or not destination:
                raise ValueError(f"自定义应用分流 {name} 缺少初始出站")
            members = list(dict.fromkeys([destination, *default_members]))
            members = [destination, *(member for member in members if member != destination)]
            group = {"tag": name, "type": "selector", "outbounds": members}
            group_definitions.append(group)
            result["outbounds"].append(group)
            all_outbound_tags.add(name)
            valid_application_tags.add(name)
        if not isinstance(destination, str) or not destination:
            raise ValueError(f"匹配规则 {rule_id} 缺少初始出站")
        if not isinstance(rule_set, str) or rule_set not in known_rule_set_tags:
            raise ValueError(f"匹配规则 {rule_id} 指向了不存在的规则集")
        custom_rule_set_tags = {
            custom_item.get("tag")
            for custom_item in custom_rule_sets
            if isinstance(custom_item, dict)
        }
        if rule_set not in selected_rule_sets and rule_set not in custom_rule_set_tags:
            raise ValueError(f"匹配规则 {rule_id} 指向了未选择的规则集")
        if outbound != name:
            raise ValueError(f"匹配规则 {rule_id} 的出站必须与应用分流名称一致")
        builder_rule_ids.add(rule_id)
        builder_destinations[rule_id] = destination
        builder_rules.append({
            "rule_set": rule_set,
            "outbound": name,
            "__builder_rule_id": rule_id,
        })

    rule_outbounds = options.get("rule_outbounds", {})
    if not isinstance(rule_outbounds, dict):
        raise ValueError("rule_outbounds 必须是对象")
    rule_by_id = {
        **default_matching_rules,
        **{
            f"custom:{item['tag']}": rule
            for item, rule in zip(custom_rule_sets, custom_rules)
        },
        **{
            rule["__builder_rule_id"]: rule
            for rule in builder_rules
        },
    }
    available_matching_targets = (
        set(metadata["matching_targets"]) - removed_groups
    ) | {group["tag"] for group in group_definitions}
    if "直连" in metadata["outbounds"]:
        available_matching_targets.add("直连")
    available_destinations = available_matching_targets - valid_application_tags
    for rule_id, outbound in rule_outbounds.items():
        if rule_id not in rule_by_id:
            raise ValueError(f"rule_outbounds 包含不存在的匹配规则：{rule_id}")
        is_builder_rule = rule_id in builder_rule_ids
        available_targets = (
            valid_application_tags if is_builder_rule else available_matching_targets
        )
        if not isinstance(outbound, str) or outbound not in available_targets:
            raise ValueError(f"匹配规则指向了不可用的分流组：{outbound}")
        rule_by_id[rule_id]["outbound"] = outbound

    rule_destinations = options.get("rule_destinations", {})
    if not isinstance(rule_destinations, dict):
        raise ValueError("rule_destinations 必须是对象")
    rule_destinations = {**builder_destinations, **rule_destinations}
    destinations_by_group = {}
    for rule_id, destination in rule_destinations.items():
        if rule_id not in rule_by_id:
            raise ValueError(f"rule_destinations 包含不存在的匹配规则：{rule_id}")
        if not isinstance(destination, str) or destination not in available_destinations:
            raise ValueError(f"匹配规则指向了不可用的目标出站：{destination}")
        group_tag = rule_by_id[rule_id].get("outbound")
        if group_tag in removed_groups:
            continue
        if group_tag not in valid_application_tags:
            raise ValueError(f"匹配规则 {rule_id} 不对应应用分流组")
        previous_destination = destinations_by_group.get(group_tag)
        if previous_destination is not None and previous_destination != destination:
            raise ValueError(
                f"应用分流组 {group_tag} 的匹配规则选择了不同的初始出站"
            )
        destinations_by_group[group_tag] = destination
        target_group = next(
            (
                item for item in result["outbounds"]
                if isinstance(item, dict) and item.get("tag") == group_tag
            ),
            None,
        )
        if not isinstance(target_group, dict) or target_group.get("type") != "selector":
            raise ValueError(f"应用分流组不存在或不是 selector：{group_tag}")
        members = target_group.get("outbounds", [])
        if not isinstance(members, list):
            raise ValueError(f"应用分流组 {group_tag} 的 outbounds 必须是数组")
        target_group["outbounds"] = [
            destination,
            *(member for member in members if member != destination),
        ]

    route["rules"] = [
        rule for rule in route.get("rules", [])
        if not isinstance(rule, dict) or rule.get("outbound") not in removed_groups
    ]
    route["rule_set"] = rule_set_entries
    route["rules"] = _filter_rule_sets(route.get("rules", []), selected_rule_sets)
    dns["rules"] = _filter_rule_sets(dns.get("rules", []), selected_rule_sets)
    custom_rule_position = next(
        (
            index for index, rule in enumerate(route["rules"])
            if isinstance(rule, dict) and "rule_set" in rule and "outbound" in rule
        ),
        len(route["rules"]),
    )
    route["rules"][custom_rule_position:custom_rule_position] = [
        *custom_rules,
        *builder_rules,
    ]

    rule_order = options.get("rule_order")
    if rule_order is not None:
        expected_rule_ids = [
            *(str(item["index"]) for item in metadata["matching_rules"]),
            *(rule["__builder_rule_id"] for rule in custom_rules),
            *(rule["__builder_rule_id"] for rule in builder_rules),
        ]
        if (
            not isinstance(rule_order, list)
            or any(not isinstance(rule_id, str) for rule_id in rule_order)
            or len(set(rule_order)) != len(rule_order)
            or not set(rule_order).issubset(expected_rule_ids)
        ):
            raise ValueError("rule_order 必须是有效匹配规则 ID 的有序子集")
        retained_rule_ids = set(rule_order)
        removed_rule_ids = set(expected_rule_ids) - retained_rule_ids
        route["rules"] = [
            rule for rule in route["rules"]
            if not (
                isinstance(rule, dict)
                and rule.get("__builder_rule_id") in removed_rule_ids
            )
        ]
        matching_by_id = {
            rule["__builder_rule_id"]: rule
            for rule in route["rules"]
            if isinstance(rule, dict) and "__builder_rule_id" in rule
        }
        ordered_rules = [
            matching_by_id[rule_id]
            for rule_id in rule_order
            if rule_id in matching_by_id
        ]
        matching_slots = [
            index for index, rule in enumerate(route["rules"])
            if isinstance(rule, dict) and "__builder_rule_id" in rule
        ]
        for index, rule in zip(matching_slots, ordered_rules):
            route["rules"][index] = rule
    for rule in route["rules"]:
        if isinstance(rule, dict):
            rule.pop("__builder_rule_id", None)

    for group in group_definitions:
        global_group = next(
            (
                outbound for outbound in result["outbounds"]
                if outbound.get("tag") == "GLOBAL" and outbound.get("type") == "selector"
            ),
            None,
        )
        if global_group is not None:
            global_group["outbounds"].append(group["tag"])
    return result
