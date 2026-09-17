# Device Hub Pro: license activation, integration brief

Wire Device Hub Pro's Advanced features (extra analyses, Measure, Custom Views)
to the license service below. The service is live and tested. Nothing on the
server needs to change. Replace any earlier attempt that posted to `/uploads`
with `sensor_id: "device-hub-pro"`; that endpoint is for sensor uploads and will
always refuse.

Reference implementation of every call and of the device id:
`DataCollectionPanel/aws/license-check/try_local.py`. Full contract:
`README.md` in the same folder.

## What the user should experience

1. **Enter key once.** A License dialog takes the key from evbdata.com, Profile
   Settings. On success, Advanced unlocks and stays unlocked across restarts and
   workspace resets, including offline.
2. **See who and how many.** The License dialog shows "Connected as
   <email>", the plan name, and **"N of M activations left"**, where
   left = `device_limit - devices_used`.
3. **Deactivate this computer** from the same dialog. It frees the slot and
   locks Advanced on this machine until a key is entered again.
4. **Check on every startup.** If this computer was deactivated elsewhere (the
   customer's portal page or by support), Advanced locks at the next start
   while online.
5. **At the limit,** the dialog says the key is in use on the maximum number of
   computers, lists their names, and says to deactivate one at evbdata.com,
   Profile Settings, Activated computers. The app can only deactivate the
   computer it is running on.

## Endpoint

```
POST https://smv4232qo6.execute-api.us-east-1.amazonaws.com/prod/activate
auth-token: <license key>
Content-Type: application/json

{
  "action": "activate" | "check" | "deactivate",
  "device_id": "<64 hex chars, see below>",
  "device_name": "<computer name, shown to the customer>",
  "platform": "Windows 11",
  "app_version": "<app version>"
}
```

Timeout 10 s. Never log the key, the `auth-token` header, or the activation
token.

### device_id

Salted SHA-256 of the OS machine identifier, lowercase hex. The raw identifier
must never leave the machine. Use exactly this so ids are stable:

```python
DEVICE_SALT = "evb-device-hub-pro-v1"
device_id = hashlib.sha256(f"{DEVICE_SALT}:{machine_identifier}".encode()).hexdigest()
```

`machine_identifier`: Windows `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`;
macOS `IOPlatformUUID` from `ioreg -rd1 -c IOPlatformExpertDevice`; Linux
`/etc/machine-id`. `device_name` is the hostname.

## Responses

A decision is always HTTP 200. Read `allowed` (or `deactivated`).

```json
// activate, yes
{"allowed": true, "email": "user@example.com", "product": "device-hub-pro",
 "plan": "Annual Plan", "subscription_end_at": "2027-09-15T19:04:09+00:00",
 "license_id": "<uuid>", "devices_used": 1, "device_limit": 3,
 "activation_token": "<license_id>.<64 hex>"}

// check, yes
{"allowed": true, "email": "user@example.com", "product": "device-hub-pro",
 "license_id": "<uuid>", "devices_used": 1, "device_limit": 3,
 "activation_token": "<license_id>.<64 hex>"}

// deactivate
{"deactivated": true}

// no
{"allowed": false, "reason": "<reason>", "email": "user@example.com"}
```

| reason | meaning | message to show |
|---|---|---|
| `invalid_key` | unknown or deactivated key (no `email`) | That license key is not valid. |
| `no_subscription` | account has no subscription | Advanced requires an annual subscription. |
| `expired` | not an active paid subscription (includes trials) | Advanced requires an active annual subscription. |
| `not_annual` | monthly plan | Advanced is included with the annual plan. |
| `device_limit` | all slots used; body also has `device_limit` and `devices: [{device_name, platform, activated_at, last_seen_at}]` | list the names, point to the portal |
| `device_deactivated` | `check` only: this computer no longer holds a slot | This computer was deactivated. Enter your key to activate again. |

Anything that is not HTTP 200 is **not a decision**: 400 (`missing_auth_token`,
`invalid_json`, `invalid_action`, `missing_device_id`), 503
(`service_unavailable`), timeouts, no network. Never lock on these.

## Required behavior

**Activate (user enters key)**
- Call `activate`. On `allowed: true`, store key, `activation_token`, `email`,
  `plan`, `devices_used`, `device_limit`. Unlock Advanced.
- On `allowed: false`, show the message for the reason. Store nothing.
- On a non-decision, say the license server could not be reached and to try
  again. Store nothing.

**Startup, every launch**
1. Load the stored state. If none, Advanced is locked; stop.
2. Verify the stored token locally (below). If it fails, delete the stored
   state and lock.
3. If it passes, **unlock immediately**. Do not wait on the network.
4. In the background, call `check`.
   - `allowed: true`: update stored `devices_used`, `device_limit`, `email`,
     `activation_token`.
   - `allowed: false` (`device_deactivated` or `invalid_key`): delete the stored
     state, lock Advanced, tell the user why.
   - non-decision: do nothing. Offline use is permanent by design.
   - Subscription lapsing does **not** lock an activated computer; `check`
     ignores the subscription on purpose.

**Deactivate this computer (button in the License dialog)**
- Confirm first. Call `deactivate`. On `{"deactivated": true}` or `false`,
  delete the stored state and lock. On a non-decision, keep everything and say
  it could not reach the server; do not pretend it worked.

**Storage**
- Per-user application data directory, **not** the workspace, so workspace
  resets keep it (Windows `%APPDATA%\EVidentBattery\DeviceHubPro\license.json`
  or the app's existing per-user settings location).
- The key is a credential. Prefer the OS keychain (Windows Credential Manager,
  macOS Keychain) for the key and the file for the rest. If that is not
  practical, restrict the file to the user.

## Verifying the activation token offline

`activation_token = "<license_id>.<mac>"`, where
`mac = HMAC-SHA256(secret, "<license_id>:<device_id>:device-hub-pro")` as
lowercase hex. The device id is inside the MAC, so a token copied to another
computer fails there.

```python
import hashlib, hmac
def token_ok(token: str, device_id: str, secret: str) -> bool:
    lic, _, mac = token.partition(".")
    msg = f"{lic}:{device_id}:device-hub-pro".encode()
    want = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return bool(lic) and hmac.compare_digest(mac, want)
```

The secret is in
`DataCollectionPanel/aws/license-check/activation_hmac_secret.txt` on the
owner's machine. It is git-ignored: read it at build time and embed it in the
binary; **do not commit it** or put it in a tracked config file. This is
tamper resistance against editing a settings file, not strong security, since
a secret shipped in a client can be extracted. The server-side device limit is
the real control.

## Acceptance tests

Against the live endpoint with a real annual-plan key (owner has one):

1. Fresh install, enter key: Advanced unlocks, dialog shows email and "2 of 3
   activations left".
2. Restart offline: Advanced still unlocked, no error shown.
3. Restart online: counts refresh.
4. Deactivate this computer in the portal (Profile Settings), restart online:
   Advanced locks with the deactivated message. Restart offline instead: stays
   unlocked.
5. Deactivate from the app: locks at once; portal shows the slot freed.
6. Copy the stored license file to a second computer: Advanced stays locked
   there (token fails verification).
7. With three computers active, a fourth shows the limit message with the three
   names.
8. Wrong key: "not valid", nothing stored.
9. Server unreachable during key entry: clear retry message, nothing stored,
   and an already-activated install is unaffected.
10. The key never appears in logs.
