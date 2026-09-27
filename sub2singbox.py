#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将 Clash YAML、Base64 订阅、URI 订阅转换为 sing-box 配置。

支持：
- Clash YAML
- Base64 编码的 Clash YAML
- Base64 URI 订阅
- 明文 URI 订阅
- vmess://
- vless://
- trojan://
- ss://
- hysteria2://
- hy2://
- tuic

用法：

    python3 sub2singbox.py "订阅链接" -o sing-box.json

或者：

    python3 sub2singbox.py clash.yaml -o sing-box.json
"""

import argparse
import base64
import copy
import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:
    import yaml
except ImportError:
    print(
        "缺少 PyYAML 依赖，请先执行：python3 -m pip install pyyaml",
        file=sys.stderr
    )
    sys.exit(1)


SUPPORTED_URI_PREFIXES = (
    "vmess://",
    "vless://",
    "trojan://",
    "ss://",
    "hysteria2://",
    "hy2://",
    "tuic://",
)

SUBSCRIPTION_INFO_KEYWORDS = (
    "剩余流量",
    "剩余：",
    "剩余:",
    "距离下次重置",
    "下次重置",
    "重置时间",
    "流量重置",
    "套餐到期",
    "到期时间",
    "到期日期",
    "过期时间",
    "有效期",
    "订阅信息",
    "订阅地址",
)


def is_probably_subscription_text(text):
    """
    判断文本是否已经是明文订阅，而不是 Base64。
    """
    stripped = text.lstrip()

    if any(prefix in stripped for prefix in SUPPORTED_URI_PREFIXES):
        return True

    yaml_markers = (
        "proxies:",
        "proxy-groups:",
        "proxy-providers:",
        "port:",
        "mixed-port:",
        "socks-port:",
        "rules:",
    )

    return stripped.startswith(yaml_markers) or stripped.startswith("{")


def b64decode_auto(value):
    """
    自动处理普通 Base64、URL-safe Base64 和缺少 padding 的情况。
    """
    value = value.strip()
    value += "=" * (-len(value) % 4)

    try:
        raw = base64.urlsafe_b64decode(value)
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def get_subscription(url):
    """
    下载订阅内容。

    订阅可能是：
    1. 明文 URI
    2. Base64 URI
    3. Clash YAML
    4. Base64 编码的 Clash YAML
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sub2singbox/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()

    text = data.decode("utf-8", errors="replace").strip()

    # 明文 URI 或明文 YAML
    if is_probably_subscription_text(text):
        return text

    # 尝试 Base64 解码
    decoded = b64decode_auto(text)

    if decoded and is_probably_subscription_text(decoded):
        return decoded

    # 即使无法判断，也返回原始文本，后续会给出错误提示
    return text


def node_name(parsed_uri, default_name):
    """
    获取 URI 中的节点名称。
    """
    if parsed_uri.fragment:
        return urllib.parse.unquote(parsed_uri.fragment)

    return default_name


def parse_vmess(uri):
    """
    解析 vmess://Base64JSON
    """
    try:
        encoded = uri[len("vmess://"):]
        decoded = b64decode_auto(encoded)
        data = json.loads(decoded)

        server = data["add"]
        port = int(data["port"])
        uuid = data["id"]

        outbound = {
            "type": "vmess",
            "tag": data.get("ps") or data.get("remark") or "VMess",
            "server": server,
            "server_port": port,
            "uuid": uuid,
            "security": data.get("scy") or "auto",
        }

        alter_id = data.get("aid")

        if alter_id not in (None, "", "0", 0):
            outbound["alter_id"] = int(alter_id)

        network = str(data.get("net") or "tcp").lower()

        if network == "ws":
            transport = {
                "type": "ws",
                "path": data.get("path") or "/",
            }

            host = data.get("host")
            if host:
                transport["headers"] = {
                    "Host": host
                }

            outbound["transport"] = transport

        elif network == "grpc":
            outbound["transport"] = {
                "type": "grpc",
                "service_name": data.get("path") or "",
            }

        elif network == "http":
            outbound["transport"] = {
                "type": "http",
                "path": data.get("path") or "/",
            }

        tls_enabled = str(data.get("tls") or "").lower() in (
            "tls",
            "1",
            "true",
            "yes",
        )

        if tls_enabled:
            tls = {
                "enabled": True,
                "server_name": (
                    data.get("sni")
                    or data.get("host")
                    or server
                ),
            }

            if data.get("fp"):
                tls["utls"] = {
                    "enabled": True,
                    "fingerprint": data["fp"],
                }

            outbound["tls"] = tls

        return outbound

    except Exception as exc:
        raise ValueError(f"VMess 解析失败：{exc}")


