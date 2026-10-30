"""CI check (Windows, administrator): the raw-socket capture sees a real TCP download, in order."""
import socket
import sys
import threading
import time

sys.path.insert(0, ".")
import requests  # noqa: E402

from shugotracker.capture import _Listener, ensure_firewall_rule, parse_ipv4_tcp  # noqa: E402
from shugotracker.nearby import is_admin  # noqa: E402

print("admin:", is_admin())
if "--firewall" in sys.argv:
    print("firewall rule:", ensure_firewall_rule(print), "| again (no change):", ensure_firewall_rule(print))
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("8.8.8.8", 80))
ip = s.getsockname()[0]
s.close()
got = {"packets": 0, "bytes": 0, "all": 0, "out": 0, "in": 0}
lock = threading.Lock()


def on_packet(pkt):
    p = parse_ipv4_tcp(pkt)
    with lock:
        got["all"] += 1
        if p:
            got["out" if p[0] == ip else "in"] += 1
    if p and p[1] == 443 and p[2] == ip and p[5]:
        with lock:
            got["packets"] += 1
            got["bytes"] += len(p[5])


ln = _Listener(ip, on_packet)
time.sleep(0.5)
r = requests.get("https://github.com/CynicaGaming/Shugo-Tracker", timeout=20)
time.sleep(1.0)
ln.stop()
print(f"any packets: {got['all']}, tcp out: {got['out']}, tcp in: {got['in']}")
print(f"listening on {ip}: {got['packets']} packets, {got['bytes']} bytes from port 443 (page {len(r.content)} bytes)")
sys.exit(0 if got["bytes"] > 5000 else 1)
