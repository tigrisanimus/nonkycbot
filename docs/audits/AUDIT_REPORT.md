# Codebase Audit Report

**Date:** 2026-01-28
**Scope:** Full codebase audit of nonkycbot — security, correctness, and robustness
**Baseline:** 104 tests passing, all 104 still passing after fixes

---

## Bugs Fixed

### 1. `engine/balances.py` — Pending adjustments double-counted on reconciliation

**Severity:** High (financial correctness)

`Balances._reconcile()` applied pending fill adjustments to the fetched balance
but never cleared `pending_adjustments` afterward.  On the next fetch cycle the
same pending delta would be added again to the new exchange-reported value,
causing available balances to drift upward and potentially allowing orders the
account cannot actually cover.

**Fix:** Clear `pending_adjustments[asset]` after applying them during
reconciliation, matching the behavior of the "within tolerance" branch that
already cleared them.

### 2. `strategies/infinity_ladder_grid.py` — Cancelled orders treated as filled

**Severity:** High (financial correctness)

The `reconcile()` method included `"cancelled"` and `"Cancelled"` in the set of
statuses treated as filled orders.  When an order was cancelled (by the user, by
the exchange, or due to expiry), the strategy would:

- Place new opposing orders as if the cancelled order had actually executed
- Record phantom "profit" from sell cancellations
- Extend the sell ladder based on non-existent fills

**Fix:** Separated filled statuses (`filled`, `closed`, `partly filled`) from
cancelled statuses (`cancelled`, `canceled`, `rejected`, `expired`).  Cancelled
orders are now removed from tracking without triggering the fill/refill logic.

### 3. `strategies/infinity_ladder_grid.py` — Misleading profit tracking

**Severity:** Medium (reporting accuracy)

The profit tracking variable `total_profit_quote` recorded `quantity * price`
(i.e. gross sell revenue) as "profit", not the actual net profit after buy cost
and fees.  The log message also called it "Profit from sell".

**Fix:** Changed the log label to "Sell revenue" to accurately describe what the
counter tracks.  The counter itself still accumulates sell-side revenue since
individual buy costs aren't tracked per order in this strategy.

### 4. `utils/amm_pricing.py` — `estimate_optimal_trade_size` off by 100×

**Severity:** Medium (AMM trade sizing)

The function accepted `max_price_impact` as a decimal fraction (docstring:
"0.01 = 1%"), but then divided by 100 again internally.  This meant a
requested 1% max impact produced trade sizes appropriate for 0.01% impact —
100× too conservative.

**Fix:** Removed the erroneous `/ Decimal("100")` division.  Updated the test
to pass `Decimal("0.01")` instead of `Decimal("1.0")` to match the corrected
semantics.

### 5. `nonkyc_client/rest.py` — `cancel_all_orders_v1` missing transient error handling

**Severity:** Medium (resilience)

The `cancel_all_orders_v1` method caught `HTTPError` and `URLError` but did not
handle `TimeoutError`, `socket.timeout`, `http.client.RemoteDisconnected`,
`ConnectionResetError`, or `BrokenPipeError`.  The main `_send_once` method
correctly handled all of these.  A transient network issue during cancel-all
would raise an unhandled exception instead of a `TransientApiError`.

**Fix:** Added the missing exception handlers, consistent with `_send_once`.

### 6. `utils/logging_config.py` — `LogContext` not thread-safe

**Severity:** Medium (correctness under concurrency)

`LogContext.__enter__` called `logging.setLogRecordFactory()`, which mutates
global state.  If two threads used `LogContext` concurrently, they would
overwrite each other's factory and `__exit__` would restore the wrong one.

**Fix:** Added a class-level `threading.Lock` to serialise entry/exit of the
context manager across threads.

---

## Observations (No Code Changes)

### Security

- **HMAC authentication** is correctly implemented using SHA256 with constant-time
  nonce generation via 14-digit timestamps.
- **SSL verification** is enabled by default on both sync and async REST clients.
  Custom contexts and opt-out are supported for development.
- **Credential storage** properly supports OS keychain (via `keyring`), environment
  variables, and config-file fallback with `${VAR_NAME}` expansion.
- **Log sanitization** via `SanitizingFormatter` redacts known secret patterns.
  Note: the regex `rf"{pattern}['\"]?\s*[:=]\s*['\"]?[\w\-]+"` only matches
  single-token values — secrets containing spaces or special characters may leak.
  Consider using a more permissive pattern if secrets with non-word characters
  are possible.
- **State files** are written with default OS permissions.  On shared systems,
  trading state (order prices, quantities, strategy parameters) could be readable
  by other users.  Consider restricting file permissions via `os.umask` or
  explicit `chmod` if running in a multi-user environment.

### Architecture

- Clean protocol-based exchange client abstraction (`ExchangeClient`) makes
  testing with fakes straightforward.
- Strategy implementations properly validate profitability before placing orders.
- Config validation is comprehensive with strategy-specific validators.
- Rate limiting covers both sync and async paths with proper token-bucket
  implementation.

### Minor Notes

- `rest.py` `debug_auth` mode prints `data_to_sign` which contains the full
  signed URL.  This is documented as dev-only but worth noting.
- `infinity_ladder_grid.py` duplicates the `_split_symbol` static method that
  also exists in `adaptive_capped_martingale.py` and `balance_checker.py`.
  Consider extracting to a shared utility.
- The `fee_rate` parameter in `balance_checker.py:calculate_required_balance`
  applies fees to sell orders as `amount * (1 + fee_rate)`, but on most spot
  exchanges, sell fees are deducted from proceeds, not from the base quantity
  required.  This is conservative (over-estimates requirements) so it's safe,
  but could cause unnecessary order rejections in tight-balance scenarios.