def parse_vless(uri):
    """
    解析 vless://UUID@host:port?...#name
    """
    parsed = urllib.parse.urlsplit(uri)
    params = urllib.parse.parse_qs(parsed.query)

    def get_param(key, default=""):
        return params.get(key, [default])[0]

    if not parsed.hostname:
        raise ValueError("VLESS 缺少服务器地址")

    if not parsed.username:
        raise ValueError("VLESS 缺少 UUID")

    outbound = {
        "type": "vless",
        "tag": node_name(parsed, "VLESS"),
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "uuid": urllib.parse.unquote(parsed.username),
    }

    flow = get_param("flow")
    if flow:
        outbound["flow"] = flow

    packet_encoding = get_param("packetEncoding") or get_param(
        "packet-encoding"
    )

    if packet_encoding:
        outbound["packet_encoding"] = packet_encoding

    network = get_param("type", "tcp").lower()

    if network == "ws":
        transport = {
            "type": "ws",
            "path": get_param("path", "/"),
        }

        host = get_param("host")
        if host:
            transport["headers"] = {
                "Host": host
            }

        outbound["transport"] = transport

    elif network == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": (
                get_param("serviceName")
                or get_param("service-name")
            ),
        }

    elif network == "http":
        outbound["transport"] = {
            "type": "http",
            "path": get_param("path", "/"),
        }

    security = get_param("security").lower()

    if security in ("tls", "reality"):
        tls = {
            "enabled": True,
            "server_name": get_param("sni") or parsed.hostname,
        }

        fingerprint = get_param("fp")
        if fingerprint:
            tls["utls"] = {
                "enabled": True,
                "fingerprint": fingerprint,
            }

        if security == "reality":
            tls["reality"] = {
                "enabled": True,
                "public_key": get_param("pbk"),
                "short_id": get_param("sid"),
            }

        if get_param("allowInsecure").lower() in (
            "1",
            "true",
            "yes",
        ):
            tls["insecure"] = True

        outbound["tls"] = tls

    return outbound


def parse_trojan(uri):
    """
    解析 trojan://password@host:port?...#name
    """
    parsed = urllib.parse.urlsplit(uri)
    params = urllib.parse.parse_qs(parsed.query)

    def get_param(key, default=""):
        return params.get(key, [default])[0]

    if not parsed.hostname:
        raise ValueError("Trojan 缺少服务器地址")

    outbound = {
        "type": "trojan",
        "tag": node_name(parsed, "Trojan"),
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "password": urllib.parse.unquote(parsed.username or ""),
    }

    network = get_param("type", "tcp").lower()

    if network == "ws":
        transport = {
            "type": "ws",
            "path": get_param("path", "/"),
        }

        host = get_param("host")
        if host:
            transport["headers"] = {
                "Host": host
            }

        outbound["transport"] = transport

    elif network == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": (
                get_param("serviceName")
                or get_param("service-name")
            ),
        }

    outbound["tls"] = {
        "enabled": True,
        "server_name": get_param("sni") or parsed.hostname,
    }

    if get_param("allowInsecure").lower() in (
        "1",
        "true",
        "yes",
    ):
        outbound["tls"]["insecure"] = True

    return outbound


