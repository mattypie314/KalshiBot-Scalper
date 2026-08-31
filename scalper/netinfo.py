"""Guess LAN IPv4s so a phone on the same network can open the dashboard."""

from __future__ import annotations

import socket
from urllib.parse import urlparse


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


def _octets(ip: str) -> list[int] | None:
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 or n > 255 for n in nums):
        return None
    return nums


def is_tailscale_ip(ip: str) -> bool:
    nums = _octets(ip)
    if not nums:
        return False
    return nums[0] == 100 and 64 <= nums[1] <= 127


def is_home_wifi_ip(ip: str) -> bool:
    """Addresses a phone on the same Wi-Fi / Tailscale can usually open."""
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True
    return is_tailscale_ip(ip)


def host_from_url(url: str) -> str:
    return urlparse(url).hostname or ""


def bonjour_host() -> str | None:
    name = (socket.gethostname() or "").split(".")[0].strip()
    if not name or name.lower() == "localhost":
        return None
    return f"{name}.local"


def dashboard_urls(port: int, host: str = "0.0.0.0") -> list[str]:
    """Loopback first, then LAN / Tailscale IPs when the server is bound wide."""
    urls = [f"http://127.0.0.1:{int(port)}"]
    if host in {"127.0.0.1", "localhost", "::1"}:
        return urls
    for ip in lan_ipv4s():
        url = f"http://{ip}:{int(port)}"
        if url not in urls:
            urls.append(url)
    mdns = bonjour_host()
    if mdns and host not in {"127.0.0.1", "localhost", "::1"}:
        url = f"http://{mdns}:{int(port)}"
        if url not in urls:
            urls.append(url)
    return urls


def startup_lines(port: int, host: str = "0.0.0.0") -> list[str]:
    """Human lines for run.py. Never tell someone to open a cloud IP on a phone."""
    port = int(port)
    urls = dashboard_urls(port, host)
    lines = [f"Scalper 3000 dashboard  {urls[0]}"]
    home = [u for u in urls[1:] if is_home_wifi_ip(host_from_url(u))]
    mdns = [u for u in urls[1:] if host_from_url(u).endswith(".local") and u not in home]
    # .local alone (cloud/container hostname) is not a phone URL.
    phone = home + (mdns if home else [])
    other = [u for u in urls[1:] if u not in phone]
    if phone:
        lines.append(f"Phone (same Wi-Fi)      {phone[0]}")
        for extra in phone[1:]:
            lines.append(f"  also                  {extra}")
        lines.append("On the iPhone use that exact http:// URL in Safari. Not https. Not 127.0.0.1.")
        lines.append("That page is the desk: pick SCALPER or KALSHI15. Do not run both LIVE on BTC.")
    else:
        lines.append("Phone cannot open this process. 127.0.0.1 and cloud/container IPs are this machine only.")
        lines.append("On the Pi/PC that is on your Wi-Fi: hostname -I   then Safari → http://THAT_IP:8787")
        for extra in other:
            lines.append(f"  (not a phone URL)      {extra}")
    return lines
