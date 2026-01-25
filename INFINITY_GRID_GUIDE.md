# Infinity Grid Bot - Complete Guide

## What is Infinity Grid?

An **infinity grid** is a grid trading bot with **unlimited upside** potential. Unlike a standard grid which has upper and lower bounds, an infinity grid:

- ✅ Has a **lower limit** (based on your USDT allocation)
- ✅ Has **NO upper limit** (extends infinitely as price rises)
- ✅ Profits continuously from upward price movement
- ✅ Perfect for bull markets and long-term holds

---

## How It Works

### Startup (Seeding the Grid)

When you start the bot, it places:
1. **Buy orders** below current price (down to lower limit)
2. **Sell orders** above current price (initial ladder)

```
Example at BTC = $90,000:
┌─────────────────────────────────
│ SELL: $99,000  (10% above)
│ SELL: $95,400  (6% above)
│ SELL: $91,800  (2% above)
├─────────────────────────────────  ← Current price: $90,000
│ BUY:  $88,200  (2% below)
│ BUY:  $84,600  (6% below)
│ BUY:  $81,000  (10% below) ← Lower limit
└─────────────────────────────────
```

### When Orders Fill

**When a BUY order fills:**
1. Bot bought BTC at a low price
2. → Place SELL order one step above to take profit

**When a SELL order fills:**
1. Bot sold BTC at a high price
2. → Place new SELL above highest (extend ladder upward)
3. → Place new BUY below that sell (to buy back)

This creates a **self-perpetuating cycle** that climbs with price!

### Example Cycle

```
1. Buy fills at $88,000
   → Place sell at $89,760 (2% above)

2. Sell fills at $89,760
   → Place new sell at $100,000 (extend upward)
   → Place new buy at $87,965 (buy back)

3. New buy fills at $87,965
   → Place sell at $89,724

And so on... forever upward! 🚀
```

---

## Configuration for Your Balance

### Calculate Your Order Size

**Formula:**
```
base_order_size = min(
    BTC_balance / initial_sell_levels,
    (USDT_balance / n_buy_levels) / BTC_price
)
```

### Example 1: Small Balance (You!)

Your balance:
- 0.00036516 BTC (~$33)
- 32.93542637 USDT
- BTC price: $90,000

**Recommended config:**
```yaml
n_buy_levels: 3                  # 3 buy orders
initial_sell_levels: 5           # 5 sell orders
base_order_size: "0.00006"       # ~$5.40 per order

# Calculation:
# BTC for sells: 0.00036516 / 5 = 0.000073 (use half for safety)
# USDT for buys: 32.93 / 3 / 90000 = 0.00012 (use half for safety)
# Use smaller: 0.00006 BTC per order
```

### Example 2: Medium Balance

Balance:
- 0.01 BTC (~$900)
- $500 USDT
- BTC price: $90,000

**Recommended config:**
```yaml
n_buy_levels: 5
initial_sell_levels: 8
base_order_size: "0.001"         # ~$90 per order

# BTC for sells: 0.01 / 8 = 0.00125
# USDT for buys: 500 / 5 / 90000 = 0.00111
# Use: 0.001 BTC per order
```

### Example 3: Large Balance

Balance:
- 0.1 BTC (~$9,000)
- $3,000 USDT
- BTC price: $90,000

**Recommended config:**
```yaml
n_buy_levels: 10
initial_sell_levels: 10
base_order_size: "0.01"          # ~$900 per order
```

---

## Full Config Template

```yaml
# Infinity Grid Configuration
symbol: "BTC_USDT"

# Grid spacing
step_pct: "0.02"                 # 2% between levels (adjust based on volatility)

# Order configuration
n_buy_levels: 5                  # Buy orders below (adjust to your USDT balance)
initial_sell_levels: 5           # Initial sell orders (adjust to your BTC balance)
base_order_size: "0.0001"        # Size per order (see calculation above)

# Exchange requirements
min_notional_quote: "1.0"        # $1 minimum order
total_fee_rate: "0.002"          # 0.2% fees
fee_buffer_pct: "0.0001"         # 0.01% safety buffer

# Market precision
tick_size: "0.01"                # Price precision
step_size: "0.00000001"          # Quantity precision (8 decimals for BTC)

# Timing
poll_interval_sec: 60            # Check every 60 seconds
reconcile_interval_sec: 60       # Reconcile every 60 seconds

# REST API
rest_timeout_sec: 30.0
rest_retries: 3

# State file
state_path: "infinity_grid_state.json"
```

---

## Timing, Fill Detection, and Troubleshooting

### How cadence works

- `poll_interval_sec` controls how often the bot polls order status for fills.
- `reconcile_interval_sec` controls how often it refreshes the open-order snapshot.
- The **lower** of the two effectively sets the fill-monitoring cadence. If both are
  60 seconds, fills are typically noticed within ~1 minute.

**Typical values:** 30–120 seconds. Lower values detect fills faster but increase API
usage and can surface rate-limit errors on busy accounts.

### If fills aren’t detected promptly

1. **Reduce the cadence** (e.g., set both to 30–45 seconds) and watch logs for more
   frequent fill checks.
2. **Confirm open orders are refreshing** by ensuring `reconcile_interval_sec` is not
   much higher than `poll_interval_sec`.
