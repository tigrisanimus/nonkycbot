#!/usr/bin/env python
"""Fill-driven ladder grid bot runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from engine.ladder_runner import run_ladder_grid


def load_config(config_file: str) -> dict:
    with open(config_file, "r") as handle:
        return yaml.safe_load(handle)


def run_ladder_grid_from_file(config_file: str) -> None:
    config = load_config(config_file)
    state_path = Path(config.get("state_path", "state.json"))
    run_ladder_grid(config, state_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_grid_bot.py <config_file>")
        sys.exit(1)
    config_path = sys.argv[1]
    if not os.path.exists(config_path):
        print(f"Error: Config file '{config_path}' not found.")
        sys.exit(1)
    run_ladder_grid_from_file(config_path)
