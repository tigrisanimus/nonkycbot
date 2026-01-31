# Hybrid Triangular Arbitrage Bot

A specialized arbitrage bot for nonkyc.io exchange that exploits price discrepancies between order books and liquidity pools.

## Overview

This bot identifies profitable arbitrage opportunities by combining:
- **Order book trades** (limit orders on COSA/USDT, COSA/BTC, PIRATE/USDT, PIRATE/BTC)
- **Liquidity pool swaps** (AMM swaps on COSA/PIRATE pool)

### Why This Works

Liquidity pools (AMMs) and order books price assets differently:
- **Order books**: Fixed prices from limit orders (best bid/ask)
- **Liquidity pools**: Dynamic pricing based on reserves (x * y = k formula)

Price discrepancies create arbitrage opportunities when:
1. Pool is undervalued vs. order books
2. Order books on different pairs are misaligned
3. Pool has low liquidity (high slippage) but profitable spread exists

## Quick Start

### 1. Monitor Mode (Recommended First Step)

```bash
# Just watch for opportunities without trading
python bots/run_hybrid_arb_bot.py examples/hybrid_arb.yml --monitor-only
```

This will:
- ✅ Check for profitable cycles every 2 seconds
- ✅ Log opportunities when found
- ✅ **NOT execute any trades**
- ✅ Show you if the strategy is viable

### 2. Dry Run Mode

```bash
# Simulate execution without real money
python bots/run_hybrid_arb_bot.py examples/hybrid_arb.yml --dry-run
```

This will:
- ✅ Execute the trading logic
- ✅ Log full cycle details
- ✅ **NOT place real orders**
- ✅ Test your configuration

### 3. Live Trading ⚠️

```bash
# REAL TRADING - USE WITH CAUTION
python bots/run_hybrid_arb_bot.py examples/hybrid_arb.yml
```

**WARNING**: This executes real trades with real money!

## Configuration

Edit `examples/hybrid_arb.yml`:

```yaml
# API credentials
api_key: "your_api_key_here"       # Optional if stored in keychain
api_secret: "your_api_secret_here" # Optional if stored in keychain

# Trading parameters
trade_amount: "100"      # Amount in USDT per cycle
min_profit_pct: "0.5"    # Minimum 0.5% profit to execute

# Order book pairs to monitor
orderbook_pairs:
  - "COSA/USDT"
  - "COSA/BTC"
  - "PIRATE/USDT"
  - "PIRATE/BTC"

# Liquidity pool
pool_pair: "COSA/PIRATE"
```

## How It Works

### The 4 Arbitrage Cycles

#### Cycle 1: USDT → COSA → PIRATE → USDT
```
1. Buy COSA with USDT on order book
2. Swap COSA for PIRATE in liquidity pool
3. Sell PIRATE for USDT on order book
```

#### Cycle 2: USDT → PIRATE → COSA → USDT
```
1. Buy PIRATE with USDT on order book
2. Swap PIRATE for COSA in liquidity pool
3. Sell COSA for USDT on order book
```

#### Cycle 3: BTC → COSA → PIRATE → BTC
```
1. Buy COSA with BTC on order book
2. Swap COSA for PIRATE in liquidity pool
3. Sell PIRATE for BTC on order book
```

#### Cycle 4: BTC → PIRATE → COSA → BTC
```
1. Buy PIRATE with BTC on order book
2. Swap PIRATE for COSA in liquidity pool
3. Sell COSA for BTC on order book
```

### Profitability Calculation

For each cycle, the bot calculates:

1. **Order book leg 1**: Price × (1 - taker_fee)
   - Taker fee: 0.2% (configurable)
2. **Pool swap leg**: AMM formula with slippage
   - Swap fee: 0.3% (configurable)
   - Slippage: Calculated from pool reserves
3. **Order book leg 3**: Price × (1 - taker_fee)
   - Taker fee: 0.2%

**Total fees**: ~0.7% minimum
**Required spread**: ~1.2%+ for profitable trade