3. **Watch for REST backoff or timeout logs.** If you see frequent retries, increase
   `rest_timeout_sec` or `rest_retries`, or raise the intervals to reduce load.
4. **Verify exchange-side fills** by checking the NonKYC order history to ensure the
   order actually filled (helpful when network latency or intermittent REST errors occur).

---

## Lower Limit Behavior

The **lower limit** is the lowest buy order price, calculated from your USDT allocation.

### What Happens at Lower Limit?

**Scenario:** Price drops to lower limit and all buy orders fill.

```
Result:
- All your USDT is now converted to BTC
- No more buy orders can be placed (no USDT left)
- Sell orders continue to extend upward
- If price rises and sells fill, profits accumulate in USDT
```

### Can Lower Limit Adjust?

**Question:** Should the bot lower its lower limit as it earns USDT profit?

**Answer:** This is RISKY but possible:

**Pros:**
- Bot can buy even more BTC at lower prices
- Maximizes profit from dips
- Uses earned profit productively

**Cons:**
- You might not want to reinvest ALL profits automatically
- Could expose you to more downside risk
- You may want to withdraw profits instead

**Recommendation:**
- For now, keep lower limit FIXED
- Manually adjust if you want to add more USDT
- Add a config option later: `reinvest_profits: true/false`

---

## Step Percentage Guide

Choose `step_pct` based on BTC volatility:

| Volatility | step_pct | Description |
|-----------|----------|-------------|
| **Low** (sideways) | 0.005 (0.5%) | Tight grid, frequent fills |
| **Medium** | 0.01 (1%) | Balanced approach |
| **High** (trending) | 0.02 (2%) | Wide grid, fewer fills |
| **Very High** | 0.05 (5%) | Very wide, major moves only |

**Important:** Must be > minimum profitable step (~0.42% for 0.2% fees)

---

## Expected Behavior

### On Startup

```
INFO: Seeding infinity grid: entry=90000, 5 buy levels (down to 81450),
      5 initial sell levels (up to 99225).
      Balances: 0.00036516 BTC, 32.93542637 USDT
INFO: ✓ Successfully placed all 10 orders
```

You should see:
- 5 buy orders on NonKYC order book
- 5 sell orders on NonKYC order book

### During Operation

**Price goes UP (sell fills):**
```
INFO: Order filled: SELL 0.00006 @ 92000
INFO: Extended sell ladder to 101000 (no upper limit!)
INFO: Sell filled at 92000, placed buy-back at 90160
```

**Price goes DOWN (buy fills):**
```
INFO: Order filled: BUY 0.00006 @ 88000
INFO: Buy filled at 88000, placed sell at 89760
```

### What You Should See on Exchange

On NonKYC order book:
- ✅ Multiple buy orders below current price
- ✅ Multiple sell orders above current price
- ✅ Orders appear immediately on startup
- ✅ New orders added as old ones fill

---

## Troubleshooting

### "Insufficient balance" on Startup

**Problem:** Bot can't place orders

**Solution:**
```yaml
# Reduce order size
base_order_size: "0.00003"  # Make smaller

# Or reduce number of levels
n_buy_levels: 3
initial_sell_levels: 3
```

### "Only placed 0/10 orders"

**Problem:** Order size too large for balance

**Calculation:**
```
Your USDT: $33
Needed per buy order: $90 (0.001 BTC * $90k)
Result: Can't afford even one order!

Fix: Use 0.0001 BTC or smaller
```

### "Grid spacing too small to be profitable"

**Problem:** `step_pct` < 0.42%

**Solution:**
```yaml
step_pct: "0.01"  # Use 1% or higher
```

### No Orders Appearing

**Check:**
1. View NonKYC order book - orders should be there
2. Check bot logs for "Successfully placed all X orders"
3. Verify balance is sufficient
4. Check `state.json` for `open_orders`

---

## Summary

### Quick Setup for Your Balance

For **0.00036516 BTC + $33 USDT**:

```yaml
symbol: "BTC_USDT"
step_pct: "0.02"                # 2% spacing
n_buy_levels: 3                 # 3 buys
initial_sell_levels: 6          # 6 sells
base_order_size: "0.00006"      # $5.40 per order
min_notional_quote: "1.0"
total_fee_rate: "0.002"
tick_size: "0.01"
step_size: "0.00000001"
poll_interval_sec: 60
state_path: "infinity_grid_state.json"
```

**Run:**
```bash
python run_infinity_grid.py examples/infinity_grid.yml
```

**Expected result:**
- 3 buy orders placed (~$16 total USDT used)
- 6 sell orders placed (~0.00036 BTC used)
- Bot monitors and refills as orders execute
- Sell ladder extends infinitely upward 🚀

---

## Key Differences from Ladder Grid

| Feature | Ladder Grid | Infinity Grid |
|---------|-------------|---------------|
| Upper limit | Yes | NO (infinite!) |
| Lower limit | Yes | Yes |
| Best for | Range-bound | Uptrends |
| Buy fills → | Refill buy + place sell | Place sell only |
| Sell fills → | Refill sell + place buy | Extend upward + buy back |
| Profit potential | Bounded | Unlimited |

Use **Infinity Grid** when you believe price will trend upward long-term!
