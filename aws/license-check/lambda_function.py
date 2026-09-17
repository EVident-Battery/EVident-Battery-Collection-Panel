"""
license-check: POST /prod/activate

Takes the existing portal license key in the `auth-token` header and a JSON
body naming the computer, and answers yes/no for Device Hub Pro advanced
features. One route, three actions, chosen by `action` in the body:

  activate    (default) the user typed a key. Applies the subscription rule,
              then claims one of the account's device slots.
  check       the app's startup / once-a-day check-in. Never claims a slot and
              never looks at the subscription: activation is permanent, so the
              only questions are "is the key still live" and "does this
              computer still hold its slot".
  deactivate  the user signed this computer out from inside the app.

Activation rule, all of:
  1. key exists in user_license_keys with is_active = true
  2. that user's subscription_profiles row (environment = SUBSCRIPTION_ENV) has
     subscription_status = 'active' and subscription_end_at in the future
  3. its stripe_price_id maps to a platform_plans row with billing_interval = 'year'
  4. the account has a free device slot, or this computer already holds one
     (claim_license_device() in the portal's migration
     20260917120000_license_device_activations.sql; default cap 3,
     user_profiles.device_activation_limit)

Always 200 for a yes or a no (client reads `allowed`). Non-200 means "could not
decide", and the app keeps whatever it last knew: 400 malformed request,
503 backend unavailable.

Never logs the license key, any request header, or the device id.
"""
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone

from supabase import create_client, Client

PRODUCT = "device-hub-pro"
ACTIONS = ("activate", "check", "deactivate")
DEVICE_ID = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")
_client: Client | None = None


def _sb() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL_CUSTOMER"],
            os.environ["SUPABASE_SERVICE_KEY_CUSTOMER"],
        )
    return _client


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def _bad(code: str, message: str) -> dict:
    print(f"license: bad_request {code}")
    return _resp(400, {"error": code, "message": message})


def _no(action: str, reason: str, email: str | None = None, extra: dict | None = None) -> dict:
    print(f"license: action={action} allowed=false reason={reason}")
    body = {"allowed": False, "reason": reason}
    if email:
        body["email"] = email
    if extra:
        body.update(extra)
    return _resp(200, body)


def _user_email(sb: Client, user_id: str) -> str | None:
    """Best-effort: look up the account email via the auth admin API."""
    try:
        res = sb.auth.admin.get_user_by_id(user_id)
        user = getattr(res, "user", None) or res
        return getattr(user, "email", None)
    except Exception as e:
        print(f"license: email lookup failed {type(e).__name__}")
        return None


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _activation_token(license_id: str, device_id: str) -> str | None:
    """`<license_id>.<hmac>` over license, device and product.

    The device id is inside the MAC, so a token copied to another computer
    fails verification there: that computer hashes to a different device id.
    """
    secret = os.environ.get("ACTIVATION_HMAC_SECRET")
    if not secret:
        return None
    msg = f"{license_id}:{device_id}:{PRODUCT}".encode()
    mac = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"{license_id}.{mac}"


def _live_devices(sb: Client, user_id: str) -> list[dict]:
    r = (
        sb.table("license_device_activations")
        .select("device_name,platform,activated_at,last_seen_at")
        .eq("user_id", user_id)
        .eq("product", PRODUCT)
        .is_("deactivated_at", "null")
        .order("activated_at")
        .execute()
    )
    return r.data or []


def _subscription_verdict(sb: Client, user_id: str, env_name: str):
    """Returns (reason_or_None, plan_name, end_at)."""
    r = (
        sb.table("subscription_profiles")
        .select("subscription_status,subscription_end_at,stripe_price_id")
        .eq("user_id", user_id)
        .eq("environment", env_name)
        .limit(1)
        .execute()
    )
    if not r.data:
        return "no_subscription", None, None
    sub = r.data[0]
    status = sub.get("subscription_status")
    end_at = sub.get("subscription_end_at")
    price_id = sub.get("stripe_price_id")
    if status != "active" or not end_at or _parse_ts(end_at) <= datetime.now(timezone.utc):
        return "expired", None, end_at
    if not price_id:
        return "not_annual", None, end_at
    r = (
        sb.table("platform_plans")
        .select("name,billing_interval")
        .eq("stripe_price_id", price_id)
        .eq("environment", env_name)
        .limit(1)
        .execute()
    )
    if not r.data or r.data[0].get("billing_interval") != "year":
        return "not_annual", None, end_at
    return None, r.data[0].get("name"), end_at


