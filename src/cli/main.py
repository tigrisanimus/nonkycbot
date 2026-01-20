"""CLI entry point for nonkyc bot."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

from engine.grid_runner import run_grid
from engine.state import EngineState
from strategies import (
    grid_describe,
    infinity_grid_describe,
    profit_reinvest_describe,
    rebalance_describe,
    triangular_arb_describe,
)
from utils.config_validator import ConfigValidationError, validate_config
from utils.logging_config import setup_logging

LOGGER = logging.getLogger("nonkyc_bot.cli")

STRATEGY_DESCRIPTIONS: dict[str, Callable[[], str]] = {
    "grid": grid_describe,
    "infinity_grid": infinity_grid_describe,
    "rebalance": rebalance_describe,
    "triangular_arb": triangular_arb_describe,
    "profit_reinvest": profit_reinvest_describe,
}

SUPPORTED_FORMATS = (".json", ".toml", ".yaml", ".yml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="nonkyc bot CLI")
    parser.add_argument("--version", action="version", version="nonkyc-bot 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser(
        "start", help="Start a strategy with a config file."
    )
    start_parser.add_argument(
        "--strategy", required=True, help="Strategy name to start."
    )
    start_parser.add_argument(
        "--config", required=True, help="Path to JSON/TOML/YAML config file."
    )
    start_parser.add_argument(
        "--config-dir",
        help="Directory to store instance state/config overrides (defaults to config file directory).",
    )
    start_parser.add_argument(
        "--instance-id",
        default="default",
        help="Instance identifier for multi-instance runs.",
    )
    start_parser.add_argument(
        "--pid-file",
        help="Optional PID file to prevent duplicate starts for the same instance.",
    )
    start_parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    start_parser.set_defaults(handler=run_start)

    grid_parser = subparsers.add_parser(
        "start_grid", help="Start the grid trading bot."
    )
    grid_parser.add_argument(
        "--config", required=True, help="Path to JSON/TOML/YAML config file."
    )
    grid_parser.add_argument(
        "--state-path",
        help="Optional path to state.json (defaults to config file directory).",
    )
    grid_parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    grid_parser.set_defaults(handler=run_start_grid)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "handler"):
        return args.handler(args)
    parser.print_help()
    return 1


def run_start(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    try:
        strategy_name = args.strategy.strip()
        validate_strategy(strategy_name)
        config_path = Path(args.config).expanduser()
        config = load_config(config_path)

        # Validate configuration for the specified strategy
        try:
            validate_config(config, strategy_name)
        except ConfigValidationError as exc:
            LOGGER.error("Configuration validation failed: %s", exc)
            return 2

        config_dir = resolve_config_dir(args.config_dir, config_path)
        instance_id = normalize_instance_id(args.instance_id)
        instance_dir = prepare_instance_dir(config_dir, instance_id)
        state_path = instance_dir / "state.json"
        pid_file = Path(args.pid_file).expanduser() if args.pid_file else None
        if pid_file:
            ensure_pid_file(pid_file)

        state = EngineState(config=config)
        state.mark_running()
        state.save(state_path)

        LOGGER.info("Starting nonkyc bot")
        LOGGER.info("Strategy: %s", strategy_name)
        LOGGER.info("Strategy description: %s", STRATEGY_DESCRIPTIONS[strategy_name]())
        LOGGER.info("Config file: %s", config_path)
        LOGGER.info("Config directory: %s", config_dir)
        LOGGER.info("Instance: %s", instance_id)
        LOGGER.info("Instance directory: %s", instance_dir)
        LOGGER.info("State file: %s", state_path)
        if pid_file:
            LOGGER.info("PID file: %s", pid_file)
        LOGGER.info("Loaded config keys: %s", sorted(config.keys()))
        LOGGER.info(
            "Startup complete. Use --config-dir or --instance-id for parallel instances.",
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        LOGGER.error(str(exc))
        return 2
    except Exception as exc:  # pragma: no cover - safeguard for unexpected issues.
        LOGGER.exception("Unexpected error during startup: %s", exc)
        return 3
    return 0


def run_start_grid(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    try:
        config_path = Path(args.config).expanduser()
        config = load_config(config_path)
        state_path = (
            Path(args.state_path).expanduser()
            if args.state_path
            else config_path.parent / "state.json"
        )
        run_grid(config, state_path)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        LOGGER.error(str(exc))
        return 2
    except Exception as exc:  # pragma: no cover - safeguard for unexpected issues.
        LOGGER.exception("Unexpected error during grid bot startup: %s", exc)
        return 3
    return 0


def configure_logging(level: str) -> None:
    """Configure logging with sanitization and proper formatting."""
    setup_logging(level=level, sanitize=True, structured=False)


def validate_strategy(strategy_name: str) -> None:
    if not strategy_name:
        raise ValueError("Strategy name is required.")
    if strategy_name not in STRATEGY_DESCRIPTIONS:
        available = ", ".join(sorted(STRATEGY_DESCRIPTIONS))
        raise ValueError(
            f"Unknown strategy '{strategy_name}'. Available strategies: {available}."
        )


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Ensure the path is correct and readable."
        )
    suffix = config_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        supported = ", ".join(SUPPORTED_FORMATS)
        raise ValueError(
            f"Unsupported config format '{suffix}'. Supported formats: {supported}."
        )
    try:
        if suffix == ".json":
            data = json.loads(config_path.read_text(encoding="utf-8"))
        elif suffix == ".toml":
            data = load_toml(config_path)
        else:
            data = load_yaml(config_path)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in config file {config_path}: {exc}. Validate the file format."
        ) from exc
    except (RuntimeError, ValueError):
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse config file {config_path}: {exc}."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"Config file {config_path} must contain a JSON/TOML/YAML object mapping."
        )
    return data


def load_toml(config_path: Path) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib  # type: ignore[attr-defined]

        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    if importlib.util.find_spec("tomli") is None:
        raise RuntimeError(
            "TOML config parsing requires Python 3.11+ or the 'tomli' package. Install tomli or use JSON/YAML."
        )
    import tomli  # type: ignore[import-not-found]

    return tomli.loads(config_path.read_text(encoding="utf-8"))


def load_yaml(config_path: Path) -> dict[str, Any]:
    if importlib.util.find_spec("yaml") is None:
        raise RuntimeError(
            "YAML config parsing requires PyYAML. Install it with 'pip install pyyaml' or use JSON/TOML."
        )
    import yaml  # type: ignore[import-not-found]

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"YAML config file {config_path} must contain a mapping at the top level."
        )
    return data


def resolve_config_dir(config_dir: str | None, config_path: Path) -> Path:
    base = Path(config_dir).expanduser() if config_dir else config_path.parent
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_instance_id(instance_id: str) -> str:
    cleaned = instance_id.strip()
    if not cleaned:
        raise ValueError("Instance ID cannot be empty. Use --instance-id to set one.")
    if Path(cleaned).name != cleaned:
        raise ValueError(
            "Instance ID must be a simple name without path separators (e.g. 'bot-1')."
        )
    return cleaned


def prepare_instance_dir(config_dir: Path, instance_id: str) -> Path:
    instance_dir = config_dir / "instances" / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    return instance_dir


def ensure_pid_file(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    if pid_file.exists():
        existing_pid = pid_file.read_text(encoding="utf-8").strip()
        if existing_pid.isdigit() and is_pid_running(int(existing_pid)):
            raise RuntimeError(
                f"PID file {pid_file} already exists with running process {existing_pid}. "
                "Stop the existing instance or pass a different --pid-file."
            )
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    raise SystemExit(main())
