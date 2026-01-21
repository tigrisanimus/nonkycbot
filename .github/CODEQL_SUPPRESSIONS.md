# CodeQL False Positive Suppressions

This document explains CodeQL security alerts that are **false positives** and why they can be safely ignored.

## 1. "Use of weak cryptographic algorithm" (HMAC-SHA256)

**Alert:** `py/weak-cryptographic-algorithm`
**Files:** `test_auth.py`, `src/nonkyc_client/auth.py`
**Severity:** High (False Positive)

### Why This Is a False Positive

CodeQL flags HMAC-SHA256 usage because it detects "password" (API secret) being used with SHA256. However:

1. **We are NOT hashing passwords** - We're creating HMAC signatures for API request authentication
2. **HMAC-SHA256 is the REQUIRED algorithm** per the [nonkyc.io API specification](https://api.nonkyc.io/api/v2/)
3. **This is the industry standard** for REST API authentication (used by AWS, Stripe, Coinbase, etc.)
4. **HMAC-SHA256 is secure** for this purpose - it's specifically designed for message authentication

### The Correct Context

```python
# This is CORRECT usage for API request signing:
signature = hmac.new(api_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
```

**If we were hashing passwords**, we would use:
- `bcrypt`, `scrypt`, or `argon2` (computationally expensive)
- **NOT** plain SHA256

But we're not hashing passwords - we're signing API requests, which is exactly what HMAC-SHA256 is designed for.

### Official API Documentation

From the nonkyc.io API docs:
```python
# Official example from NonKYCExchange/nonkycapinodehmac
const message = apiKey + url + body + nonce;
const signature = crypto.createHmac('sha256', apiSecret).update(message).digest('hex');
```

## 2. "Clear-text logging of sensitive information" (Nonce)

**Alert:** `py/clear-text-logging-sensitive-data`
**Files:** `test_auth.py`
**Severity:** High (False Positive)

### Why This Is a False Positive

CodeQL flags logging of the `nonce` value as "sensitive data exposure". However:

1. **The nonce is NOT a secret** - It's a public timestamp value
2. **The nonce is sent in clear text** in the `X-API-NONCE` header (visible in network traffic)
3. **The nonce changes every request** - It's just `Date.now()` in milliseconds
4. **Logging the nonce is necessary** for debugging authentication issues (verifying it's 13 digits)

### The Nonce Is Public

The nonce is literally just:
```python
nonce = str(int(time.time() * 1000))  # e.g., "1737419347581"
```

It's a **public timestamp**, not a credential. Anyone can generate the same nonce by calling `Date.now()`.

### What IS Secret

- ✅ **API Key** - We redact this: `[REDACTED] (32 chars)`
- ✅ **API Secret** - Never logged at all
- ✅ **Signature** - We redact this: `[REDACTED] (64 chars)`
- ❌ **Nonce** - Public timestamp, safe to log: `1737419347581`

## 3. "Clear-text logging of sensitive information" (HTTP Request)

**Alert:** `py/clear-text-logging-sensitive-data`
**Files:** `test_auth.py`
**Line:** `response = requests.get(full_url, headers=headers, timeout=10)`
**Severity:** High (False Positive)

### Why This Is a False Positive

CodeQL flags the HTTP request because it "sends sensitive data over the network". However:

1. **This is an authentication test script** - The entire purpose is to test sending credentials
2. **The request uses HTTPS** - All data is encrypted in transit (TLS 1.2+)
3. **This is how REST API authentication works** - Credentials MUST be sent to authenticate
4. **We're using standard headers** - `X-API-KEY`, `X-API-SIGN`, `X-API-NONCE` (industry standard)

### This Is Not Logging

The flagged line is **making an API request**, not logging sensitive data. This is the core functionality of the authentication system.

## Summary

All CodeQL "High Severity" alerts in this repository are **false positives** related to:

1. Using HMAC-SHA256 correctly for API authentication (not password hashing)
2. Logging public nonce values (timestamps, not secrets)
3. Sending authentication headers over HTTPS (required for API usage)

These are **standard practices** for REST API client libraries and are **secure**.

---

**Last Updated:** 2026-01-21
**Reviewed By:** Claude Code Agent
**Status:** All alerts confirmed as false positives
