# Grid Spacing Guide - Finding Your Optimal Settings

## Understanding Grid Spacing

Grid spacing determines how far apart your buy and sell orders are. Tighter spacing = more orders = more frequent fills.

---

## Minimum Spacing for Profitability

With NonKYC fees (0.2% total):

**Absolute minimum:** 0.42%
**Recommended minimum:** 0.5% (includes safety margin)

### Why 0.42%?

```
Buy cost = $100 * 1.002 = $100.20 (including 0.2% fee)
Sell revenue = $100.42 * 0.998 = $100.239 (after 0.2% fee)
Profit = $100.239 - $100.20 = $0.039 ✅

With 0.41% spacing:
Sell revenue = $100.41 * 0.998 = $100.209
Profit = $100.209 - $100.20 = $0.009 (too risky!)

With 0.5% spacing (safer):
Sell revenue = $100.50 * 0.998 = $100.299
Profit = $100.299 - $100.20 = $0.099 ✅ Better!
```

---

## Spacing Options for Your Balance

For **0.00036 BTC + $33 USDT** at BTC = $90,000:

### Option 1: TIGHTEST (0.5% spacing)

```yaml
step_pct: "0.005"               # 0.5%
n_buy_levels: 15
initial_sell_levels: 20
base_order_size: "0.000012"     # $1.08 per order

Grid range: $83,500 - $99,400
Total orders: 35 orders
Profit per cycle: ~$0.005 per $1 trade
```

**Pros:**
- Maximum profit opportunities
- Catches tiny price movements
- More fills = faster compounding

**Cons:**
- Many API calls (rate limit risk)
- Small profit per trade
- Requires active monitoring
- More exchange fees total

**Best for:** High volatility, active traders

---

### Option 2: TIGHT (1% spacing)

```yaml
step_pct: "0.01"                # 1%
n_buy_levels: 8
initial_sell_levels: 10
base_order_size: "0.000025"     # $2.25 per order

Grid range: $82,800 - $99,400
Total orders: 18 orders
Profit per cycle: ~$0.011 per $2.25 trade
```

**Pros:**
- Good balance of frequency vs profit
- Fewer API calls
- Moderate monitoring required

**Cons:**
- Misses very small moves
- Moderate profit per trade

**Best for:** Moderate volatility, semi-active traders

---

### Option 3: MEDIUM (2% spacing) **← RECOMMENDED**

```yaml
step_pct: "0.02"                # 2%
n_buy_levels: 3
initial_sell_levels: 6
base_order_size: "0.00006"      # $5.40 per order

Grid range: $84,300 - $101,300
Total orders: 9 orders
Profit per cycle: ~$0.054 per $5.40 trade
```

**Pros:**
- Larger profit per trade
- Fewer API calls
- Lower monitoring needs
- Works well for small balances

**Cons:**
- Misses small price movements
- Fewer profit opportunities

**Best for:** Normal volatility, passive traders, small balances

---

### Option 4: WIDE (5% spacing)

```yaml
step_pct: "0.05"                # 5%
n_buy_levels: 2
initial_sell_levels: 3
base_order_size: "0.00012"      # $10.80 per order

Grid range: $81,000 - $103,500
Total orders: 5 orders
Profit per cycle: ~$0.27 per $10.80 trade
```

**Pros:**
- Large profit per trade
- Very few API calls
- Minimal monitoring
- Good for trending markets

**Cons:**
- Misses most price movements
- Very few fills
- May sit idle for long periods

**Best for:** Low volatility, trending markets, hands-off trading

---

## Comparison Table

| Spacing | Orders | Profit/Trade | Fills/Day* | Total Daily Profit* | Monitoring | Risk |
|---------|--------|--------------|------------|---------------------|------------|------|
| 0.5% | 35 | $0.005 | 20 | $0.10 | High | Low |
| 1% | 18 | $0.011 | 10 | $0.11 | Medium | Low |
| 2% | 9 | $0.054 | 5 | $0.27 | Low | Medium |
| 5% | 5 | $0.27 | 2 | $0.54 | Very Low | High |

*Estimated for normal volatility (2-3% daily BTC movement)

---

