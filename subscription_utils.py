"""Shared validation and query handling for remote subscription URLs."""

import ipaddress
import re
from urllib.parse import urlsplit

MAX_SUBSCRIPTION_URLS = 10
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal")


class SubscriptionFetchError(Exception):
    status_code = 502


class SubscriptionTooLargeError(SubscriptionFetchError):
    status_code = 413


def collect_subscription_urls(params):
    """Collect URL query values while preserving commas inside a single URL."""
    urls = []
    for key in ("url", "urls"):
        values = params.get(key, [])
        if isinstance(values, str):
            values = [values]
        for raw in values:
            if not isinstance(raw, str):
                continue
            parts = re.split(r",(?=https?://)", raw, flags=re.IGNORECASE)
            urls.extend(part.strip() for part in parts if part.strip())

    urls = list(dict.fromkeys(urls))
    if len(urls) > MAX_SUBSCRIPTION_URLS:
        raise ValueError(f"一次最多支持 {MAX_SUBSCRIPTION_URLS} 个订阅链接")
    return urls


def validate_public_url_syntax(url):
    """Reject malformed URLs and obvious local/private destinations."""
    if not isinstance(url, str) or not url or any(ord(char) <= 32 for char in url):
        raise ValueError("订阅链接格式无效")

    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError as exc:
        raise ValueError("订阅链接格式无效") from exc

    if (
        parsed.scheme.lower() not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("订阅链接必须是有效的 HTTP 或 HTTPS 公网地址")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
        raise ValueError("订阅链接不能指向本机或内网地址")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("订阅链接不能指向内网或非公网地址")

    return parsed