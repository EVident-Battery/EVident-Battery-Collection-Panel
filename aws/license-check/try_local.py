"""Be Device Hub Pro for a minute: run the real Lambda handler on this computer,
against a Supabase you name, with this computer's real device id and name.

    python try_local.py activate   --key XXXX-XXXX-...
    python try_local.py check      --key XXXX-XXXX-...
    python try_local.py deactivate --key XXXX-XXXX-...
    python try_local.py activate   --key ... --as-device LAB-PC      # pretend to be another computer

What this proves end to end: the handler in lambda_function.py, the SQL in the
portal's claim_license_device(), and the portal pages that list and deactivate
the row. What it does not cover is the API Gateway hop, which is unchanged and
already serving the previous version of this function.

Supabase credentials come from an env file, by default the portal's .env.lan
(the LAN copy of the database, safe to write to). Point --env somewhere else
deliberately or not at all: this script refuses the production project.

The device id below is the reference for the app: a salted SHA-256 of the OS
machine identifier, so the raw identifier never leaves the computer and the
same computer always produces the same id.
"""
import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_ENV = Path.home() / "OneDrive/Desktop/data-web-portal/.env.lan"
PRODUCTION_REF = "ocgxoxzmbyjzbykdblas"   # Customer-Portal. Never from here.
DEVICE_SALT = "evb-device-hub-pro-v1"


def machine_identifier() -> str:
    system = platform.system()
    if system == "Windows":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            return winreg.QueryValueEx(k, "MachineGuid")[0]
    if system == "Darwin":
        out = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True)
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
        raise RuntimeError("IOPlatformUUID not found")
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        if os.path.exists(p):
            return Path(p).read_text().strip()
    raise RuntimeError("no machine identifier on this platform")


def device_id_for(identifier: str) -> str:
    return hashlib.sha256(f"{DEVICE_SALT}:{identifier}".encode()).hexdigest()


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["activate", "check", "deactivate"])
    ap.add_argument("--key", required=True, help="license key from the portal's Profile Settings")
    ap.add_argument("--env", type=Path, default=DEFAULT_ENV, help=f"env file with the Supabase URL and service key (default {DEFAULT_ENV})")
    ap.add_argument("--as-device", metavar="NAME", help="pretend to be a different computer with this name")
    args = ap.parse_args()

    env = load_env(args.env)
    url = env.get("NEXT_PUBLIC_SUPABASE_URL", "")
    if PRODUCTION_REF in url:
        print("Refusing: that env file points at the production project.", file=sys.stderr)
        return 2
    os.environ["SUPABASE_URL_CUSTOMER"] = url
    os.environ["SUPABASE_SERVICE_KEY_CUSTOMER"] = env["SUPABASE_SERVICE_ROLE_KEY"]
    secret_file = Path(__file__).with_name("activation_hmac_secret.txt")
    if secret_file.exists():
        os.environ["ACTIVATION_HMAC_SECRET"] = secret_file.read_text().strip()

    if args.as_device:
        name, ident = args.as_device, f"pretend:{args.as_device}"
    else:
        name, ident = socket.gethostname(), machine_identifier()
    device_id = device_id_for(ident)

    import lambda_function as lf   # after the env is set

    event = {
        "headers": {"auth-token": args.key},
        "body": json.dumps({
            "action": args.action,
            "device_id": device_id,
            "device_name": name,
            "platform": f"{platform.system()} {platform.release()}",
            "app_version": "try_local",
        }),
    }
    print(f"database : {url}")
    print(f"computer : {name}   device_id {device_id[:12]}...")
    print(f"action   : {args.action}\n")
    res = lf.lambda_handler(event, None)
    body = json.loads(res["body"])
    if "activation_token" in body:
        body["activation_token"] = body["activation_token"][:24] + "..."
    print(f"\nHTTP {res['statusCode']}")
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