## How to Choose

### High Volatility Markets (BTC moving 5%+ daily)
→ Use **0.5-1% spacing**
- Many opportunities to catch swings
- Profits add up from frequent fills

### Normal Volatility (2-3% daily)
→ Use **1-2% spacing**
- Balanced approach
- Catches most meaningful moves

### Low Volatility (<2% daily)
→ Use **2-5% spacing**
- Wait for significant moves
- Larger profit per trade

### Trending Markets (consistent up/down)
→ Use **2-5% spacing**
- Don't get filled out of position too early
- Ride the trend longer

---

## Maximum Grid Levels (Based on Min Notional)

With minimum $1 orders:

**At BTC = $50,000:**
- Min order: 0.00002 BTC
- Your 0.00036 BTC = 18 sell orders max
- Your $33 USDT = 33 buy orders max

**At BTC = $90,000:**
- Min order: 0.000011 BTC
- Your 0.00036 BTC = 33 sell orders max
- Your $33 USDT = 33 buy orders max

**At BTC = $100,000:**
- Min order: 0.00001 BTC
- Your 0.00036 BTC = 36 sell orders max
- Your $33 USDT = 33 buy orders max

---

## Rate Limit Considerations

NonKYC likely has rate limits. With tight grids:

**0.5% spacing (35 orders):**
- Startup: 35 order placements
- Per fill: 1 cancel + 2 new orders = 3 API calls
- If 10 fills/hour = 30 API calls/hour

**2% spacing (9 orders):**
- Startup: 9 order placements
- Per fill: 1 cancel + 2 new orders = 3 API calls
- If 5 fills/hour = 15 API calls/hour

**Recommendation:** Start with wider spacing, tighten gradually if no rate limit issues.

---

## Profit Examples (24-hour period)

### Scenario: BTC at $90,000, moves between $88,000 - $92,000

**0.5% spacing (35 orders):**
- Fills: ~20 orders
- Profit per fill: $0.005
- Total: $0.10

**1% spacing (18 orders):**
- Fills: ~10 orders
- Profit per fill: $0.011
- Total: $0.11

**2% spacing (9 orders):**
- Fills: ~5 orders
- Profit per fill: $0.054
- Total: $0.27

**5% spacing (5 orders):**
- Fills: ~2 orders
- Profit per fill: $0.27
- Total: $0.54

*These are rough estimates - actual results vary greatly with market conditions*

---

## My Recommendation for You

Based on your balance (0.00036 BTC + $33 USDT):

**Start with 2% spacing:**
```yaml
step_pct: "0.02"
n_buy_levels: 3
initial_sell_levels: 6
base_order_size: "0.00006"
```

**Why:**
- Not too aggressive (won't hit rate limits)
- Reasonable profit per trade ($0.05)
- Easy to monitor
- Won't exhaust balance too quickly
- Good for learning how infinity grid works

**After a week, consider:**
- If fills too rare → tighten to 1%
- If too many fills → widen to 3%
- If making consistent profit → add more balance and try tighter grid

---

## Formula for Custom Calculation

```python
# Calculate max grid levels for your balance
btc_balance = 0.00036516
usdt_balance = 32.93542637
btc_price = 90000

# Choose spacing
step_pct = 0.02  # 2%

# Calculate order size to fill grid
# Option 1: Based on sell levels wanted
sell_levels = 6
btc_per_sell = btc_balance / sell_levels
print(f"BTC per sell: {btc_per_sell}")  # 0.00006086

# Option 2: Based on buy levels wanted
buy_levels = 3
usdt_per_buy = usdt_balance / buy_levels
btc_per_buy = usdt_per_buy / btc_price
print(f"BTC per buy: {btc_per_buy}")    # 0.00012207

# Use smaller value for base_order_size
base_order_size = min(btc_per_sell, btc_per_buy)
print(f"Use: {base_order_size} BTC per order")
```

---

## Summary

- **Tightest possible:** 0.5% (0.005)
- **Recommended minimum:** 1% (0.01)
- **Best for small balance:** 2% (0.02)
- **Best for trending:** 5% (0.05)

All configurations are profitable - choose based on your trading style and market conditions!
