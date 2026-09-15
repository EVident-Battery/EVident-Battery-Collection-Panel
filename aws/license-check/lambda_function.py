"""
license-check: POST /prod/activate

Takes the existing portal license key in the `auth-token` header and answers
yes/no for Device Hub Pro advanced features.

Yes only when ALL of:
  1. key exists in user_license_keys with is_active = true
  2. that user's subscription_profiles row (environment = SUBSCRIPTION_ENV) has
     subscription_status = 'active' and subscription_end_at in the future
  3. its stripe_price_id maps to a platform_plans row with billing_interval = 'year'

Always 200 for a yes or a no (client reads `allowed`). Non-200 means "could not
decide": 400 missing header, 503 backend unavailable.

Never logs the license key or any request header.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from supabase import create_client, Client

PRODUCT = "device-hub-pro"
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


def _no(reason: str) -> dict:
    print(f"activate: allowed=false reason={reason}")
    return _resp(200, {"allowed": False, "reason": reason})


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _activation_token(license_id: str) -> str | None:
    secret = os.environ.get("ACTIVATION_HMAC_SECRET")
    if not secret:
        return None
    mac = hmac.new(secret.encode(), f"{license_id}:{PRODUCT}".encode(), hashlib.sha256).hexdigest()
    return f"{license_id}.{mac}"


def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    key = (headers.get("auth-token") or "").strip()
    if not key:
        return _resp(400, {"error": "missing_auth_token", "message": "auth-token header is required"})

    env_name = os.environ.get("SUBSCRIPTION_ENV", "production")

    try:
        sb = _sb()

        # 1) license key -> user
        r = (
            sb.table("user_license_keys")
            .select("id,user_id")
            .eq("license_key", key)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not r.data:
            return _no("invalid_key")
        license_id = r.data[0]["id"]
        user_id = r.data[0]["user_id"]

        # 2) subscription row
        r = (
            sb.table("subscription_profiles")
            .select("subscription_status,subscription_end_at,stripe_price_id")
            .eq("user_id", user_id)
            .eq("environment", env_name)
            .limit(1)
            .execute()
        )
        if not r.data:
            return _no("no_subscription")
        sub = r.data[0]

        status = sub.get("subscription_status")
        end_at = sub.get("subscription_end_at")
        price_id = sub.get("stripe_price_id")
        if status != "active" or not end_at or _parse_ts(end_at) <= datetime.now(timezone.utc):
            return _no("expired")
        if not price_id:
            return _no("not_annual")

        # 3) plan interval
        r = (
            sb.table("platform_plans")
            .select("name,billing_interval")
            .eq("stripe_price_id", price_id)
            .eq("environment", env_name)
            .limit(1)
            .execute()
        )
        if not r.data or r.data[0].get("billing_interval") != "year":
            return _no("not_annual")
        plan_name = r.data[0].get("name")

    except KeyError as e:
        print(f"activate: misconfigured, missing env {e}")
        return _resp(503, {"error": "service_unavailable", "message": "license service not configured"})
    except Exception as e:
        print(f"activate: backend error {type(e).__name__}: {e}")
        return _resp(503, {"error": "service_unavailable", "message": "license service temporarily unavailable"})

    print(f"activate: allowed=true license_id={license_id}")
    body = {
        "allowed": True,
        "product": PRODUCT,
        "plan": plan_name,
        "subscription_end_at": end_at,
        "license_id": license_id,
    }
    token = _activation_token(license_id)
    if token:
        body["activation_token"] = token
    return _resp(200, body)
