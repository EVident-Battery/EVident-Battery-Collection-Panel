"""
Test tool: force the Device Hub to drop a sensor's mDNS record NOW.

mDNS has no authentication, so any host on the LAN can multicast a TTL=0
"goodbye" for a service name. Every listening cache (the Hub included)
drops the record immediately and fires its device_lost path - the same
thing a clean sensor shutdown would cause, without waiting up to ~75 min
for TTL expiry after a silent power-off.

Usage:
    python tools/simulate_mdns_goodbye.py EVBS_QF85Q 192.168.0.53

Note: registering briefly re-announces the service (the Hub may refresh
the record for ~1s) before the goodbye goes out. If the real sensor is
still powered on, it will re-announce itself eventually and the Hub will
re-add it - which is exactly what the probation/auto-resume paths expect.
"""
import argparse
import socket
import time

from zeroconf import Zeroconf, ServiceInfo

SERVICE_TYPE = "_evbs._tcp.local."


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a spoofed mDNS goodbye for a sensor")
    parser.add_argument("hostname", help="Sensor hostname, e.g. EVBS_QF85Q")
    parser.add_argument("ip", help="Sensor IP address, e.g. 192.168.0.53")
    parser.add_argument("--port", type=int, default=80)
    args = parser.parse_args()

    info = ServiceInfo(
        SERVICE_TYPE,
        f"{args.hostname}.{SERVICE_TYPE}",
        addresses=[socket.inet_aton(args.ip)],
        port=args.port,
    )

    zc = Zeroconf()
    try:
        print(f"announcing {args.hostname} briefly...")
        zc.register_service(info)
        time.sleep(1)
        print("sending goodbye (TTL=0)...")
        zc.unregister_service(info)
        print(f"done - the Hub should log mDNS loss for {args.hostname} now")
    finally:
        zc.close()


if __name__ == "__main__":
    main()