def parse_ss(uri):
    """
    解析以下两种常见格式：

    ss://base64(method:password)@host:port#name

    ss://base64(method:password@host:port)#name
    """
    parsed = urllib.parse.urlsplit(uri)

    # 格式一：ss://base64(method:password)@host:port
    if parsed.username:
        userinfo = urllib.parse.unquote(parsed.username)

        if ":" not in userinfo:
            raise ValueError("SS 用户信息格式错误")

        method, password = userinfo.split(":", 1)

        if not parsed.hostname:
            raise ValueError("SS 缺少服务器地址")

        return {
            "type": "shadowsocks",
            "tag": node_name(parsed, "Shadowsocks"),
            "server": parsed.hostname,
            "server_port": parsed.port or 443,
            "method": method,
            "password": password,
        }

    # 格式二：ss://base64(method:password@host:port)#name
    raw = uri[len("ss://"):]

    if "#" in raw:
        encoded, fragment = raw.split("#", 1)
        tag = urllib.parse.unquote(fragment)
    else:
        encoded = raw
        tag = "Shadowsocks"

    decoded = b64decode_auto(encoded)

    if "@" not in decoded:
        raise ValueError("SS URI 格式错误")

    userinfo, address = decoded.rsplit("@", 1)

    if ":" not in userinfo:
        raise ValueError("SS 用户信息格式错误")

    method, password = userinfo.split(":", 1)

    if ":" not in address:
        raise ValueError("SS 服务器地址格式错误")

    host, port = address.rsplit(":", 1)

    return {
        "type": "shadowsocks",
        "tag": tag,
        "server": host,
        "server_port": int(port),
        "method": method,
        "password": password,
    }


def parse_hysteria2(uri):
    """
    解析 hysteria2://password@host:port?...#name
    """
    parsed = urllib.parse.urlsplit(uri)
    params = urllib.parse.parse_qs(parsed.query)

    def get_param(key, default=""):
        return params.get(key, [default])[0]

    if not parsed.hostname:
        raise ValueError("Hysteria2 缺少服务器地址")

    outbound = {
        "type": "hysteria2",
        "tag": node_name(parsed, "Hysteria2"),
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "password": urllib.parse.unquote(parsed.username or ""),
    }

    obfs = get_param("obfs")

    if obfs:
        outbound["obfs"] = {
            "type": obfs,
            "password": get_param("obfs-password"),
        }

    tls = {
        "enabled": True,
        "server_name": get_param("sni") or parsed.hostname,
    }

    if get_param("insecure").lower() in ("1", "true", "yes"):
        tls["insecure"] = True

    outbound["tls"] = tls

    return outbound


def parse_tuic(uri):
    """
    解析常见 tuic:// URI。
    """
    parsed = urllib.parse.urlsplit(uri)
    params = urllib.parse.parse_qs(parsed.query)

    def get_param(key, default=""):
        return params.get(key, [default])[0]

    if not parsed.hostname:
        raise ValueError("TUIC 缺少服务器地址")

    uuid = urllib.parse.unquote(parsed.username or "")
    password = urllib.parse.unquote(parsed.password or "")

    outbound = {
        "type": "tuic",
        "tag": node_name(parsed, "TUIC"),
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "uuid": uuid,
        "password": password,
        "congestion_control": get_param(
            "congestion_control",
            "cubic",
        ),
    }

    udp_relay_mode = get_param("udp_relay_mode")
    if udp_relay_mode:
        outbound["udp_relay_mode"] = udp_relay_mode

    outbound["tls"] = {
        "enabled": True,
        "server_name": get_param("sni") or parsed.hostname,
    }

    return outbound


def parse_uri(uri):
    """
    根据 URI 协议类型选择解析器。
    """
    uri = uri.strip()

    if not uri or uri.startswith("#"):
        return None

    try:
        if uri.startswith("vmess://"):
            return parse_vmess(uri)

        if uri.startswith("vless://"):
            return parse_vless(uri)

        if uri.startswith("trojan://"):
            return parse_trojan(uri)

        if uri.startswith("ss://"):
            return parse_ss(uri)

        if uri.startswith("hysteria2://"):
            return parse_hysteria2(uri)

        if uri.startswith("hy2://"):
            converted = "hysteria2://" + uri[len("hy2://"):]
            return parse_hysteria2(converted)

        if uri.startswith("tuic://"):
            return parse_tuic(uri)

    except Exception as exc:
        print(
            f"[跳过] {exc}: {uri[:100]}",
            file=sys.stderr
        )
        return None

    return None


