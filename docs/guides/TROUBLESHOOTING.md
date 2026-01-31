# Troubleshooting Guide

Common issues and solutions for NonKYC trading bots.

---

## Bot Runs But Doesn't Create Orders

### Symptoms
- Bot starts successfully
- No error messages
- No orders appear on NonKYC exchange
- Bot just polls continuously

### Cause
**Insufficient balance** - Bot needs both base and quote assets to place orders.

### Solution

1. **Check your balance requirements:**
   ```bash
   python scripts/check_grid_balances.py examples/grid.yml
   ```

2. **Fix the issue (choose one):**

   **Option A: Deposit more funds** (Recommended)
   - Deposit both base asset (COSA) and quote asset (USDT)
   - Run the bot again

   **Option B: Reduce order size**
   ```yaml
   # In your config.yml
   base_order_size: "100"    # Reduce from 1000 to 100
   n_buy_levels: 5           # Reduce from 10 to 5
   n_sell_levels: 5          # Reduce from 10 to 5
   ```

   **Option C: Enable auto-rebalance**
   ```yaml
   # If you only have one asset
   startup_rebalance: true
   ```

3. **Delete state file if exists:**
   ```bash
   rm state/grid_state.json
   ```

4. **Run the bot again:**
   ```bash
   python bots/run_grid.py examples/grid.yml
   ```

### How to Prevent
- Always check balance requirements before starting
- Start with small order sizes to test
- Use the diagnostic tool: `scripts/check_grid_balances.py`

---

## Authentication Errors (401 Unauthorized)

### Symptoms
```
HTTP error 401: Not Authorized
RestError: Not Authorized
```

### Causes & Solutions

#### 1. Invalid Credentials
**Test:**
```bash
python scripts/debug_auth.py
```

**Solution:**
- Verify credentials on NonKYC website
- Regenerate API key/secret if needed
- Update your credentials:
  ```bash
  export NONKYC_API_KEY="your_new_key"
  export NONKYC_API_SECRET="your_new_secret"
  ```

#### 2. IP Not Whitelisted
**Check:** NonKYC API settings → IP whitelist

**Solution:**
- Add your current IP address
- If using VPN, add VPN IP or disable IP whitelist
- Your IP may change dynamically (check with `curl ifconfig.me`)

#### 3. API Key Permissions
**Check:** API key has proper permissions

**Solution:**
- Enable "Read" permission (for balances)
- Enable "Trade" permission (for orders)
- Regenerate key if permissions can't be changed

#### 4. Clock Skew
**Symptoms:** Auth works sometimes, fails other times

**Solution:**
```yaml
# In config.yml
use_server_time: true
```

Or sync your system clock:
```bash
# macOS
sudo sntp -sS time.apple.com

# Linux
sudo ntpdate pool.ntp.org
```

---

## Symbol Format Errors

### Symptoms
```
ValueError: Unsupported symbol format: COSA_USDT
```

### Solution
Update to latest version - underscore format is now supported!

**Supported formats:**
- `COSA_USDT` (NonKYC uses this)
- `COSA/USDT` (also supported)
- `COSA-USDT` (also supported)

---

## Infinity Grid Shows "No Rebalance Needed"

### Is This Normal?
✅ **YES!** This is **correct behavior** for infinity grid.

### Why?
Infinity grid is a **rebalance strategy**, not a ladder strategy:
- It waits for price to move by `step_pct` (e.g., 1%)
- Only then does it place an order
- "No rebalance needed" means price hasn't moved enough yet

### Expected Behavior
```
Check #1: Price 50000 → "No rebalance needed" ✅
Check #2: Price 50250 → "No rebalance needed" ✅
Check #3: Price 50505 → "REBALANCE TRIGGERED" 🎯
```

See `GRID_STRATEGIES_EXPLAINED.md` for full details.

---

## Bot Creates No Orders on Ladder Grid

### Check These in Order

