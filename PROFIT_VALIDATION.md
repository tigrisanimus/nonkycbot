# Profit Validation System

All grid bots now include comprehensive profit validation to ensure orders are only placed when they will be profitable after fees.

---

## Overview

The profit validation system ensures:
- ✅ All orders will profit after exchange fees
- ✅ Grid spacing is wide enough to cover fees + buffer
- ✅ Orders meet minimum notional requirements
- ✅ Orders are rejected if they would lose money

---

## How It Works

### 1. Minimum Profitable Step Calculation

For any grid strategy, the minimum step percentage required to profit is calculated as:

```
min_step_pct = [(1 + fee_rate) / (1 - fee_rate - buffer)] - 1
```

**Example:**
- Fee rate: 0.2% (0.002)
- Buffer: 0.01% (0.0001)
- **Min step: ~0.42%**

This means:
- ✅ Grid with 0.5% step → Profitable
- ✅ Grid with 1.0% step → Profitable
- ❌ Grid with 0.3% step → Would lose money, rejected!

### 2. Order-Level Validation

Before placing each order, the bot validates:

**For Buy Orders:**
```python
# Will we profit when this buy fills and we sell one step above?
buy_price = 100.00
sell_price = 100.50  # One step up
fee_rate = 0.002

buy_cost = 100.00 * (1 + 0.002) = 100.20
sell_revenue = 100.50 * (1 - 0.002) = 100.299
profit = 100.299 - 100.20 = 0.099 ✅ Profitable!
```

**For Sell Orders:**
```python
# Did we buy low enough that this sell will profit?
buy_price = 99.50  # One step down
sell_price = 100.00
fee_rate = 0.002

buy_cost = 99.50 * (1 + 0.002) = 99.699
sell_revenue = 100.00 * (1 - 0.002) = 99.800
profit = 99.800 - 99.699 = 0.101 ✅ Profitable!
```

### 3. Minimum Notional Check

Every order must meet the exchange's minimum order value:

```python
notional_value = price * quantity
if notional_value < min_notional_quote:
    # Order rejected - too small
```

**Example:**
- Min notional: $1.00
- Order: 0.0001 BTC @ $10,000 = $1.00 ✅
- Order: 0.00005 BTC @ $10,000 = $0.50 ❌ Rejected

---

## Configuration

### Fee Settings

```yaml
# In your config.yml
total_fee_rate: "0.002"      # 0.2% total (maker + taker)
fee_buffer_pct: "0.0001"     # 0.01% safety buffer
min_notional_quote: "1.0"    # $1 minimum order value
```

### Grid Spacing

The bot will automatically validate your grid spacing on startup:

```yaml
step_pct: "0.01"  # 1% spacing

# On startup, bot checks:
# min_profitable_step = 0.42%
# your step_pct = 1.0%
# ✅ 1.0% > 0.42% → Profitable, bot starts

step_pct: "0.003"  # 0.3% spacing
# ❌ 0.3% < 0.42% → Would lose money, bot refuses to start!
```

---

## What Happens When Orders Are Rejected

### Startup Validation

If grid spacing is too small, the bot will refuse to start:

```
ValueError: Grid spacing too small to be profitable after fees:
step_pct=0.30% < min_profitable_step=0.42%
(fee_rate=0.20%, buffer=0.01%)
```

**Solution:** Increase `step_pct` in your config.

### Runtime Validation

If an individual order would be unprofitable, it's skipped with a warning:

```
WARNING: Skipping unprofitable order: Buy at 100.00 with sell at 100.30
would lose money after fees. Min profitable sell: 100.42.
Grid spacing may be too small.
```

**Solution:**
1. Check if you manually adjusted prices
2. Increase grid spacing
3. Review fee configuration

### Minimum Notional Rejection

```
WARNING: Skipping unprofitable order: Order below minimum notional:
0.50 < 1.0
```

**Solution:** Increase `base_order_size` in your config.

---

## Validation Functions

The `src/utils/profit_calculator.py` module provides:

### calculate_min_profitable_sell_price()
Given a buy price, calculates minimum sell price to break even.

