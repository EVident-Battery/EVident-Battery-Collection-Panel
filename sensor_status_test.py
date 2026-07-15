#!/usr/bin/env python3
"""
EVBS sensor /status connection test (standalone).

This calls a sensor's /status endpoint the EXACT same way the EVBS Hub does
-- same library (requests), same URL (http://<ip>/status), same timeouts
(5s connect / 10s read), same raise_for_status() -- with nothing else around
it. If this fails the same way the Hub does, the problem is the network path
to the sensor, not the Hub application. If this succeeds but the Hub fails,
the block is specific to the Hub executable.

Usage:
    python sensor_status_test.py 10.3.6.8
    (or just run it and type the IP when prompted)
"""
import sys
import time

import requests
from requests.utils import getproxies, should_bypass_proxies


def main():
    # Get the sensor IP from the command line, or ask for it.
    if len(sys.argv) > 1:
        ip = sys.argv[1].strip()
    else:
        ip = input("Enter the sensor IP address (e.g. 10.3.6.8): ").strip()

    url = f"http://{ip}/status"

    print()
    print("=" * 62)
    print("  EVBS Sensor /status Connection Test")
    print("=" * 62)
    print(f"  Target URL : {url}")
    print(f"  Timeout    : 5s connect / 10s read   (identical to the Hub)")
    print(f"  requests   : v{requests.__version__}")

    # Show whether a system/corporate proxy would intercept this request.
    proxies = getproxies()
    if proxies:
        bypass = should_bypass_proxies(url, no_proxy=None)
        print(f"  Proxy      : {proxies}")
        print(f"  Via proxy? : {'NO - going direct' if bypass else 'YES - routed through proxy'}")
    else:
        print("  Proxy      : none detected (direct connection)")
    print("-" * 62)

    # ---------- This is the exact call the EVBS Hub makes ----------
    start = time.time()
    try:
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()
        data = r.json()
        # --------------------------------------------------------------
        elapsed = time.time() - start

        print(f"  RESULT     : SUCCESS   (HTTP {r.status_code}, {elapsed:.2f}s)")
        print("-" * 62)
        print("  Device responded with:")
        for k, v in data.items():
            print(f"    {k}: {v}")

    except requests.exceptions.RequestException as e:
        elapsed = time.time() - start
        print(f"  RESULT     : FAILED    ({elapsed:.2f}s)")
        print(f"  Error type : {type(e).__name__}")
        print(f"  Details    : {e}")
        print("-" * 62)

        # Plain-language interpretation of the failure.
        if isinstance(e, requests.exceptions.ProxyError):
            print("  Meaning    : Request went to a proxy server and the proxy")
            print("               refused or could not reach the sensor.")
        elif isinstance(e, requests.exceptions.ConnectTimeout):
            print("  Meaning    : No reply to the connection attempt within 5s.")
            print("               Packets are being silently dropped -- typical of")
            print("               a firewall / endpoint-security / egress block,")
            print("               NOT a refusal.")
        elif isinstance(e, requests.exceptions.ReadTimeout):
            print("  Meaning    : Connected OK, but the sensor did not reply in time.")
        elif isinstance(e, requests.exceptions.ConnectionError):
            print("  Meaning    : Connection actively refused/reset, or host")
            print("               unreachable.")
        elif isinstance(e, requests.exceptions.HTTPError):
            print("  Meaning    : Connected and got a reply, but an HTTP error code.")

    print("=" * 62)
    print()
    input("Press Enter to close...")


if __name__ == "__main__":
    main()
