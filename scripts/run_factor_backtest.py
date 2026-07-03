#!/usr/bin/env python3
"""Run the backtest workflow on user-provided factor and market data."""

from __future__ import annotations

import argparse
import ast
import configparser
import importlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = SKILL_ROOT / "scripts" / "backtest_engine"
CONFIG_PATH = SKILL_ROOT / "scripts" / "config" / "backtestconfig.ini"
DEFAULT_TEST_ROOT = SKILL_ROOT / "data" / "test_data"
DEFAULT_OUTPUT_ROOT = SKILL_ROOT / "output"
DEFAULT_STRATEGY = "long_only_equal_weight"


@contextmanager
def pushd(path: Path):
    previous_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


def _parse_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return raw


def _parse_overrides(pairs: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Override must be key=value, got: {pair}")
        key, raw_value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Override key is empty in: {pair}")
        overrides[key] = _parse_value(raw_value.strip())
    return overrides


def _enable_pandas_week_compat() -> None:
    if not hasattr(pd.DatetimeIndex, "week"):
        pd.DatetimeIndex.week = property(lambda self: self.isocalendar().week.to_numpy())  # type: ignore[attr-defined]


def _load_test_manifest(test_root: Path) -> dict[str, str]:
    manifest_path = test_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Test data manifest not found: {manifest_path}. "
            "Run scripts/make_test_data.py only when intentionally refreshing the checked-in test fixture."
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _resolve_manifest_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (SKILL_ROOT / path).resolve()


def _default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = DEFAULT_OUTPUT_ROOT / f"run_{timestamp}"
    suffix = 1
    while candidate.exists():
        candidate = DEFAULT_OUTPUT_ROOT / f"run_{timestamp}_{suffix:02d}"
        suffix += 1
    return candidate


def _load_strategy_args(strategy_name: str) -> dict[str, Any]:
    config = configparser.ConfigParser()
    config.optionxform = lambda option: option
    config.read(CONFIG_PATH, encoding="utf-8")
    if strategy_name not in config:
        available = ", ".join(config.sections())
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available strategies: {available}")
    return {key: _parse_value(value.strip()) for key, value in config[strategy_name].items()}


def _resolve_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.test_data:
        manifest = _load_test_manifest(args.test_root)
        args.input_file = _resolve_manifest_path(manifest["factor_file"])
        args.factor_column = manifest["factor_column"]
        args.data_root = _resolve_manifest_path(manifest["data_root"])
        args.timespan = [int(manifest["start_date"]), int(manifest["end_date"])]
        args.override = list(args.override) + ["longx=5", f"benchmark={manifest['benchmark']}"]
        if args.report_insample_last_day is None:
            args.report_insample_last_day = int(manifest.get("report_insample_last_day", "20241231"))
        if args.report_outsample_last_day is None:
            args.report_outsample_last_day = int(manifest.get("report_outsample_last_day", "20260123"))

    missing = []
    for attr in ["input_file", "factor_column", "data_root"]:
        if getattr(args, attr) in (None, ""):
            missing.append(f"--{attr.replace('_', '-')}")
    if missing:
        raise ValueError(
            "Missing required user-data arguments: "
            f"{', '.join(missing)}. Provide --input-file, --factor-column, and --data-root, "
            "or explicitly pass --test-data to run the checked-in test fixture."
        )

    args.input_file = Path(args.input_file).resolve()
    args.data_root = Path(args.data_root).resolve()
    if not args.input_file.exists():
        raise FileNotFoundError(f"Factor input does not exist: {args.input_file}")
    if not args.data_root.exists():
        raise FileNotFoundError(f"Market data root does not exist: {args.data_root}")
    args.output_dir = Path(args.output_dir or _default_output_dir()).resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.optimizer_root is not None:
        args.optimizer_root = Path(args.optimizer_root).resolve()
    return args


def _expected_outputs(savemode: int, pure_alpha: bool) -> list[str]:
    expected = ["ICs.csv", "group_ret.csv", "group_return.png", "winrate.png"]
    if savemode != 0:
        expected.append("Pnl.png")
    if savemode >= 2:
        expected.append("stats.csv")
    if savemode == 3:
        expected.extend(["transaction.csv", "holdings.csv"])
    if pure_alpha:
        expected.extend(["Explo.csv", "Explo_return.csv", "Pure_alpha.png"])
    return expected


def run_factor_backtest(args: argparse.Namespace) -> dict[str, Any]:
    args = _resolve_args(args)
    _enable_pandas_week_compat()

    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))

    with pushd(ENGINE_DIR):
        backtest_module = importlib.import_module("BackTest")

        backtest_module.BASE_PATH = str(args.data_root)
        backtest_module.OPT_PATH = str(args.optimizer_root or args.data_root)

        strategy_args = _load_strategy_args(args.strategy)
        strategy_args.update(_parse_overrides(args.override))

        system = backtest_module.TradingSystem(
            str(args.input_file),
            args.factor_column,
            str(args.output_dir),
            args.savemode,
            args.timespan or [],
            **strategy_args,
            init_cash=args.init_cash,
            pure_alpha=args.pure_alpha,
            addtwap=True,
            reverse=args.reverse,
        )
        system.run()

    expected = _expected_outputs(args.savemode, args.pure_alpha)
    missing = [name for name in expected if not (args.output_dir / name).exists()]
    if missing:
        raise RuntimeError(f"Backtest finished but expected outputs are missing: {missing}")

    summary: dict[str, Any] = {
        "input_file": str(args.input_file),
        "factor_column": args.factor_column,
        "data_root": str(args.data_root),
        "output_dir": str(args.output_dir),
        "expected_outputs": expected,
    }
    if args.report:
        scripts_dir = Path(__file__).resolve().parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        report_module = importlib.import_module("generate_factor_report")
        report_pdf = report_module.generate_report(
            args.output_dir,
            args.factor_column,
            args.input_file,
            data_root=args.data_root,
            stock_price_daily=args.report_stock_price_daily,
            comparison_factor_dir=args.report_comparison_factor_dir,
            comparison_backtest_dir=args.report_comparison_backtest_dir,
            mkt_data_path=args.report_mkt_data_path,
            stock_folder=args.report_stock_folder,
            alpha_folder=args.report_alpha_folder,
            barra_folder=args.report_barra_folder,
            reverse=args.reverse,
            insample_last_day=args.report_insample_last_day or 20241231,
            outsample_last_day=args.report_outsample_last_day or 20260123,
        )
        summary["report_pdf"] = str(report_pdf)
    stats_path = args.output_dir / "stats.csv"
    if stats_path.exists():
        stats = pd.read_csv(stats_path)
        summary["stats_rows"] = int(len(stats))
        for col in ["unrealized_pnl", "hedged_unrealized_pnl", "MaxDrawdown"]:
            if col in stats.columns and len(stats):
                summary[f"last_{col}"] = float(stats[col].iloc[-1])
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a cross-sectional factor backtest.")
    parser.add_argument("--test-data", action="store_true", help="Explicitly run the checked-in test fixture.")
    parser.add_argument("--test-root", type=Path, default=DEFAULT_TEST_ROOT)
    parser.add_argument("--input-file", type=Path, help="Factor CSV, Parquet file, or directory.")
    parser.add_argument("--factor-column", help="Column name containing factor values.")
    parser.add_argument("--data-root", type=Path, help="Parquet market data root.")
    parser.add_argument("--optimizer-root", type=Path, help="Optimizer or attribution data root.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated backtest outputs. Defaults to output/run_YYYYMMDD_HHMMSS/.",
    )
    parser.add_argument("--timespan", nargs=2, type=int, metavar=("START", "END"), help="Inclusive factor-date range.")
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY, help="Section in scripts/config/backtestconfig.ini.")
    parser.add_argument("--savemode", type=int, default=3, choices=[0, 1, 2, 3])
    parser.add_argument("--init-cash", type=float, default=1e8)
    parser.add_argument("--override", action="append", default=[], help="Override strategy arg as key=value.")
    parser.add_argument("--reverse", action="store_true", help="Reverse factor direction.")
    parser.add_argument("--pure-alpha", action="store_true", help="Run pure alpha attribution; requires optimizer/attribution data.")
    parser.add_argument("--report", action="store_true", help="Generate a PDF report after the backtest.")
    parser.add_argument("--report-stock-price-daily", type=Path, help="CSV with ticker, tradeDate, openPrice.")
    parser.add_argument("--report-comparison-factor-dir", type=Path, help="Optional factor library directory.")
    parser.add_argument("--report-comparison-backtest-dir", type=Path, help="Optional backtest result directory.")
    parser.add_argument("--report-mkt-data-path", type=Path, help="Market daily data path for report diagnostics.")
    parser.add_argument("--report-stock-folder", type=Path, help="Stock daily data folder for pure factor return.")
    parser.add_argument("--report-alpha-folder", type=Path, help="Alpha factor folder for pure factor return.")
    parser.add_argument("--report-barra-folder", type=Path, help="Barra exposure folder for pure factor return.")
    parser.add_argument("--report-insample-last-day", type=int)
    parser.add_argument("--report-outsample-last-day", type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        summary = run_factor_backtest(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
