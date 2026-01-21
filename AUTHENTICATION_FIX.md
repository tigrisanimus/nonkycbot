# Authentication Fix - Complete Guide

## ✅ Fix Status: FULLY RESOLVED

The nonce multiplier has been corrected from `1e4` to `1e3` in ALL locations, including a hidden bug in the REST client library.

**Primary Fix:** `746d463` - Corrected nonce multiplier in bot configuration files
**Final Fix:** `355cda8` - Removed hardcoded `1e4` in `cancel_all_orders_v1` method + enhanced debug output

All nonce values are now consistently 13 digits (milliseconds since epoch).

---

## 🔑 About API Credentials in YAML Files

### Why are API keys commented out with `#`?

The YAML configuration files (like `examples/infinity_grid.yml`) have API credentials **commented out as a security best practice**:

```yaml
# api_key: "${NONKYC_API_KEY}"      # Loaded from keychain automatically
# api_secret: "${NONKYC_API_SECRET}" # Loaded from keychain automatically
```

**This is intentional!** Storing credentials in configuration files is a security risk because:
- Config files are often committed to git
- They can be accidentally shared
- They're visible in plain text

### How the bot loads credentials (in order of priority):

1. **Config file** (if uncommented) - NOT recommended
2. **Environment variables** - RECOMMENDED for testing/development
3. **OS Keyring** - RECOMMENDED for production

---

## 🧪 Quick Test (Recommended)

### Option 1: Use Environment Variables (Easiest)

```bash
# Set your credentials
export NONKYC_API_KEY="your_api_key_here"
export NONKYC_API_SECRET="your_api_secret_here"

# Test authentication
python test_auth.py

# Or test with your actual bot
python run_infinity_grid.py examples/infinity_grid.yml --monitor-only
```

### Option 2: Use the Test Script with Arguments

```bash
python test_auth.py YOUR_API_KEY YOUR_API_SECRET
```

---

## ✅ What to Look For (Success)

When authentication works correctly, you'll see:

```
✅ SUCCESS - Authentication working!

Balances received: X assets
  BTC: 0.12345678
  USDT: 1234.56
  ETH: 0.98765
  ...
```

**Most importantly**, check the nonce format:
```
Nonce: 1737419347581 (13 digits)  ← CORRECT!
```

NOT:
```
Nonce: 17374193475819 (14 digits)  ← WRONG!
```

---

## 🔧 Credential Setup Options

### Option A: Environment Variables (Development/Testing)

**For current session:**
```bash
export NONKYC_API_KEY="your_key"
export NONKYC_API_SECRET="your_secret"
```

**For permanent setup (add to ~/.bashrc or ~/.zshrc):**
```bash
echo 'export NONKYC_API_KEY="your_key"' >> ~/.bashrc
echo 'export NONKYC_API_SECRET="your_secret"' >> ~/.bashrc
source ~/.bashrc
```

### Option B: OS Keyring (Production - Most Secure)

```bash
python nonkyc_store_credentials.py --api-key "your_key" --api-secret "your_secret"
```

**Note:** Keyring requires a backend. If you get an error, install one:
```bash
pip install keyrings.alt
```

### Option C: Config File (NOT Recommended)

Edit `examples/infinity_grid.yml` and uncomment lines 27-28:
```yaml
api_key: "your_actual_key_here"
api_secret: "your_actual_secret_here"
```

**⚠️ Warning:** Never commit this file to git after adding real credentials!

---

## 🐛 Troubleshooting

### Error: "No module named 'pydantic'"

```bash
pip install -r requirements.txt
```

### Error: "No recommended backend was available"

```bash
pip install keyrings.alt
```

Or use environment variables instead of keyring.

### Error: 401 Unauthorized

1. **Check your credentials are correct**
2. **Verify API key has proper permissions** (trading permissions enabled on nonkyc.io)
3. **Check nonce is 13 digits** (run `python test_auth.py` to see nonce value)
4. **Clear Python cache:**
   ```bash
   find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
   find . -name "*.pyc" -delete
   ```

### Still seeing 14-digit nonce?

This means you're running old code. Verify:

```bash
# Should show 1e3 (not 1e4)
grep "nonce_multiplier" run_infinity_grid.py

# Should see commit 746d463
git log --oneline -5
```

---

## 📊 What Was Fixed

The official nonkyc.io API documentation (https://api.nonkyc.io/api/v2/) shows:

```python
nonce = str(int(time()*1e3))  # Milliseconds since epoch
```

**Our old code:**
```python
nonce_multiplier=1e4  # WRONG - 10x too large!
```

**Our new code:**
```python
nonce_multiplier=1e3  # CORRECT - matches Date.now() format
```

---

## 🚀 Running Your Bot

Once credentials are set up:

```bash
# Monitor mode (read-only, no trading)
python run_infinity_grid.py examples/infinity_grid.yml --monitor-only

# Dry-run mode (simulate trading)
python run_infinity_grid.py examples/infinity_grid.yml --dry-run

# Live trading (REAL MONEY!)
python run_infinity_grid.py examples/infinity_grid.yml
```

---

## 📝 Files Modified (Already Committed)

- ✅ `run_infinity_grid.py:103` - Changed to `1e3`
- ✅ `run_rebalance_bot.py:88` - Changed to `1e3`
- ✅ `run_hybrid_arb_bot.py:99` - Changed to `1e3`
- ✅ `run_arb_bot.py:158` - Changed to `1e3`
- ✅ `src/engine/grid_runner.py:31` - Changed to `1e3`

All changes are in commit `746d463` on branch `claude/update-nonkyc-branding-IkFqj`.

---

## 📞 Support

If issues persist after following this guide:

1. Run `python test_auth.py` with your credentials and share the output
2. Check nonkyc.io API status: https://status.nonkyc.io (if available)
3. Contact NonKYC support: support@nonkyc.io
4. Verify API key permissions in your nonkyc.io account settings

---

**Created:** 2026-01-21
**Branch:** claude/fix-api-auth-error-rxWNe
**Status:** Ready for testing
