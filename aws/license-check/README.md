# license-check: POST /prod/activate

Yes/no license check for Device Hub Pro advanced features, using the existing
evbdata.com portal license key, capped at three computers per account.

Lives on the same REST API as `/uploads` (`smv4232qo6`, us-east-1) as a
separate resource with **no authorizer**; the Lambda validates the key itself
so it can return real reasons and a 503 on backend failure instead of a
misleading 403. `/uploads` and its token-authorizer are untouched.

**Depends on the portal migration
`20260917120000_license_device_activations.sql`** (data-web-portal repo, branch
`feature/license-device-activations`). Deploy this Lambda only after that
migration is on the database it points at, or every activation answers 503.
The same holds for `20261020120000_product_entitlements.sql` (Enterprise
grants, below): run it before deploying this version.

## Request

```
POST https://smv4232qo6.execute-api.us-east-1.amazonaws.com/prod/activate
auth-token: <license key from evbdata.com Settings>
Content-Type: application/json

{
  "action": "activate",            // activate (default) | check | deactivate
  "device_id": "<salted machine hash>",   // required, 8-128 chars of A-Z a-z 0-9 _ - : .
  "device_name": "ANDREW-PC",      // shown to the customer in the portal
  "platform": "Windows 11",
  "app_version": "2.3.0"
}
```

`device_id` is a salted SHA-256 of the OS machine identifier (Windows
`MachineGuid`, macOS `IOPlatformUUID`, Linux `/etc/machine-id`), hex. The raw
identifier never leaves the computer.

## The three actions

| action | when the app calls it | looks at subscription | claims a slot |
|---|---|---|---|
| `activate` | the user typed a key | yes, annual rule below | yes, or reuses this computer's |
| `check` | startup, and once every 24 h while online | **no**, activation is permanent | never |
| `deactivate` | "Sign out this computer" in the app | no | frees this computer's |

### Activation rule

`allowed: true` only when all of:

1. `user_license_keys` has the key with `is_active = true`
2. that user's `subscription_profiles` row (`environment = production`) has
   `subscription_status = 'active'` and `subscription_end_at` in the future
3. its `stripe_price_id` maps to a `platform_plans` row with `billing_interval = 'year'`
4. the account has a free slot, or this computer already holds one. The cap is
   `user_profiles.device_activation_limit`, default 3, editable per account on
   the portal's admin customer page

Trials and monthly plans are a **no**. The cap is per account, not per key
string, so regenerating a key does not hand out three fresh slots.

## Responses

A decision is always HTTP 200:

```json
// activate, yes
{"allowed": true, "email": "user@example.com", "product": "device-hub-pro",
 "plan": "Annual Plan", "subscription_end_at": "2027-03-01T00:00:00+00:00",
 "license_id": "<uuid>", "devices_used": 2, "device_limit": 3,
 "activation_token": "<license_id>.<hmac-sha256 hex>"}

// check, yes. Usage is current as of this call, so it follows deactivations
// made in the portal and a cap changed by an admin.
{"allowed": true, "email": "user@example.com", "product": "device-hub-pro",
 "license_id": "<uuid>", "devices_used": 2, "device_limit": 3,
 "activation_token": "..."}

// deactivate
{"deactivated": true}      // false if this computer held no slot

// no
{"allowed": false, "reason": "invalid_key"}
{"allowed": false, "reason": "no_subscription", "email": "..."}
{"allowed": false, "reason": "expired", "email": "..."}        // includes trials
{"allowed": false, "reason": "not_annual", "email": "..."}
{"allowed": false, "reason": "device_limit", "email": "...", "device_limit": 3,
 "devices": [{"device_name": "ANDREW-PC", "platform": "Windows 11",
              "activated_at": "...", "last_seen_at": "..."}, ...]}
{"allowed": false, "reason": "device_deactivated", "email": "..."}   // check only
```

`email` is the portal account the key belongs to, present whenever the key
resolved to an account, so the app can show "Connected as ..." even on a no.

Not a decision, keep the last known state and try again later:

