# license-check — POST /prod/activate

Yes/no license check for Device Hub Pro advanced features, using the existing
evbdata.com portal license key. Lives on the same REST API as `/uploads`
(`smv4232qo6`, us-east-1) as a separate resource with **no authorizer**; the
Lambda validates the key itself so it can return real reasons and a 503 on
backend failure instead of a misleading 403.

`/uploads` and its token-authorizer are untouched.

## Rule

`allowed: true` only when all of:

1. `user_license_keys` has the key with `is_active = true`
2. that user's `subscription_profiles` row (`environment = production`) has
   `subscription_status = 'active'` and `subscription_end_at` in the future
3. its `stripe_price_id` maps to a `platform_plans` row with `billing_interval = 'year'`

Trials and monthly plans are a **no**. Permanence is the client's job: store a
yes once and never re-check.

## Request

```
POST https://smv4232qo6.execute-api.us-east-1.amazonaws.com/prod/activate
auth-token: <license key from evbdata.com Settings>
```

Body is ignored.

## Responses

Yes/no is always HTTP 200:

```json
{"allowed": true, "email": "user@example.com", "product": "device-hub-pro", "plan": "Annual Plan",
 "subscription_end_at": "2027-03-01T00:00:00+00:00",
 "license_id": "<uuid>", "activation_token": "<uuid>.<hmac-sha256 hex>"}

{"allowed": false, "reason": "invalid_key"}                                  // unknown or deactivated key
{"allowed": false, "reason": "no_subscription", "email": "user@example.com"} // no subscription_profiles row
{"allowed": false, "reason": "expired", "email": "user@example.com"}         // status not active, or end date passed (includes trials)
{"allowed": false, "reason": "not_annual", "email": "user@example.com"}      // monthly or unknown plan
```

`email` is the portal account the key belongs to, looked up through the Supabase
auth admin API. It is present whenever the key resolved to an account, so the
app can show "Connected as user@example.com" even on a no. It may be null if
the auth lookup fails; the decision does not depend on it.

Not a decision — retry later, keep last known state:

| HTTP | body.error | cause |
|---|---|---|
| 400 | `missing_auth_token` | no `auth-token` header |
| 503 | `service_unavailable` | Supabase unreachable or function env not set |

## activation_token

`"<license_id>.<hex>"` where `hex = HMAC-SHA256(secret, "<license_id>:device-hub-pro")`.
The secret is `ACTIVATION_HMAC_SECRET` on the Lambda and is also embedded in
the Device Hub Pro build (saved by `set-env.ps1` to `activation_hmac_secret.txt`,
git-ignored). Client verification:

```python
import hashlib, hmac
def token_ok(token: str, secret: str) -> bool:
    lic, _, mac = token.partition(".")
    want = hmac.new(secret.encode(), f"{lic}:device-hub-pro".encode(), hashlib.sha256).hexdigest()
    return bool(lic) and hmac.compare_digest(mac, want)
```

Store the token in the per-user app-data directory (not the workspace). On
startup, unlock if the stored token verifies. No expiry, no re-check.

## Files

- `lambda_function.py` — the handler (never logs the key or headers)
- `deploy.ps1` — package + create/update Lambda + wire `POST /activate` + deploy stage `prod` (re-runnable)
- `set-env.ps1` — run by the account owner: copies Supabase creds from `token-authorizer`, generates the HMAC secret, sets the env
- `fix-logging.ps1` — one-time: gives the function its own role so it can write to `/aws/lambda/license-check` (the borrowed token-authorizer role cannot)
- `test_local.py` — offline tests with a fake Supabase client (`python test_local.py`)

## Deploy

```powershell
& .\deploy.ps1      # creates function + route, deploys prod
& .\set-env.ps1     # sets env vars; writes activation_hmac_secret.txt
```

Then smoke test:

```powershell
curl.exe -s -X POST https://smv4232qo6.execute-api.us-east-1.amazonaws.com/prod/activate -H "auth-token: not-a-key"
# -> {"allowed": false, "reason": "invalid_key"}
```
