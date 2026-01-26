#!/usr/bin/env python
"""Adaptive capped martingale bot runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from engine.adaptive_capped_martingale_runner import run_adaptive_capped_martingale


def load_config(config_file: str) -> dict:
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Config file '{config_file}' not found.")
    with open(config_file, "r") as handle:
        return yaml.safe_load(handle)


def run_from_file(config_file: str) -> None:
    config = load_config(config_file)
    state_path = Path(config.get("state_path", "state.json"))
    run_adaptive_capped_martingale(config, state_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_adaptive_capped_martingale.py <config_file>")
        sys.exit(1)
    run_from_file(sys.argv[1])
