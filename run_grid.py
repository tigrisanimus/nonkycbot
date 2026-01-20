#!/usr/bin/env python
"""Grid trading bot runner with ladder behavior."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from engine.grid_runner import run_grid


def load_config(config_file: str) -> dict:
    with open(config_file, "r") as handle:
        return yaml.safe_load(handle)


def run_grid_from_file(config_file: str) -> None:
    config = load_config(config_file)
    state_path = Path(config.get("state_path", "state.json"))
    run_grid(config, state_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_grid.py <config_file>")
        sys.exit(1)
    config_path = sys.argv[1]
    if not os.path.exists(config_path):
        print(f"Error: Config file '{config_path}' not found.")
        sys.exit(1)
    run_grid_from_file(config_path)