def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    key = (headers.get("auth-token") or "").strip()
    if not key:
        return _bad("missing_auth_token", "auth-token header is required")

    try:
        body = json.loads(event.get("body") or "{}")
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return _bad("invalid_json", "request body must be a JSON object")

    action = str(body.get("action") or "activate").lower()
    if action not in ACTIONS:
        return _bad("invalid_action", f"action must be one of {', '.join(ACTIONS)}")

    device_id = str(body.get("device_id") or "").strip()
    if not DEVICE_ID.match(device_id):
        return _bad("missing_device_id", "device_id is required (8 to 128 chars of A-Z a-z 0-9 _ - : .)")

    device_name = str(body.get("device_name") or "").strip()[:120]
    platform = str(body.get("platform") or "").strip()[:60]
    app_version = str(body.get("app_version") or "").strip()[:40]
    env_name = os.environ.get("SUBSCRIPTION_ENV", "production")

    try:
        sb = _sb()

        # key -> account (every action starts here)
        r = (
            sb.table("user_license_keys")
            .select("id,user_id")
            .eq("license_key", key)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not r.data:
            return _no(action, "invalid_key")
        license_id = r.data[0]["id"]
        user_id = r.data[0]["user_id"]

        # ---- deactivate: free this computer's slot ---------------------------
        if action == "deactivate":
            r = (
                sb.table("license_device_activations")
                .update({"deactivated_at": datetime.now(timezone.utc).isoformat(), "deactivated_by": "app"})
                .eq("user_id", user_id)
                .eq("product", PRODUCT)
                .eq("device_id", device_id)
                .is_("deactivated_at", "null")
                .execute()
            )
            done = bool(r.data)
            print(f"license: action=deactivate deactivated={done} license_id={license_id}")
            return _resp(200, {"deactivated": done})

        email = _user_email(sb, user_id)

        # ---- check: does this computer still hold its slot -------------------
        if action == "check":
            touch = {"last_seen_at": datetime.now(timezone.utc).isoformat()}
            if app_version:
                touch["app_version"] = app_version
            r = (
                sb.table("license_device_activations")
                .update(touch)
                .eq("user_id", user_id)
                .eq("product", PRODUCT)
                .eq("device_id", device_id)
                .is_("deactivated_at", "null")
                .execute()
            )
            if not r.data:
                return _no(action, "device_deactivated", email)
            print(f"license: action=check allowed=true license_id={license_id}")
            out = {"allowed": True, "email": email, "product": PRODUCT, "license_id": license_id}
            token = _activation_token(license_id, device_id)
            if token:
                out["activation_token"] = token
            return _resp(200, out)

        # ---- activate --------------------------------------------------------
        reason, plan_name, end_at = _subscription_verdict(sb, user_id, env_name)
        if reason:
            return _no(action, reason, email)

        claim = sb.rpc(
            "claim_license_device",
            {
                "p_user_id": user_id,
                "p_license_key_id": license_id,
                "p_device_id": device_id,
                "p_device_name": device_name,
                "p_platform": platform,
                "p_app_version": app_version,
                "p_product": PRODUCT,
            },
        ).execute().data or {}
        status = claim.get("status")
        if status == "limit":
            return _no(action, "device_limit", email, {
                "device_limit": claim.get("limit"),
                "devices": _live_devices(sb, user_id),
            })
        if status not in ("created", "existing"):
            raise RuntimeError(f"unexpected claim status {status!r}")

    except KeyError as e:
        print(f"license: misconfigured, missing env {e}")
        return _resp(503, {"error": "service_unavailable", "message": "license service not configured"})
    except Exception as e:
        print(f"license: backend error {type(e).__name__}: {e}")
        return _resp(503, {"error": "service_unavailable", "message": "license service temporarily unavailable"})

    print(f"license: action=activate allowed=true claim={status} license_id={license_id}")
    out = {
        "allowed": True,
        "email": email,
        "product": PRODUCT,
        "plan": plan_name,
        "subscription_end_at": end_at,
        "license_id": license_id,
        "devices_used": claim.get("active"),
        "device_limit": claim.get("limit"),
    }
    token = _activation_token(license_id, device_id)
    if token:
        out["activation_token"] = token
    return _resp(200, out)