def clash_tls_config(proxy):
    """
    转换 Clash 的 TLS、Reality、指纹和跳过证书验证设置。
    """
    reality_opts = proxy.get("reality-opts") or {}

    if not proxy.get("tls", False) and not reality_opts:
        return None

    tls = {
        "enabled": True,
    }

    server_name = (
        proxy.get("servername")
        or proxy.get("sni")
        or proxy.get("server")
    )

    if server_name:
        tls["server_name"] = server_name

    fingerprint = (
        proxy.get("client-fingerprint")
        or proxy.get("fingerprint")
    )

    if fingerprint:
        tls["utls"] = {
            "enabled": True,
            "fingerprint": fingerprint,
        }

    if proxy.get("skip-cert-verify", False):
        tls["insecure"] = True

    if reality_opts:
        tls["reality"] = {
            "enabled": True,
            "public_key": reality_opts.get("public-key", ""),
            "short_id": reality_opts.get("short-id", ""),
        }

    return tls


def clash_transport_config(proxy):
    """
    转换 Clash 的 network、ws-opts、grpc-opts、http-opts。
    """
    network = str(proxy.get("network", "")).lower()

    if network == "ws":
        ws_opts = proxy.get("ws-opts") or {}

        transport = {
            "type": "ws",
            "path": ws_opts.get("path") or "/",
        }

        headers = ws_opts.get("headers") or {}
        if headers:
            transport["headers"] = headers

        return transport

    if network == "grpc":
        grpc_opts = proxy.get("grpc-opts") or {}

        return {
            "type": "grpc",
            "service_name": (
                grpc_opts.get("grpc-service-name")
                or grpc_opts.get("service-name")
                or ""
            ),
        }

    if network == "http":
        http_opts = proxy.get("http-opts") or {}

        transport = {
            "type": "http",
            "path": http_opts.get("path") or "/",
        }

        headers = http_opts.get("headers") or {}
        if headers:
            transport["headers"] = headers

        return transport

    return None