1. **Balance sufficient?**
   ```bash
   python scripts/check_grid_balances.py examples/grid.yml
   ```
   - If insufficient: Deposit funds or reduce order size

2. **Check state/grid_state.json:**
   ```bash
   cat state/grid_state.json
   ```
   - If `needs_rebalance: true`: Delete file and restart

3. **Check logs:**
   ```bash
   python bots/run_grid.py examples/grid.yml
   ```
   - Look for "Insufficient balance" warnings
   - Look for "Only placed X/Y orders"

4. **Enable debug logging:**
   ```yaml
   # In config.yml
   debug_auth: true
   ```

---

## Testing Your Setup

### Test Authentication
```bash
# Quick test
python scripts/auth_check.py

# Comprehensive test (all signing variations)
python scripts/debug_auth.py
```

### Test Balance Requirements
```bash
python scripts/check_grid_balances.py examples/grid.yml
```

### Test Symbol Formats
```bash
python scripts/symbol_format_check.py
```

### Dry Run Mode
```bash
# Test ladder grid without real trades
python bots/run_grid.py examples/grid.yml --dry-run

# Test infinity grid without real trades
python bots/run_infinity_grid.py examples/infinity_grid.yml --dry-run
```

---

## Common Configuration Mistakes

### 1. Wrong Symbol Format
❌ **Wrong:**
```yaml
symbol: "COSA/USDT"  # NonKYC uses underscore
```

✅ **Correct:**
```yaml
symbol: "COSA_USDT"  # NonKYC format
```

### 2. Order Size Too Large
❌ **Problem:**
```yaml
base_order_size: "10000"  # Need 100,000+ COSA for 10 levels
```

✅ **Better:**
```yaml
base_order_size: "100"    # Need 1,000 COSA for 10 levels
```

### 3. Too Many Grid Levels
❌ **Problem:**
```yaml
n_buy_levels: 50    # Need massive balance
n_sell_levels: 50   # 100 orders total!
```

✅ **Better:**
```yaml
n_buy_levels: 5     # Start small
n_sell_levels: 5    # 10 orders total
```

### 4. Missing Credentials
❌ **Problem:**
```yaml
api_key: "${NONKYC_API_KEY}"  # Not set in environment
```

✅ **Fix:**
```bash
export NONKYC_API_KEY="your_key"
export NONKYC_API_SECRET="your_secret"
```

---

## Getting Help

### Check Documentation
1. `README.md` - General overview
2. `AUTHENTICATION_GUIDE.md` - Auth setup
3. `GRID_STRATEGIES_EXPLAINED.md` - Strategy differences
4. `SOLUTION_SUMMARY.md` - Recent fixes

### Debug Tools
- `scripts/auth_check.py` - Test authentication
- `scripts/debug_auth.py` - Comprehensive auth testing
- `scripts/check_grid_balances.py` - Balance diagnostics
- `scripts/symbol_format_check.py` - Symbol format testing

### Enable Debug Output
```yaml
# In config.yml
debug_auth: true  # WARNING: Shows sensitive data, development only!
```

```bash
# Or via environment
export NONKYC_DEBUG_AUTH=1
python bots/run_grid.py config.yml
```

---

## Quick Checklist

Before starting any bot:
- [ ] Credentials set and tested (`python scripts/auth_check.py`)
- [ ] IP whitelisted on NonKYC
- [ ] Balance sufficient (`python scripts/check_grid_balances.py`)
- [ ] Symbol format correct (use underscore: `COSA_USDT`)
- [ ] Order size reasonable for your balance
- [ ] Config file valid YAML syntax

---

## Summary

Most issues are:
1. **Insufficient balance** → Use `scripts/check_grid_balances.py`
2. **Authentication** → Use `scripts/debug_auth.py`
3. **Confusion about strategies** → Read `GRID_STRATEGIES_EXPLAINED.md`

**All bots are working correctly** - most "bugs" are actually configuration or balance issues! 🎯
