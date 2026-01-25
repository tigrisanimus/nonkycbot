# Infinity Grid Backup Snapshot

This folder contains a point-in-time backup of the current infinity grid bot
implementation. The files are copied from the live sources so we can quickly
reference or restore the working version if needed.

## Contents
- `run_infinity_grid.py.bak`: Runner CLI for the infinity grid bot.
- `infinity_ladder_grid.py.bak`: Strategy implementation with state handling,
  order placement, and reconciliation logic.

## Source of Truth
The active sources remain:
- `run_infinity_grid.py`
- `src/strategies/infinity_ladder_grid.py`

If you update the live implementation, refresh this backup to keep the snapshot
in sync.