### calculate_grid_profit()
Calculates exact profit from a complete grid cycle (buy → sell).

### is_profitable_grid_level()
Checks if a buy/sell pair will be profitable.

### calculate_min_profitable_step_pct()
Calculates minimum grid spacing percentage.

### validate_order_profitability()
Comprehensive validation before placing any order.

### meets_min_notional()
Checks if order meets minimum value requirement.

---

## Real-World Examples

### Example 1: BTC Grid

```yaml
symbol: "BTC_USDT"
step_pct: "0.01"             # 1% spacing
base_order_size: "0.001"     # 0.001 BTC per order
total_fee_rate: "0.002"      # 0.2% total fees
fee_buffer_pct: "0.0001"     # 0.01% buffer
min_notional_quote: "1.0"    # $1 minimum

# At BTC = $50,000:
# Min profitable step: 0.42%
# Your step: 1.0% ✅
# Order size: 0.001 BTC * $50,000 = $50 ✅
# Profit per cycle: ~$500 * 0.006 = ~$3
```

### Example 2: ALT Grid (Low Price)

```yaml
symbol: "COSA_USDT"
step_pct: "0.01"             # 1% spacing
base_order_size: "1000"      # 1000 COSA per order
total_fee_rate: "0.002"
min_notional_quote: "1.0"

# At COSA = $0.50:
# Min profitable step: 0.42%
# Your step: 1.0% ✅
# Order size: 1000 * $0.50 = $500 ✅
# Profit per cycle: ~$500 * 0.006 = ~$3
```

### Example 3: Too Small Grid (Rejected)

```yaml
step_pct: "0.003"  # 0.3% spacing
total_fee_rate: "0.002"

# Min profitable step: 0.42%
# Your step: 0.3% ❌
# ERROR: Grid spacing too small, bot refuses to start
```

---

## Profit Calculation Formula

For a complete grid cycle (buy then sell):

```
Buy Cost = buy_price * quantity * (1 + fee_rate)
Sell Revenue = sell_price * quantity * (1 - fee_rate)
Net Profit = Sell Revenue - Buy Cost

Must be positive!
```

**Worked Example:**
```
Buy: 1 BTC @ $50,000 with 0.2% fee
  Cost = $50,000 * 1 * 1.002 = $50,100

Sell: 1 BTC @ $50,500 with 0.2% fee
  Revenue = $50,500 * 1 * 0.998 = $50,399

Profit = $50,399 - $50,100 = $299 ✅
```

---

## Benefits

### Prevents Losses
- Never place orders that would lose money after fees
- Automatic rejection of unprofitable grid configurations

### Transparent
- Clear error messages explain why orders are rejected
- Shows exact minimum profitable prices

### Configurable
- Adjust fee rates for different exchanges
- Set safety buffer for extra protection
- Customize minimum notional requirements

### Reliable
- Validates on startup (fail fast)
- Validates each order (fail safe)
- Accounts for all fees (maker + taker)

---

## Troubleshooting

### "Grid spacing too small" Error

**Cause:** Your `step_pct` is smaller than minimum profitable step.

**Solution:**
```yaml
# Increase step_pct
step_pct: "0.01"  # Use 1% instead of 0.3%
```

### Orders Keep Getting Skipped

**Cause:** Individual orders failing profit validation.

**Check:**
1. Is grid spacing actually profitable?
2. Are fees configured correctly?
3. Did you manually adjust prices?

**Solution:** Review and increase `step_pct`.

### "Order below minimum notional" Warning

**Cause:** Order value (price * quantity) too small.

**Solution:**
```yaml
# Increase order size
base_order_size: "0.01"  # Larger orders
```

---

## Summary

All grid bots now automatically:
- ✅ Calculate minimum profitable grid spacing
- ✅ Validate each order before placement
- ✅ Ensure orders meet minimum notional
- ✅ Reject unprofitable orders with clear explanations
- ✅ Account for maker + taker fees + safety buffer

**No configuration needed** - validation works automatically with your existing fee settings!

Just ensure your `step_pct` is large enough to cover fees (typically > 0.42% for 0.2% total fees).
