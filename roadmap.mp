# NonKYC Bot Roadmap

## Now
- [x] Initialize repository scaffold with core packages, CLI, and tests.
- [x] Add standard grid strategy placeholder.
- [x] Implement infinity grid helper module with deterministic refresh logic.
- [x] Implement rebalance helper module for target ratio adjustments.
- [x] Implement triangular arbitrage helper module for cycle scanning.
- [x] Implement profit reinvest helper module for reserve allocation.
- [x] Add CLI start command with strategy config parsing and multi-instance support.
- [x] Add deterministic REST/WS, order manager, and strategy tests.
- [x] Document 401 Unauthorized troubleshooting and API auth guidance.
- [x] Clarify 401 guidance for private endpoint permission checks.
- [x] Add remediation step for regenerating API credentials when 401 persists.
- [x] Add optional auth debug output for troubleshooting signature mismatches.
- [x] Note debug output includes headers for signature verification (handle logs carefully).

## Next
- [ ] Define API client interfaces and error handling.
- [ ] Implement persistent configuration and secrets management.
- [ ] Add strategy configuration schemas.

## Later
- [ ] Add exchange-specific adapters.
- [ ] Add backtesting harness.
