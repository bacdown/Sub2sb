"""安全下载公网订阅内容。"""

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

from subscription_utils import (
    SubscriptionFetchError,
    SubscriptionTooLargeError,
    validate_public_url_syntax,
)

MAX_SUBSCRIPTION_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 5


def validate_public_url(url):
    """Allow public HTTP(S) subscription URLs and reject private destinations."""
    parsed = validate_public_url_syntax(url)
    port = parsed.port

    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                parsed.hostname,
                port if port is not None else (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise ValueError("无法解析订阅链接的服务器地址") from exc

    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError("订阅链接不能指向内网或非公网地址")

    return parsed


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS
    max_repeats = MAX_REDIRECTS

    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_public_url(new_url)
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def fetch_remote_subscription(url):
    """Fetch a bounded subscription response without private redirects."""
    validate_public_url(url)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        PublicRedirectHandler(),
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Sub2sb/1.0"})

    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_SUBSCRIPTION_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SubscriptionFetchError(f"下载订阅失败：HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SubscriptionFetchError("下载订阅失败：远程服务器无法访问") from exc

    if len(data) > MAX_SUBSCRIPTION_BYTES:
        raise SubscriptionTooLargeError("订阅内容不能超过 2 MiB")

    return data.decode("utf-8", errors="replace")
