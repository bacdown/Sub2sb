#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""协议转换单元测试。"""

import unittest

from sub2singbox import (
    clash_proxy_to_outbound,
    clash_tls_config,
    parse_hysteria2,
    parse_tuic,
    parse_uri,
    _normalize_utls_fingerprint,
)


class TlsFingerprintTests(unittest.TestCase):
    def test_valid_utls(self):
        self.assertEqual(_normalize_utls_fingerprint("chrome"), "chrome")
        self.assertEqual(_normalize_utls_fingerprint("Firefox"), "firefox")

    def test_cert_sha256_rejected(self):
        # Hysteria2 风格的证书指纹不应被当作 uTLS
        long_hex = "c77f0fb1aef429ebc3f7e15078ea13c3cc9fe85d8c7a9bda9637f919e340d355"
        self.assertIsNone(_normalize_utls_fingerprint(long_hex))

    def test_clash_tls_ignores_cert_fingerprint(self):
        proxy = {
            "tls": True,
            "sni": "example.com",
            "fingerprint": "c77f0fb1aef429ebc3f7e15078ea13c3cc9fe85d8c7a9bda9637f919e340d355",
            "client-fingerprint": "chrome",
        }
        tls = clash_tls_config(proxy)
        self.assertEqual(tls["utls"]["fingerprint"], "chrome")


class Hysteria2ConvertTests(unittest.TestCase):
    def test_basic_with_disable_chrome_parrot(self):
        proxy = {
            "name": "HK-HY2",
            "type": "hysteria2",
            "server": "aws-linkhy5.lxyun.xyz",
            "port": 443,
            "password": "be45e133-f0a8-4deb-88c2-45c0e32cc53a",
            "sni": "www.apple.com.cn",
            "skip-cert-verify": True,
            "fingerprint": "c77f0fb1aef429ebc3f7e15078ea13c3cc9fe85d8c7a9bda9637f919e340d355",
        }
        out = clash_proxy_to_outbound(proxy)
        self.assertEqual(out["type"], "hysteria2")
        self.assertTrue(out["disable_chrome_parrot"])
        self.assertEqual(out["tls"]["alpn"], ["h3"])
        self.assertTrue(out["tls"]["insecure"])
        self.assertNotIn("utls", out["tls"])

    def test_port_hopping(self):
        proxy = {
            "name": "SG",
            "type": "hysteria2",
            "server": "example.com",
            "port": 60000,
            "ports": "60000-65530",
            "password": "pwd",
            "sni": "example.com",
            "skip-cert-verify": True,
        }
        out = clash_proxy_to_outbound(proxy)
        self.assertNotIn("server_port", out)
        self.assertEqual(out["server_ports"], ["60000:65530"])

    def test_uri_parse(self):
        uri = (
            "hysteria2://be45e133-f0a8-4deb-88c2-45c0e32cc53a"
            "@aws-linkhy5.lxyun.xyz:443?sni=www.apple.com.cn&insecure=1#test"
        )
        out = parse_hysteria2(uri)
        self.assertTrue(out["disable_chrome_parrot"])
        self.assertEqual(out["tls"]["alpn"], ["h3"])
        self.assertTrue(out["tls"]["insecure"])


class TuicConvertTests(unittest.TestCase):
    def test_clash_tuic_alpn_and_insecure(self):
        proxy = {
            "name": "TUIC-1",
            "type": "tuic",
            "server": "example.com",
            "port": 443,
            "uuid": "00000000-0000-0000-0000-000000000001",
            "password": "pwd",
            "sni": "example.com",
            "skip-cert-verify": True,
            "udp-relay-mode": "native",
            "congestion-controller": "bbr",
        }
        out = clash_proxy_to_outbound(proxy)
        self.assertEqual(out["type"], "tuic")
        self.assertEqual(out["tls"]["alpn"], ["h3"])
        self.assertTrue(out["tls"]["insecure"])
        self.assertEqual(out["udp_relay_mode"], "native")
        self.assertEqual(out["congestion_control"], "bbr")

    def test_uri_tuic(self):
        uri = (
            "tuic://00000000-0000-0000-0000-000000000001:pwd"
            "@example.com:443?sni=example.com&insecure=1&udp_relay_mode=quic#t1"
        )
        out = parse_tuic(uri)
        self.assertEqual(out["tls"]["alpn"], ["h3"])
        self.assertTrue(out["tls"]["insecure"])


class ShadowsocksPluginTests(unittest.TestCase):
    def test_plain_ss(self):
        proxy = {
            "name": "SS",
            "type": "ss",
            "server": "1.2.3.4",
            "port": 8388,
            "cipher": "aes-256-gcm",
            "password": "secret",
        }
        out = clash_proxy_to_outbound(proxy)
        self.assertEqual(out["type"], "shadowsocks")
        self.assertEqual(out["method"], "aes-256-gcm")
        self.assertNotIn("plugin", out)

    def test_obfs_plugin(self):
        proxy = {
            "name": "SS-obfs",
            "type": "ss",
            "server": "1.2.3.4",
            "port": 443,
            "cipher": "chacha20-ietf-poly1305",
            "password": "secret",
            "plugin": "obfs",
            "plugin-opts": {"mode": "http", "host": "www.bing.com"},
        }
        out = clash_proxy_to_outbound(proxy)
        self.assertEqual(out["plugin"], "obfs-local")
        self.assertIn("obfs=http", out["plugin_opts"])
        self.assertIn("obfs-host=www.bing.com", out["plugin_opts"])


class ExtraProtocolTests(unittest.TestCase):
    def test_anytls(self):
        proxy = {
            "name": "AT",
            "type": "anytls",
            "server": "example.com",
            "port": 443,
            "password": "pwd",
            "sni": "example.com",
            "skip-cert-verify": True,
        }
        out = clash_proxy_to_outbound(proxy)
        self.assertEqual(out["type"], "anytls")
        self.assertTrue(out["tls"]["enabled"])
        self.assertTrue(out["tls"]["insecure"])

    def test_hysteria_v1(self):
        proxy = {
            "name": "HY1",
            "type": "hysteria",
            "server": "example.com",
            "port": 443,
            "auth_str": "pwd",
            "up": "100 Mbps",
            "down": "200",
            "sni": "example.com",
            "skip-cert-verify": True,
        }
        out = clash_proxy_to_outbound(proxy)
        self.assertEqual(out["type"], "hysteria")
        self.assertEqual(out["up_mbps"], 100)
        self.assertEqual(out["down_mbps"], 200)
        self.assertEqual(out["tls"]["alpn"], ["h3"])

    def test_http_socks(self):
        http_out = clash_proxy_to_outbound({
            "name": "HTTP",
            "type": "http",
            "server": "1.1.1.1",
            "port": 8080,
            "username": "u",
            "password": "p",
        })
        self.assertEqual(http_out["type"], "http")
        self.assertEqual(http_out["username"], "u")

        socks_out = clash_proxy_to_outbound({
            "name": "SOCKS",
            "type": "socks5",
            "server": "1.1.1.1",
            "port": 1080,
        })
        self.assertEqual(socks_out["type"], "socks")


class UriDispatchTests(unittest.TestCase):
    def test_hy2_alias(self):
        out = parse_uri("hy2://pwd@example.com:443?sni=example.com&insecure=1#n")
        self.assertIsNotNone(out)
        self.assertEqual(out["type"], "hysteria2")

    def test_unsupported_returns_none(self):
        self.assertIsNone(parse_uri("unknown://foo"))


if __name__ == "__main__":
    unittest.main()
