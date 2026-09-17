"""Local test of lambda_function.py with a fake Supabase client. No network.
Run:  python test_local.py

The fake implements just enough of supabase-py: table().select/eq/is_/order/
limit/update/execute, rpc('claim_license_device'), and auth.admin. The claim
RPC is re-implemented here in Python with the same three outcomes as the SQL
function, so these tests cover the handler's branching, not the SQL. The SQL's
own race guard is exercised by scripts/checks/license-device-activations.sql in
the portal repo.
"""
import hashlib
import hmac
import json
import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone


class _Query:
    def __init__(self, db, table):
        self._db, self._table = db, table
        self._rows = list(db.setdefault(table, []))
        self._update = None
    def select(self, *_): return self
    def limit(self, *_): return self
    def order(self, *_a, **_k): return self
    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self
    def is_(self, col, val):
        assert val == "null"
        self._rows = [r for r in self._rows if r.get(col) is None]
        return self
    def update(self, patch):
        self._update = patch
        return self
    def execute(self):
        if self._update is not None:
            for r in self._rows:
                r.update(self._update)
        return types.SimpleNamespace(data=[dict(r) for r in self._rows])


class _Rpc:
    def __init__(self, db, name, p): self._db, self._name, self._p = db, name, p
    def execute(self):
        assert self._name == "claim_license_device"
        p, rows = self._p, self._db.setdefault("license_device_activations", [])
        live = [r for r in rows if r["user_id"] == p["p_user_id"] and r["product"] == p["p_product"]
                and r.get("deactivated_at") is None]
        limit = self._db.get("_limit", 3)
        for r in live:
            if r["device_id"] == p["p_device_id"]:
                return types.SimpleNamespace(data={"status": "existing", "activation_id": r["id"],
                                                   "limit": limit, "active": len(live)})
        if len(live) >= limit:
            return types.SimpleNamespace(data={"status": "limit", "limit": limit, "active": len(live)})
        row = {"id": str(uuid.uuid4()), "user_id": p["p_user_id"], "product": p["p_product"],
               "device_id": p["p_device_id"], "device_name": p["p_device_name"], "platform": p["p_platform"],
               "activated_at": "2026-09-17T00:00:00+00:00", "last_seen_at": "2026-09-17T00:00:00+00:00",
               "deactivated_at": None}
        rows.append(row)
        return types.SimpleNamespace(data={"status": "created", "activation_id": row["id"],
                                           "limit": limit, "active": len(live) + 1})


class _Admin:
    def get_user_by_id(self, uid):
        if uid == "u1":
            return types.SimpleNamespace(user=types.SimpleNamespace(email="andrew@example.com"))
        raise LookupError("no such user")


class _Client:
    def __init__(self, db):
        self._db = db
        self.auth = types.SimpleNamespace(admin=_Admin())
    def table(self, name): return _Query(self._db, name)
    def rpc(self, name, params): return _Rpc(self._db, name, params)


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
DEV_A, DEV_B, DEV_C, DEV_D = "device-aaaaaaaa", "device-bbbbbbbb", "device-cccccccc", "device-dddddddd"


def db(status="active", end=future, price="price_year", active_key=True, has_sub=True):
    return {
        "user_license_keys": [{"id": "lic-1", "user_id": "u1", "license_key": "GOOD-KEY", "is_active": active_key}],
        "subscription_profiles": ([{"user_id": "u1", "environment": "production", "subscription_status": status,
                                    "subscription_end_at": end, "stripe_price_id": price}] if has_sub else []),
        "platform_plans": [{"stripe_price_id": "price_year", "environment": "production", "billing_interval": "year", "name": "Annual Plan"},
                           {"stripe_price_id": "price_month", "environment": "production", "billing_interval": "month", "name": "Monthly Plan"}],
        "license_device_activations": [],
    }


def call(key="GOOD-KEY", data=None, boom=False, body=None, raw_body=None):
    lf._client = None
    if data is not None:
        fake.DB = data
    fake.BOOM = boom
    payload = {"device_id": DEV_A, "device_name": "ANDREW-PC", "platform": "Windows 11", "app_version": "2.3.0"}
    if body is not None:
        payload = body
    ev = {"headers": ({"Auth-Token": key} if key is not None else {}),
          "body": raw_body if raw_body is not None else json.dumps(payload)}
    r = lf.lambda_handler(ev, None)
    return r["statusCode"], json.loads(r["body"])


results = []
def check(name, got, want_status, want_sub):
    status, body = got
    ok = status == want_status and all(body.get(k) == v for k, v in want_sub.items())
    results.append(ok)
    print(("PASS" if ok else "FAIL"), name, "->", status, {k: body.get(k) for k in list(want_sub) or list(body)})
    return body


# ---- request validation -----------------------------------------------------
check("missing header -> 400", call(key=None, data=db()), 400, {"error": "missing_auth_token"})
check("body not json -> 400", call(data=db(), raw_body="{nope"), 400, {"error": "invalid_json"})
check("body json array -> 400", call(data=db(), raw_body="[1]"), 400, {"error": "invalid_json"})
check("unknown action -> 400", call(data=db(), body={"action": "explode", "device_id": DEV_A}), 400, {"error": "invalid_action"})
check("no device_id -> 400", call(data=db(), body={}), 400, {"error": "missing_device_id"})
check("short device_id -> 400", call(data=db(), body={"device_id": "abc"}), 400, {"error": "missing_device_id"})

