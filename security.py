import json
import socket
import ipaddress
from urllib.parse import urlparse

MAX_DESCRIPTION_LEN = 2000

def load_artwork_settings(settings_data):
    """Load artwork settings safely (NO pickle). Accepts JSON or plain text."""
    if not settings_data:
        return None

    if isinstance(settings_data, (dict, list)):
        return settings_data

    try:
        obj = json.loads(settings_data)
        if isinstance(obj, (dict, list, str, int, float, bool)) or obj is None:
            return obj
    except Exception:
        pass

    return {"description": str(settings_data)[:MAX_DESCRIPTION_LEN]}


def save_artwork_description(description):
    """Store description as plain text (bounded length)."""
    if not description:
        return None
    return str(description)[:MAX_DESCRIPTION_LEN]


class ArtworkConfig:
    """Simple config container (kept for compatibility, not pickle-serializable by design)."""

    def __init__(self, colors=None, animation=False, public=True):
        self.colors = colors or ["#FF0000", "#00FF00", "#0000FF"]
        self.animation = bool(animation)
        self.public = bool(public)

    def __repr__(self):
        return f"ArtworkConfig(colors={self.colors}, animation={self.animation}, public={self.public})"

    def __str__(self):
        return self.__repr__()


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


def is_safe_url(url: str):
    """Basic SSRF guard: allow only http(s) and public IPs (A/AAAA)."""
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False, "403"

        hostname = parsed.hostname
        if not hostname:
            return False, "403"

        hn = hostname.lower()
        if hn in ("localhost", "localhost.localdomain"):
            return False, "403"

        try:
            ip = ipaddress.ip_address(hostname)
            if not _is_public_ip(ip):
                return False, "403"
            return True, str(ip)
        except ValueError:
            pass

        addrs = set()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family == socket.AF_INET:
                addrs.add(sockaddr[0])
            elif family == socket.AF_INET6:
                addrs.add(sockaddr[0])

        if not addrs:
            return False, "403"

        for ip_str in addrs:
            ip = ipaddress.ip_address(ip_str)
            if not _is_public_ip(ip):
                return False, "403"

        return True, sorted(addrs)[0]

    except Exception:
        return False, "403"
