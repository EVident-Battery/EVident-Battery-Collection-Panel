"""Local test of lambda_function.py with a fake Supabase client. No network.
Run:  python test_local.py
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

# Fake the `supabase` package before importing the handler.
class _Query:
    def __init__(self, db, table):
        self._rows = list(db.get(table, []))
    def select(self, *_): return self
    def limit(self, *_): return self
    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self
    def execute(self):
        return types.SimpleNamespace(data=self._rows)

class _Client:
    def __init__(self, db): self._db = db
    def table(self, name): return _Query(self._db, name)

class _Boom:
    def table(self, name): raise ConnectionError("supabase down")

fake = types.ModuleType("supabase")
fake.Client = _Client
fake.create_client = lambda url, key: _Client(fake.DB) if not fake.BOOM else _Boom()
fake.DB, fake.BOOM = {}, False
sys.modules["supabase"] = fake

os.environ["SUPABASE_URL_CUSTOMER"] = "x"
os.environ["SUPABASE_SERVICE_KEY_CUSTOMER"] = "y"
os.environ["ACTIVATION_HMAC_SECRET"] = "testsecret"
import lambda_function as lf

future = (datetime.now(timezone.utc) + timedelta(days=200)).isoformat()
past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

def db(status="active", end=future, price="price_year", interval="year", active_key=True, has_sub=True):
    return {
        "user_license_keys": [{"id": "lic-1", "user_id": "u1", "license_key": "GOOD-KEY", "is_active": active_key}],
        "subscription_profiles": ([{"user_id": "u1", "environment": "production", "subscription_status": status,
                                    "subscription_end_at": end, "stripe_price_id": price}] if has_sub else []),
        "platform_plans": [{"stripe_price_id": "price_year", "environment": "production", "billing_interval": "year", "name": "Annual Plan"},
                           {"stripe_price_id": "price_month", "environment": "production", "billing_interval": "month", "name": "Monthly Plan"}],
    }

def call(key="GOOD-KEY", data=None, boom=False):
    lf._client = None
    fake.DB, fake.BOOM = (data or db()), boom
    ev = {"headers": ({"Auth-Token": key} if key is not None else {}), "body": None}
    r = lf.lambda_handler(ev, None)
    return r["statusCode"], json.loads(r["body"])

cases = [
    ("annual active -> yes",      call(),                                   200, {"allowed": True, "plan": "Annual Plan"}),
    ("missing header -> 400",     call(key=None),                           400, {"error": "missing_auth_token"}),
    ("unknown key -> invalid",    call(key="NOPE"),                         200, {"allowed": False, "reason": "invalid_key"}),
    ("inactive key -> invalid",   call(data=db(active_key=False)),          200, {"allowed": False, "reason": "invalid_key"}),
    ("no sub row -> no_sub",      call(data=db(has_sub=False)),             200, {"allowed": False, "reason": "no_subscription"}),
    ("expired date -> expired",   call(data=db(end=past)),                  200, {"allowed": False, "reason": "expired"}),
    ("canceled status -> expired",call(data=db(status="canceled")),         200, {"allowed": False, "reason": "expired"}),
    ("trialing -> expired",       call(data=db(status="trialing")),         200, {"allowed": False, "reason": "expired"}),
    ("monthly -> not_annual",     call(data=db(price="price_month")),       200, {"allowed": False, "reason": "not_annual"}),
    ("unknown price -> not_annual", call(data=db(price="price_zzz")),       200, {"allowed": False, "reason": "not_annual"}),
    ("backend down -> 503",       call(boom=True),                          503, {"error": "service_unavailable"}),
]

fails = 0
for name, (status, body), want_status, want_sub in cases:
    ok = status == want_status and all(body.get(k) == v for k, v in want_sub.items())
    print(("PASS" if ok else "FAIL"), name, "->", status, body)
    fails += (not ok)

# token check
status, body = call()
tok = body["activation_token"]
lic, mac = tok.split(".")
import hashlib, hmac
expect = hmac.new(b"testsecret", f"{lic}:device-hub-pro".encode(), hashlib.sha256).hexdigest()
ok = lic == "lic-1" and mac == expect
print(("PASS" if ok else "FAIL"), "activation_token verifies with HMAC secret")
fails += (not ok)

print("\nRESULT:", "ALL PASS" if fails == 0 else f"{fails} FAILED")
sys.exit(1 if fails else 0)