# ---- subscription rule (unchanged from before) --------------------------------
check("unknown key -> invalid", call(key="NOPE", data=db()), 200, {"allowed": False, "reason": "invalid_key"})
check("inactive key -> invalid", call(data=db(active_key=False)), 200, {"allowed": False, "reason": "invalid_key"})
check("no sub row -> no_subscription", call(data=db(has_sub=False)), 200, {"allowed": False, "reason": "no_subscription", "email": "andrew@example.com"})
check("expired date -> expired", call(data=db(end=past)), 200, {"allowed": False, "reason": "expired"})
check("trialing -> expired", call(data=db(status="trialing")), 200, {"allowed": False, "reason": "expired"})
check("monthly -> not_annual", call(data=db(price="price_month")), 200, {"allowed": False, "reason": "not_annual"})
b = check("a refused activation claims no slot", call(data=db(price="price_month")), 200, {"allowed": False})
results.append(len(fake.DB["license_device_activations"]) == 0)
print(("PASS" if results[-1] else "FAIL"), "  ...and the activations table is still empty")
check("backend down -> 503", call(data=db(), boom=True), 503, {"error": "service_unavailable"})

# ---- device slots -----------------------------------------------------------
shared = db()
b = check("device A activates -> 1 of 3", call(data=shared), 200, {"allowed": True, "devices_used": 1, "device_limit": 3, "plan": "Annual Plan"})
tok_a = b["activation_token"]
check("device A again -> still 1 (idempotent)", call(), 200, {"allowed": True, "devices_used": 1})
check("device B -> 2 of 3", call(body={"device_id": DEV_B, "device_name": "LAB-PC"}), 200, {"allowed": True, "devices_used": 2})
check("device C -> 3 of 3", call(body={"device_id": DEV_C, "device_name": "LAPTOP"}), 200, {"allowed": True, "devices_used": 3})
b = check("device D -> device_limit", call(body={"device_id": DEV_D, "device_name": "SHARED-WITH-A-FRIEND"}), 200,
          {"allowed": False, "reason": "device_limit", "device_limit": 3, "email": "andrew@example.com"})
names = [d["device_name"] for d in b.get("devices", [])]
results.append(names == ["ANDREW-PC", "LAB-PC", "LAPTOP"])
print(("PASS" if results[-1] else "FAIL"), "  ...and it names the three computers holding the slots:", names)
results.append("activation_token" not in b)
print(("PASS" if results[-1] else "FAIL"), "  ...and carries no token")

# ---- check-in ---------------------------------------------------------------
check("check A -> allowed", call(body={"action": "check", "device_id": DEV_A}), 200, {"allowed": True, "email": "andrew@example.com"})
check("check D (never activated) -> device_deactivated", call(body={"action": "check", "device_id": DEV_D}), 200, {"allowed": False, "reason": "device_deactivated"})
results.append(len([r for r in fake.DB["license_device_activations"] if r["deactivated_at"] is None]) == 3)
print(("PASS" if results[-1] else "FAIL"), "  ...and check claimed no slot for D")

# subscription lapses after activation: check must still say yes (permanent)
fake.DB["subscription_profiles"][0]["subscription_status"] = "canceled"
check("check A after subscription canceled -> still allowed", call(body={"action": "check", "device_id": DEV_A}), 200, {"allowed": True})
check("...but a NEW activation is refused", call(body={"device_id": DEV_D}), 200, {"allowed": False, "reason": "expired"})
fake.DB["subscription_profiles"][0]["subscription_status"] = "active"

# ---- deactivate, from the app and from the portal -------------------------------
check("deactivate B from the app", call(body={"action": "deactivate", "device_id": DEV_B}), 200, {"deactivated": True})
check("deactivate B twice -> false", call(body={"action": "deactivate", "device_id": DEV_B}), 200, {"deactivated": False})
check("check B -> device_deactivated", call(body={"action": "check", "device_id": DEV_B}), 200, {"allowed": False, "reason": "device_deactivated"})
check("device D now fits -> 3 of 3", call(body={"device_id": DEV_D, "device_name": "NEW-PC"}), 200, {"allowed": True, "devices_used": 3})
# portal-side deactivation is a plain row update; simulate it on C
for r in fake.DB["license_device_activations"]:
    if r["device_id"] == DEV_C:
        r["deactivated_at"] = "2026-09-17T12:00:00+00:00"
check("check C after portal deactivation -> locked", call(body={"action": "check", "device_id": DEV_C}), 200, {"allowed": False, "reason": "device_deactivated"})

# key regenerated: old key dies everywhere, new key re-binds the same computer without a new slot
fake.DB["user_license_keys"][0]["is_active"] = False
fake.DB["user_license_keys"].append({"id": "lic-2", "user_id": "u1", "license_key": "NEW-KEY", "is_active": True})
check("check A with the old key -> invalid_key", call(body={"action": "check", "device_id": DEV_A}), 200, {"allowed": False, "reason": "invalid_key"})
check("activate A with the new key -> existing slot", call(key="NEW-KEY"), 200, {"allowed": True, "devices_used": 2, "license_id": "lic-2"})

# ---- token is bound to the device ------------------------------------------------
lic, mac = tok_a.split(".")
def want(dev): return hmac.new(b"testsecret", f"{lic}:{dev}:device-hub-pro".encode(), hashlib.sha256).hexdigest()
results.append(mac == want(DEV_A)); print(("PASS" if results[-1] else "FAIL"), "token verifies on the computer it was issued to")
results.append(mac != want(DEV_B)); print(("PASS" if results[-1] else "FAIL"), "the same token fails on a different computer")

fails = results.count(False)
print(f"\nRESULT: {len(results) - fails}/{len(results)} passed" + ("" if not fails else f", {fails} FAILED"))
sys.exit(1 if fails else 0)