### Example Profitable Opportunity

```
Starting amount: 100 USDT

Leg 1 (Order book): Buy COSA at 0.50 USDT/COSA
  Input:  100 USDT
  Output: 199.6 COSA (after 0.2% fee)

Leg 2 (Pool swap): Swap COSA → PIRATE
  Input:  199.6 COSA
  Output: 102.4 PIRATE (after 0.3% fee + slippage)

Leg 3 (Order book): Sell PIRATE at 1.02 USDT/PIRATE
  Input:  102.4 PIRATE
  Output: 104.25 USDT (after 0.2% fee)

Net profit: 4.25 USDT (4.25% profit)
```

## Features

### ✅ Implemented

- [x] Real-time price monitoring from order books
- [x] Liquidity pool data fetching
- [x] AMM pricing calculator with slippage
- [x] Cycle evaluation across 4 possible paths
- [x] Profitability calculation with fees
- [x] Monitor mode (no execution)
- [x] Dry run mode (simulated execution)
- [x] Live trading mode
- [x] Comprehensive logging

### ⚠️ Limitations / TODO

- [ ] **Partial fill handling**: Assumes orders fill immediately (risky!)
- [ ] **Pool API endpoints**: May need adjustment based on actual nonkyc.io API
- [ ] **Order reversal**: If a leg fails mid-cycle, manual intervention needed
- [ ] **Websocket support**: Currently polls REST API (slower)
- [ ] **Multi-threaded execution**: Sequential execution only
- [ ] **Position management**: No balance tracking across cycles

## Safety & Risk Management

### 🚨 Before Live Trading

1. **Run in monitor mode** for at least 24 hours
   - Verify opportunities exist
   - Check profit frequency
   - Validate calculations

2. **Check pool liquidity**
   ```bash
   # Example: Check if pool has enough reserves
   python -c "from src.nonkyc_client.rest import RestClient; \
              from src.nonkyc_client.auth import ApiCredentials; \
              client = RestClient('https://api.nonkyc.io/api/v2', ApiCredentials('key', 'secret')); \
              print(client.get_liquidity_pool('COSA/PIRATE'))"
   ```

3. **Start with small amounts**
   - Set `trade_amount: "10"` or less
   - Increase gradually after successful cycles

4. **Monitor execution**
   - Watch logs in real-time
   - Have a kill switch ready (Ctrl+C)
   - Check balances after each cycle

### Risk Factors

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Partial fills** | Stuck in incomplete cycle | Use small amounts, monitor fills |
| **Pool slippage** | Lower profit than expected | Calculate slippage from reserves |
| **Network latency** | Opportunity disappears | Use fast network, low poll interval |
| **API errors** | Failed execution | Retry logic, error handling |
| **Fee changes** | Profit calculation wrong | Update config when fees change |
| **Low liquidity** | Can't exit position | Check reserves before trading |

## Monitoring & Statistics

The bot logs statistics periodically:

```
INFO: Stats: 200 cycles evaluated, 5 opportunities, 2 executed, total profit: 8.45
```

- **Cycles evaluated**: Total number of cycles checked
- **Opportunities**: Cycles above min profit threshold
- **Executed**: Cycles actually traded (live mode only)
- **Total profit**: Cumulative profit/loss

## Troubleshooting

### No Opportunities Found

```
INFO: Best cycle: COSA/USDT>COSA/PIRATE>PIRATE/USDT | Profit: -2.1500 (-2.150%) [Below threshold]
```

**Possible causes:**
1. Fees too high relative to spread
2. Pool prices aligned with order books
3. `min_profit_pct` threshold too high

**Solutions:**
- Lower `min_profit_pct` to see marginal opportunities
- Increase `trade_amount` (reduces relative fee impact)
- Wait for more volatile market conditions

### Pool Data Errors

```
WARNING: Failed to fetch pool data for COSA/PIRATE: HTTP error 404
```

**Possible causes:**
1. Pool doesn't exist or is delisted
2. API endpoint path incorrect
3. Pool symbol format wrong

