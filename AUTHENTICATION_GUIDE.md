# NonKYC Authentication Guide

This guide explains the **correct** authentication settings for NonKYC.io, verified with the official API client and debug testing.

## ✅ Verified Working Configuration

### Nonce Generation
```python
import time
nonce = int(time.time() * 1000)  # 1e3 multiplier
# Result: 13-digit number (milliseconds since epoch)
# Example: 1769016991318
```

**Correct**: `1e3` (1000) → 13 digits
**Incorrect**: `1e4` (10000) → 14 digits ❌

### Signature Format

For a GET request to `/balances`:

```python
# Message to sign
message = api_key + full_url + nonce
# Example: "6731a21f...https://api.nonkyc.io/api/v2/balances1769016991318"

# Generate HMAC-SHA256 signature
signature = hmac.new(
    api_secret.encode('utf8'),
    message.encode('utf8'),
    hashlib.sha256
).hexdigest()
```

**CRITICAL**: Must sign the **FULL absolute URL**, not just the path!

✅ **Correct**: `https://api.nonkyc.io/api/v2/balances`
❌ **Incorrect**: `/balances`
❌ **Incorrect**: `/api/v2/balances`

### HTTP Headers

```python
headers = {
    "X-API-KEY": api_key,
    "X-API-NONCE": str(nonce),
    "X-API-SIGN": signature,
}
```

## Bot Configuration

The bot **defaults to the correct settings** automatically. You don't need to specify these in your config unless debugging.

### Default Behavior

```python
# In RestClient.__init__
if sign_absolute_url is None:
    self.sign_absolute_url = True  # Defaults to full URL signing ✓
```

### Debug Mode (Development Only)

To see authentication details:

```yaml
# config.yml
debug_auth: true  # WARNING: Shows sensitive data, NEVER use in production!
```

Or via environment variable:
```bash
export NONKYC_DEBUG_AUTH=1
python run_grid.py config.yml
```

## Testing Your Setup

### Quick Test
```bash
# Make sure credentials are set
export NONKYC_API_KEY="your_key"
export NONKYC_API_SECRET="your_secret"

# Test authentication
python test_auth.py
```

### Comprehensive Debug Test
```bash
# Tests all signing variations to identify issues
python debug_auth.py
```

This will test:
1. Path only + 13-digit nonce
2. Path with /api/v2 + 13-digit nonce
3. Full URL + 13-digit nonce ← **This should work!**
4. Path only + 14-digit nonce
5. Full URL + 14-digit nonce

Expected output:
```
✅ WORKING CONFIGURATION FOUND!
Variant: Full URL + 13 digit nonce
URL part to sign: https://api.nonkyc.io/api/v2/balances
Nonce multiplier: 1e3
```

## Common Issues

### 401 Unauthorized Errors

If you get 401 errors even with correct settings:

1. **Invalid Credentials** - API key/secret wrong or revoked
   - Verify on NonKYC website
   - Regenerate if needed

2. **IP Whitelist** - Your IP not whitelisted
   - Check NonKYC API settings
   - Add your current IP address
   - VPN changes your IP!

3. **Permissions** - API key lacks permissions
   - Ensure "Read" permission for balances
   - Ensure "Trade" permission for orders

4. **Clock Skew** - System clock out of sync
   - Use NTP to sync time
   - Or enable server time sync:
     ```yaml
     use_server_time: true
     ```

### Debugging Tips

1. **Enable debug mode** to see exactly what's being signed
2. **Compare with working example** from `debug_auth.py`
3. **Test credentials separately** with `test_auth.py`
4. **Verify nonce length** - must be 13 digits

## Reference Implementation

From the official NonKYC Python client:
```python
# From https://github.com/NonKYCExchange/NonKycPythonApiClient
nonce = str(int(time()*1000))  # 1000 = 1e3 multiplier
message = access_key + payload + nonce
signature = hmac.new(
    secret_key.encode(),
    message.encode(),
    hashlib.sha256
).hexdigest()
```

## Bot Implementation Files

Authentication is implemented in:
- `src/nonkyc_client/auth.py` - AuthSigner class
- `src/nonkyc_client/rest.py` - RestClient with signing logic
- `src/engine/grid_runner.py` - Grid bot client setup
- `run_*.py` - Bot runners with client initialization

All use the correct settings by default!

## Environment Variables

Override settings via environment:
```bash
export NONKYC_API_KEY="your_key"              # API key
export NONKYC_API_SECRET="your_secret"        # API secret
export NONKYC_DEBUG_AUTH=1                     # Enable debug output
export NONKYC_SIGN_FULL_URL=1                  # Force full URL signing (default anyway)
export NONKYC_USE_SERVER_TIME=1                # Use server time for nonce
```

## Summary

✅ **Nonce**: 13 digits (1e3 multiplier)
✅ **URL**: Full absolute URL
✅ **Headers**: X-API-KEY, X-API-NONCE, X-API-SIGN
✅ **Default**: Bot uses correct settings automatically

**No configuration changes needed** - the bot is already correct!

If you get 401 errors, it's likely credentials/IP whitelist, not the bot implementation.