| HTTP | body.error | cause |
|---|---|---|
| 400 | `missing_auth_token` | no `auth-token` header |
| 400 | `invalid_json` / `invalid_action` / `missing_device_id` | malformed request |
| 503 | `service_unavailable` | Supabase unreachable, migration missing, or function env not set |

## What the app does

1. **First run / key entered:** `activate`. On yes, store the key, the
   `activation_token` and the email in the per-user app-data directory (not the
   workspace, so workspace resets keep it). On `device_limit`, show the three
   computer names from `devices` and point the user at Profile Settings on
   evbdata.com, where each has a Deactivate button.
2. **Every startup, and every 24 h while running:** verify the stored token
   locally (below). If it fails, lock. If it passes, unlock at once, then call
   `check` in the background:
   - `allowed: true` → nothing to do
   - `allowed: false` (`device_deactivated` or `invalid_key`) → delete the
     stored token, lock advanced features, ask for a key
   - network error, timeout, 5xx, 400 → **stay unlocked**. Offline use is
     permanent by design; this exists to stop key sharing, not to police a
     customer's own machines
3. **Sign out this computer:** `deactivate`, then delete the stored token.

## activation_token

`"<license_id>.<hex>"` where
`hex = HMAC-SHA256(secret, "<license_id>:<device_id>:device-hub-pro")`.

The device id is inside the MAC, so a token file copied to another computer
fails there: that computer hashes to a different device id. The secret is
`ACTIVATION_HMAC_SECRET` on the Lambda and is also embedded in the Device Hub
Pro build (`set-env.ps1` saved it to `activation_hmac_secret.txt`, git-ignored).

```python
import hashlib, hmac
def token_ok(token: str, device_id: str, secret: str) -> bool:
    lic, _, mac = token.partition(".")
    msg = f"{lic}:{device_id}:device-hub-pro".encode()
    want = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return bool(lic) and hmac.compare_digest(mac, want)
```

Tokens issued before the device limit (MAC over `<license_id>:device-hub-pro`)
no longer verify. Only test accounts held one.

## Enterprise (features)

Every yes from `activate` and `check` also carries

```json
"features": ["enterprise"],          // or [] — the account's live grants, sorted
"features_token": "<hmac-sha256 hex>"
```

with `features_token = HMAC-SHA256(secret, "<license_id>:<device_id>:device-hub-pro:features:<comma-joined features>")`.
Device Hub Pro keeps the features only while that token verifies, and
Enterprise unlocks Custom Views.

Grants live in `product_entitlements` (portal migration
`20261020120000_product_entitlements.sql`), written by an admin with SQL per
contract. A grant is live when started, not expired and not revoked. A live
`enterprise` grant replaces the annual-subscription rule at activation (`plan`
is then `"Enterprise"`, `subscription_end_at` null); the device cap still
applies. Features are re-read on every `check`, unlike the subscription, so
revoking or expiring a grant turns Enterprise off at the app's next start
while Advanced stays.

## Files

- `lambda_function.py`: the handler (never logs the key, headers or device id)
- `deploy.ps1`: package + create/update Lambda + wire `POST /activate` + deploy stage `prod` (re-runnable)
- `set-env.ps1`: run by the account owner: copies Supabase creds from `token-authorizer`, generates the HMAC secret, sets the env
- `fix-logging.ps1`: one-time: gives the function its own role so it can write to `/aws/lambda/license-check`
- `test_local.py`: 36 offline checks with a fake Supabase client (`python test_local.py`)

The SQL side (table, cap, `claim_license_device()`, grants) is checked by
`scripts/checks/license-device-activations.sql` in the portal repo.

## Deploy

```
pwsh -File deploy.ps1      # updates the function code; route and env are already in place
```

Smoke test:

```
curl.exe -s -X POST https://smv4232qo6.execute-api.us-east-1.amazonaws.com/prod/activate -H "auth-token: not-a-key" -H "Content-Type: application/json" -d "{\"device_id\":\"smoke-test-0001\"}"
# -> {"allowed": false, "reason": "invalid_key"}
```