**Solutions:**
- Verify pool exists on nonkyc.io exchange
- Check API documentation for correct endpoint
- Try alternative symbols (e.g., "PIRATE/COSA" instead of "COSA/PIRATE")

### Order Placement Fails

```
ERROR: Leg execution failed: HTTP error 400: Insufficient balance
```

**Possible causes:**
1. Insufficient balance for trade
2. Minimum notional not met
3. Order size below minimum

**Solutions:**
- Check your account balances
- Adjust `trade_amount` to meet minimums
- Review exchange trading rules

## Advanced Configuration

### Custom Fee Rates

If nonkyc.io has different fees:

```yaml
orderbook_fee: "0.001"  # 0.1% maker fee
pool_fee: "0.0025"      # 0.25% pool fee
```

### Multiple Base Currencies

To trade with both USDT and BTC:

```python
# Edit bots/run_hybrid_arb_bot.py:
# Change line ~280:
for base in [self.base_currency]:
# To:
for base in ["USDT", "BTC"]:
```

This will evaluate 8 cycles instead of 4.

### Adjust Poll Interval

For faster detection (higher API load):

```yaml
poll_interval_seconds: 0.5  # Check every 500ms
```

For lower API load:

```yaml
poll_interval_seconds: 5.0  # Check every 5 seconds
```

## Performance Tips

1. **Use WebSocket instead of REST** (not implemented yet)
   - Reduces latency
   - Real-time price updates

2. **Run on low-latency server**
   - Closer to exchange servers
   - AWS/GCP in same region

3. **Optimize trade size**
   - Larger trades = better relative fees
   - But more slippage in pools

4. **Monitor during volatile periods**
   - More price discrepancies
   - Higher profit potential

## Example Output

### Monitor Mode

```
INFO: Initialized HybridArbBot in MONITOR mode
INFO: Monitoring 4 order book pairs + 1 pool
INFO: Min profit threshold: 0.5%
INFO: Starting HybridArbBot...

DEBUG: COSA/USDT: bid=0.49500000, ask=0.50500000
DEBUG: COSA/BTC: bid=0.00001200, ask=0.00001250
DEBUG: PIRATE/USDT: bid=1.01000000, ask=1.02500000
DEBUG: PIRATE/BTC: bid=0.00002450, ask=0.00002500
DEBUG: COSA/PIRATE pool: reserves=(10000.0000, 5000.0000)

DEBUG: ✓ COSA/USDT>COSA/PIRATE>PIRATE/USDT: +0.8500 (+0.850%)
DEBUG: ✗ USDT>PIRATE/USDT>COSA/PIRATE>COSA/USDT: -1.2000 (-1.200%)
DEBUG: ✗ BTC>COSA/BTC>COSA/PIRATE>PIRATE/BTC: -0.3500 (-0.350%)
DEBUG: ✗ BTC>PIRATE/BTC>COSA/PIRATE>COSA/BTC: -0.7500 (-0.750%)

INFO: 🎯 OPPORTUNITY #1: COSA/USDT>COSA/PIRATE>PIRATE/USDT | Profit: 0.8500 (0.850%)
INFO: MONITOR MODE: Would execute cycle but skipping

INFO: Stats: 100 cycles evaluated, 12 opportunities, 0 executed, total profit: 0.0000
```

## Contributing

If you improve this bot, consider contributing:

1. Better pool API integration
2. Partial fill handling
3. WebSocket support
4. Multi-threaded execution
5. Backtesting framework

## Disclaimer

**This software is provided "as is" without warranty of any kind.**

- Cryptocurrency trading involves substantial risk
- Past performance does not guarantee future results
- The authors are not responsible for any financial losses
- Always test thoroughly before live trading
- Never trade more than you can afford to lose

## Support

For questions or issues:
1. Check the main README.md
2. Review `../audits/AUDIT_REPORT.md` for security considerations
3. Open an issue on GitHub

---

**Happy arbitraging! 🚀**
