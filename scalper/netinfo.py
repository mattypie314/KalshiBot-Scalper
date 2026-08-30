"""Guess LAN IPv4s so a phone on the same network can open the dashboard."""

from __future__ import annotations

import socket


def _is_usable(ip: str) -> bool:
    if not ip or ip.startswith("127.") or ip.startswith("0."):
        return False
    if ip.startswith("169.254."):
        return False
    return True


def guess_lan_ip() -> str | None:
    """Outbound UDP trick: the kernel picks the interface used for the internet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None
    return ip if _is_usable(ip) else None


def lan_ipv4s() -> list[str]:
    found: list[str] = []
    guessed = guess_lan_ip()
    if guessed:
        found.append(guessed)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _is_usable(ip) and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def dashboard_urls(port: int, host: str = "0.0.0.0") -> list[str]:
    """Loopback first, then LAN / Tailscale IPs when the server is bound wide."""
    urls = [f"http://127.0.0.1:{int(port)}"]
    if host in {"127.0.0.1", "localhost", "::1"}:
        return urls
    for ip in lan_ipv4s():
        url = f"http://{ip}:{int(port)}"
        if url not in urls:
            urls.append(url)
    return urls