def clash_proxy_to_outbound(proxy):
    """
    将单个 Clash proxies 节点转换为 sing-box outbound。
    """
    proxy_type = str(proxy.get("type", "")).lower()
    name = str(proxy.get("name") or "未命名节点")

    if not proxy.get("server"):
        raise ValueError("缺少 server")

    # Shadowsocks
    if proxy_type in ("ss", "shadowsocks"):
        if not proxy.get("cipher"):
            raise ValueError("Shadowsocks 缺少 cipher")

        if proxy.get("password") is None:
            raise ValueError("Shadowsocks 缺少 password")

        return {
            "type": "shadowsocks",
            "tag": name,
            "server": proxy["server"],
            "server_port": int(proxy.get("port", 443)),
            "method": proxy["cipher"],
            "password": str(proxy["password"]),
        }

    # VMess
    if proxy_type == "vmess":
        if not proxy.get("uuid"):
            raise ValueError("VMess 缺少 uuid")

        outbound = {
            "type": "vmess",
            "tag": name,
            "server": proxy["server"],
            "server_port": int(proxy.get("port", 443)),
            "uuid": proxy["uuid"],
            "security": proxy.get("cipher") or "auto",
        }

        alter_id = proxy.get("alterId")

        if alter_id not in (None, "", 0, "0"):
            outbound["alter_id"] = int(alter_id)

        transport = clash_transport_config(proxy)
        if transport:
            outbound["transport"] = transport

        tls = clash_tls_config(proxy)
        if tls:
            outbound["tls"] = tls

        return outbound

    # VLESS
    if proxy_type == "vless":
        if not proxy.get("uuid"):
            raise ValueError("VLESS 缺少 uuid")

        outbound = {
            "type": "vless",
            "tag": name,
            "server": proxy["server"],
            "server_port": int(proxy.get("port", 443)),
            "uuid": proxy["uuid"],
        }

        flow = proxy.get("flow")
        if flow:
            outbound["flow"] = flow

        packet_encoding = (
            proxy.get("packet-encoding")
            or proxy.get("packetEncoding")
        )

        if packet_encoding:
            outbound["packet_encoding"] = packet_encoding

        transport = clash_transport_config(proxy)
        if transport:
            outbound["transport"] = transport

        tls = clash_tls_config(proxy)
        if tls:
            outbound["tls"] = tls

        return outbound

    # Trojan
    if proxy_type == "trojan":
        if proxy.get("password") is None:
            raise ValueError("Trojan 缺少 password")

        outbound = {
            "type": "trojan",
            "tag": name,
            "server": proxy["server"],
            "server_port": int(proxy.get("port", 443)),
            "password": str(proxy["password"]),
        }

        transport = clash_transport_config(proxy)
        if transport:
            outbound["transport"] = transport

        tls = clash_tls_config(proxy)

        if tls is None:
            tls = {
                "enabled": True,
                "server_name": proxy.get("sni") or proxy["server"],
            }
            if proxy.get("skip-cert-verify", False):
                tls["insecure"] = True

        outbound["tls"] = tls

        return outbound

    # Hysteria2
    if proxy_type in ("hysteria2", "hy2"):
        password = (
            proxy.get("password")
            or proxy.get("auth")
            or ""
        )

        outbound = {
            "type": "hysteria2",
            "tag": name,
            "server": proxy["server"],
            "server_port": int(proxy.get("port", 443)),
            "password": str(password),
        }

        server_ports = proxy.get("ports") or proxy.get("mport")
        if server_ports:
            if not isinstance(server_ports, list):
                server_ports = str(server_ports).split(",")

            normalized_ports = []
            for port_range in server_ports:
                port_range = str(port_range).strip()
                if "-" in port_range:
                    first_port, last_port = port_range.split("-", 1)
                    port_range = f"{first_port}:{last_port}"
                if port_range:
                    normalized_ports.append(port_range)

            if normalized_ports:
                outbound.pop("server_port")
                outbound["server_ports"] = normalized_ports

        hop_interval = proxy.get("hop-interval") or proxy.get("hop_interval")
        if hop_interval:
            hop_interval = str(hop_interval).strip()
            if "-" in hop_interval:
                minimum, maximum = hop_interval.split("-", 1)
                outbound["hop_interval"] = f"{minimum}s"
                outbound["hop_interval_max"] = f"{maximum}s"
            else:
                if hop_interval.isdigit():
                    hop_interval += "s"
                outbound["hop_interval"] = hop_interval

        obfs = proxy.get("obfs")
        if obfs:
            outbound["obfs"] = {
                "type": obfs,
                "password": proxy.get("obfs-password", ""),
            }

        tls = clash_tls_config(proxy)

        if tls is None:
            tls = {
                "enabled": True,
                "server_name": proxy.get("sni") or proxy["server"],
            }
            if proxy.get("skip-cert-verify", False):
                tls["insecure"] = True

        outbound["tls"] = tls

        return outbound

    # TUIC
    if proxy_type == "tuic":
        if not proxy.get("uuid"):
            raise ValueError("TUIC 缺少 uuid")

        if proxy.get("password") is None:
            raise ValueError("TUIC 缺少 password")

        outbound = {
            "type": "tuic",
            "tag": name,
            "server": proxy["server"],
            "server_port": int(proxy.get("port", 443)),
            "uuid": proxy["uuid"],
            "password": str(proxy["password"]),
            "congestion_control": (
                proxy.get("congestion-controller")
                or proxy.get("congestion_control")
                or "cubic"
            ),
        }

        udp_relay_mode = (
            proxy.get("udp-relay-mode")
            or proxy.get("udp_relay_mode")
        )

        if udp_relay_mode:
            outbound["udp_relay_mode"] = udp_relay_mode

        outbound["tls"] = {
            "enabled": True,
            "server_name": proxy.get("sni") or proxy["server"],
        }

        return outbound

    raise ValueError(f"暂不支持 Clash 节点类型：{proxy_type}")


