# Grid Trading Strategies Explained

This bot includes **TWO different grid strategies** that work in very different ways:

---

## 1. Ladder Grid (run_grid.py)

### How It Works
- **Creates a ladder of open orders** at multiple price levels
- Orders **sit on the order book** waiting to be filled
- When an order fills, a new order is placed on the opposite side
- Multiple orders active simultaneously

### Example
```
Entry: BTC = $50,000

Creates these orders immediately:
SELL: $50,500 (1% above)
SELL: $51,000 (2% above)
SELL: $51,500 (3% above)
...
BUY:  $49,500 (1% below)
BUY:  $49,000 (2% below)
BUY:  $48,500 (3% below)
...
```

### What You'll See
✅ Multiple open orders on NonKYC order book
✅ Orders waiting to be filled by market movement
✅ When filled, new order placed on opposite side

### Best For
- **Range-bound markets** (sideways price action)
- Markets with high volatility
- Capturing bid-ask spread repeatedly

### Config File
`examples/grid_cosa_pirate.yml`

### Command
```bash
python run_grid.py examples/grid_cosa_pirate.yml
```

---

## 2. Infinity Grid (run_infinity_grid.py)

### How It Works
- **Rebalance-style strategy** (NO ladder of orders)
- Waits for price to move by `step_pct` from last rebalance
- **Only places order AFTER price moves**
- Single order per trigger
- Maintains constant base asset value

### Example
```
Entry: BTC = $50,000, you hold 1 BTC

Price: $50,000 → Wait, no action
Price: $50,500 (+1%) → SELL 0.0099 BTC to maintain $50k value
Price: $50,500 → Wait, no action (already rebalanced)
Price: $51,005 (+1%) → SELL more BTC to maintain $50k value
Price: $51,005 → Wait, no action
Price: $50,500 (-1%) → BUY BTC using quote to restore $50k value
```

### What You'll See
❌ NO standing orders on NonKYC order book
✅ Bot monitoring price every poll_interval
✅ Log: "No rebalance needed" (this is NORMAL!)
✅ Order placed only when price moves ≥ step_pct

### Best For
- **Trending markets** (bull markets especially)
- Unlimited upside potential
- Profit from consistent uptrends
- Lower exchange fees (fewer orders)

### Config File
`examples/infinity_grid.yml`

### Command
```bash
python run_infinity_grid.py examples/infinity_grid.yml
```

---

## Key Differences Summary

| Feature | Ladder Grid | Infinity Grid |
|---------|-------------|---------------|
| **Order placement** | Immediate (multiple orders) | Delayed (after price moves) |
| **Open orders** | Yes, many on order book | No standing orders |
| **Strategy type** | Passive (market fills you) | Active (you hit market) |
| **Frequency** | High (many fills) | Low (periodic rebalances) |
| **Best market** | Range-bound, choppy | Trending, bullish |
| **Upper limit** | Yes (defined levels) | No (unlimited upside) |
| **Balance needed** | Both base & quote | Mostly base + some quote |
| **Typical behavior** | 10-20 orders always open | "No rebalance needed" is normal |

---

## Why Infinity Grid Shows "No Rebalance Needed"

This is **CORRECT behavior!** The infinity grid:

1. Calculates if price moved ≥ `step_pct` from last rebalance
2. If NO: Returns "No rebalance needed" and waits
3. If YES: Places a single rebalance order
4. Updates last rebalance price
5. Repeats from step 1

### Example Log (Normal Operation)
```
Check #1
Price: 50000 (last rebalance: 50000)
Price change: +0.00% from last rebalance
✓ No rebalance needed

Check #2
Price: 50250 (last rebalance: 50000)
Price change: +0.50% from last rebalance
✓ No rebalance needed

Check #3
Price: 50505 (last rebalance: 50000)
Price change: +1.01% from last rebalance
🎯 REBALANCE TRIGGERED
  Reason: Price rose 1.01%, selling to maintain constant value
  Action: SELL 0.0099 BTC
  Price: 50505
✓ Order placed
```

This means the bot is **working perfectly** - it's just waiting for enough price movement!

---

## Which Strategy Should You Use?

### Use Ladder Grid If:
- ✅ Price oscillates in a range (sideways market)
- ✅ High volatility with frequent reversals
- ✅ You want to capture bid-ask spread repeatedly
- ✅ You have balanced inventory (both assets)
- ✅ You want many small profits

### Use Infinity Grid If:
- ✅ Price is trending upward (bull market)
- ✅ You expect sustained price increases
- ✅ You mostly hold base asset (e.g., holding BTC)
- ✅ You want fewer, larger profits
- ✅ You want to minimize exchange fees
- ✅ You want unlimited upside potential

---

## Testing Your Setup

### Test Ladder Grid
```bash
# Should see multiple orders created immediately
python run_grid.py examples/grid_cosa_pirate.yml

# Check order book on NonKYC - you should see your orders
```

### Test Infinity Grid
```bash
# Should see "No rebalance needed" (this is normal!)
python run_infinity_grid.py examples/infinity_grid.yml

# Wait for price to move by step_pct, then order will trigger
```

---

## Common Misconceptions

### ❌ "Infinity grid isn't placing orders"
✅ **Correct**: Infinity grid only places orders AFTER price moves. Seeing "No rebalance needed" means it's working correctly and waiting for a trigger.

### ❌ "Infinity grid is broken"
✅ **Correct**: It's a rebalance strategy, not a ladder strategy. No standing orders is expected behavior.

### ❌ "I need both bots running"
✅ **Correct**: Pick ONE strategy based on market conditions. Running both would conflict.

### ❌ "Infinity grid should have orders on the book"
✅ **Correct**: No, that's ladder grid. Infinity grid only creates orders when rebalancing is triggered.

---

## Configuration Examples

### Ladder Grid (grid_cosa_pirate.yml)
```yaml
symbol: "COSA_USDT"
step_pct: "0.01"           # 1% between levels
n_buy_levels: 10           # 10 buy orders
n_sell_levels: 10          # 10 sell orders
base_order_size: "1000"    # COSA per order

# Creates 20 orders immediately on startup
```

### Infinity Grid (infinity_grid.yml)
```yaml
trading_pair: "BTC_USDT"
step_pct: "0.01"           # Rebalance when price moves 1%
poll_interval_seconds: 60  # Check every 60 seconds

# Creates NO orders on startup
# Waits for 1% price movement, then rebalances
```

---

## Summary

- **Ladder Grid** = Many standing orders, passive, range-bound markets
- **Infinity Grid** = Reactive rebalances, active, trending markets

Both are working correctly - they're just fundamentally different strategies! 🎯