def parse_clash_yaml(content):
    """
    解析 Clash YAML 中的 proxies 列表。
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败：{exc}")

    if not isinstance(data, dict):
        raise ValueError("YAML 根节点不是对象")

    proxies = data.get("proxies")

    if not isinstance(proxies, list):
        raise ValueError("YAML 中没有找到 proxies 列表")

    outbounds = []

    for index, proxy in enumerate(proxies, 1):
        if not isinstance(proxy, dict):
            continue

        try:
            outbound = clash_proxy_to_outbound(proxy)
            outbounds.append(outbound)

        except Exception as exc:
            name = proxy.get("name", f"第 {index} 个节点")

            print(
                f"[跳过] {name}: {exc}",
                file=sys.stderr
            )

    return outbounds


def parse_subscription_content(content):
    """
    自动判断并解析：
    1. Clash YAML
    2. 明文 URI
    3. Base64 URI
    4. Base64 Clash YAML
    """
    content = content.strip()

    if not content:
        return []

    # 先尝试直接解析 Clash YAML
    try:
        yaml_data = yaml.safe_load(content)

        if (
            isinstance(yaml_data, dict)
            and isinstance(yaml_data.get("proxies"), list)
        ):
            return parse_clash_yaml(content)

    except yaml.YAMLError:
        pass

    # 如果不是 Clash YAML，则尝试按 URI 列表解析
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip()
    ]

    outbounds = []

    for line in lines:
        outbound = parse_uri(line)

        if outbound:
            outbounds.append(outbound)

    if outbounds:
        return outbounds

    # 最后尝试把整个内容作为 Base64 再解码一次
    decoded = b64decode_auto(content)

    if decoded and decoded != content:
        try:
            yaml_data = yaml.safe_load(decoded)

            if (
                isinstance(yaml_data, dict)
                and isinstance(yaml_data.get("proxies"), list)
            ):
                return parse_clash_yaml(decoded)

        except yaml.YAMLError:
            pass

        decoded_lines = [
            line.strip()
            for line in decoded.splitlines()
            if line.strip()
        ]

        for line in decoded_lines:
            outbound = parse_uri(line)

            if outbound:
                outbounds.append(outbound)

    return outbounds


def make_unique_tags(outbounds, reserved_tags=None):
    """
    确保所有节点 tag 唯一。
    """
    used = set(reserved_tags or ())

    for index, outbound in enumerate(outbounds, 1):
        original_tag = (
            outbound.get("tag")
            or f"节点 {index}"
        )

        tag = original_tag
        suffix = 2

        while tag in used:
            tag = f"{original_tag} {suffix}"
            suffix += 1

        outbound["tag"] = tag
        used.add(tag)


def filter_subscription_info_nodes(outbounds):
    """移除名称中包含订阅流量、重置或到期信息的伪节点。"""
    filtered = []

    for outbound in outbounds:
        tag = str(outbound.get("tag", ""))
        if any(keyword in tag for keyword in SUBSCRIPTION_INFO_KEYWORDS):
            print(f"[跳过] {tag}: 订阅状态信息不是代理节点", file=sys.stderr)
            continue
        filtered.append(outbound)

    return filtered


def region_for_node(tag):
    name = tag.lower()
    regions = {
        "日本手动": ("日本", "东京", "大阪", "名古屋", "🇯🇵", "japan", "tokyo", "osaka"),
        "狮城手动": ("新加坡", "狮城", "🇸🇬", "singapore"),
        "香港手动": ("香港", "🇭🇰", "hong kong", "hongkong"),
        "台湾手动": ("台湾", "台灣", "🇹🇼", "taiwan", "taipei", "taichung", "kaohsiung"),
        "美国手动": (
            "美国", "美國", "🇺🇸", "洛杉矶", "纽约", "西雅图", "硅谷",
            "圣何塞", "芝加哥", "达拉斯", "迈阿密", "usa", "united states",
            "los angeles", "new york", "seattle", "san jose", "chicago",
        ),
    }
    abbreviations = {
        "日本手动": r"\bjp\b",
        "狮城手动": r"\b(?:sg|sing)\b",
        "香港手动": r"\bhk\b",
        "台湾手动": r"\btw\b",
        "美国手动": r"\bus\b",
    }

    for group_tag, markers in regions.items():
        if any(marker in name for marker in markers) or re.search(abbreviations[group_tag], name):
            return group_tag

    return None


def merge_nodes_into_template(template, outbounds):
    """保留用户模板，仅将解析出的节点接入预设策略组。"""
    config = copy.deepcopy(template)
    configured_outbounds = config.get("outbounds")

    if not isinstance(configured_outbounds, list):
        raise ValueError("配置模板中的 outbounds 必须是数组")

    reserved_tags = {
        item.get("tag")
        for item in configured_outbounds
        if isinstance(item, dict) and item.get("tag")
    }
    make_unique_tags(outbounds, reserved_tags)
    node_tags = [outbound["tag"] for outbound in outbounds]
    groups = {
        item.get("tag"): item
        for item in configured_outbounds
        if isinstance(item, dict) and item.get("tag")
    }
    regional_tags = {
        tag: []
        for tag in ("日本手动", "狮城手动", "香港手动", "台湾手动", "美国手动")
    }
    regional_auto_tags = {
        tag.replace("手动", "自动"): []
        for tag in regional_tags
    }

    for outbound in outbounds:
        region = region_for_node(outbound["tag"])
        if region:
            regional_tags[region].append(outbound["tag"])
            auto_group = region.replace("手动", "自动")
            regional_auto_tags[auto_group].append(outbound["tag"])

    additions = {
        "手动选择": node_tags,
        "自动选择": node_tags,
        **regional_tags,
        **regional_auto_tags,
    }

    for group_tag, tags in additions.items():
        group = groups.get(group_tag)
        if group and group.get("type") in ("selector", "urltest"):
            existing = group.get("outbounds", [])
            if not isinstance(existing, list):
                raise ValueError(f"策略组 {group_tag} 的 outbounds 必须是数组")
            group["outbounds"] = list(dict.fromkeys([*existing, *tags]))

    available_auto_groups = [
        tag for tag, tags in regional_auto_tags.items() if tags
    ]
    regional_group_tags = set(regional_tags) | set(regional_auto_tags)
    for group in groups.values():
        if group.get("type") != "selector":
            continue
        existing = group.get("outbounds", [])
        if not isinstance(existing, list):
            raise ValueError(f"策略组 {group.get('tag')} 的 outbounds 必须是数组")
        if any(tag in existing for tag in regional_tags):
            ordered_auto_groups = [
                tag for tag in existing if tag in available_auto_groups
            ]
            remaining_auto_groups = [
                tag for tag in available_auto_groups
                if tag not in ordered_auto_groups
            ]
            manual_groups = [tag for tag in regional_tags if tag in existing]
            other_groups = [
                tag for tag in existing if tag not in regional_group_tags
            ]
            group["outbounds"] = list(
                dict.fromkeys([
                    *ordered_auto_groups,
                    *remaining_auto_groups,
                    *manual_groups,
                    *other_groups,
                ])
            )

    config["outbounds"].extend(outbounds)
    return config


def build_config(outbounds, template=None):
    """
    生成完整 sing-box 配置。
    """
    if not outbounds:
        raise ValueError("没有可用节点")

    if template is not None:
        return merge_nodes_into_template(template, outbounds)

    make_unique_tags(outbounds)

    node_tags = [
        outbound["tag"]
        for outbound in outbounds
    ]

    return {
        "$schema": "https://sing-box.sagernet.org/schema.json",

        "log": {
            "level": "info",
            "timestamp": True,
        },

        "dns": {
            "servers": [
                {
                    "tag": "local",
                    "type": "local",
                },
                {
                    "tag": "remote",
                    "type": "https",
                    "server": "1.1.1.1",
                    "server_port": 443,
                    "path": "/dns-query",
                },
            ],
            "final": "remote",
            "strategy": "prefer_ipv4",
        },

        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 2080,
            },
        ],

        "outbounds": [
            {
                "type": "selector",
                "tag": "proxy",
                "outbounds": [
                    "auto",
                    *node_tags,
                ],
                "default": "auto",
            },

            {
                "type": "urltest",
                "tag": "auto",
                "outbounds": node_tags,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "10m",
                "tolerance": 50,
            },

            *outbounds,

            {
                "type": "direct",
                "tag": "direct",
            },

            {
                "type": "block",
                "tag": "block",
            },
        ],

        "route": {
            "auto_detect_interface": True,
            "final": "proxy",
        },
    }


def convert_content(content, template=None):
    """将一段订阅内容转换为 sing-box 配置。"""
    outbounds = filter_subscription_info_nodes(
        parse_subscription_content(content)
    )
    return build_config(outbounds, template), len(outbounds)


def read_input(source):
    """
    读取远程订阅或本地文件。
    """
    if source.startswith("http://") or source.startswith("https://"):
        return get_subscription(source)

    with open(source, "r", encoding="utf-8") as file:
        return file.read()


def main():
    parser = argparse.ArgumentParser(
        description="将 Clash YAML 或常见代理订阅转换为 sing-box 配置"
    )

    parser.add_argument(
        "subscription",
        nargs="+",
        help="一个或多个订阅链接或本地订阅文件"
    )

    parser.add_argument(
        "-o",
        "--output",
        help="指定输出文件；默认保存在第一个本地输入文件所在目录"
    )

    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="必填：指定平台的 sing-box 配置模板 JSON"
    )

    args = parser.parse_args()

    try:
        outbounds = []
        for source in args.subscription:
            content = read_input(source)
            source_outbounds = parse_subscription_content(content)
            if not source_outbounds:
                print(f"[跳过] {source}: 没有解析到节点", file=sys.stderr)
            outbounds.extend(source_outbounds)

        outbounds = filter_subscription_info_nodes(outbounds)

        if not outbounds:
            print(
                "没有解析到节点。",
                file=sys.stderr
            )
            print(
                "支持 Clash YAML、Base64 订阅、VMess、VLESS、Trojan、"
                "Shadowsocks、Hysteria2 和部分 TUIC。",
                file=sys.stderr
            )
            sys.exit(1)

        config_path = args.config
        output_path = args.output
        if output_path is None:
            output_directory = os.getcwd()
            for source in args.subscription:
                if not source.startswith(("http://", "https://")):
                    output_directory = os.path.dirname(os.path.abspath(source))
                    break

            template_name = os.path.basename(config_path).lower()
            if template_name == "config_phone.json":
                output_name = "sing-box-phone.json"
            elif template_name == "config_openwrt.json":
                output_name = "sing-box-openwrt.json"
            else:
                output_name = "sing-box.json"
            output_path = os.path.join(output_directory, output_name)

        template = None

        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as file:
                template = json.load(file)
            if not isinstance(template, dict):
                raise ValueError("配置模板 JSON 根节点必须是对象")
        else:
            raise FileNotFoundError(config_path)

        config = build_config(outbounds, template)

        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(
                config,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(f"转换完成：{len(outbounds)} 个节点")
        print(f"输出文件：{output_path}")
        if template is not None:
            mixed_inbound = next(
                (
                    inbound for inbound in config.get("inbounds", [])
                    if inbound.get("type") == "mixed"
                ),
                None,
            )
            if mixed_inbound:
                print(
                    "Mixed 代理监听："
                    f"{mixed_inbound.get('listen', '127.0.0.1')}:{mixed_inbound.get('listen_port', 2080)}"
                )
        else:
            print("本地 HTTP/SOCKS5 代理：127.0.0.1:2080")

    except FileNotFoundError as exc:
        print(
            f"找不到文件：{exc.filename or exc}",
            file=sys.stderr
        )
        sys.exit(1)

    except Exception as exc:
        print(
            f"转换失败：{exc}",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
