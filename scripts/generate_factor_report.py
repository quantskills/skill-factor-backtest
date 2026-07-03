#!/usr/bin/env python3
"""Generate a PDF factor report for a completed backtest run."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPORT_CODE_DIR = SKILL_ROOT / "scripts" / "factor_report_generate"


@contextmanager
def pushd(path: Path):
    previous_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


def _ensure_trailing_slash(path: Path) -> str:
    value = str(path.resolve())
    return value if value.endswith(os.sep) else value + os.sep


def _optional_dir(path: Path | None) -> str:
    if path is None:
        return ""
    return _ensure_trailing_slash(path)


def _make_stock_price_daily_from_backtest_data(data_root: Path, output_csv: Path) -> Path:
    open_price_path = data_root / "open_price.parquet"
    if not open_price_path.exists():
        raise FileNotFoundError(f"Missing open_price parquet for stock_price_daily: {open_price_path}")
    open_price = pd.read_parquet(open_price_path)
    rows = (
        open_price.rename_axis(index="date", columns="ticker")
        .reset_index()
        .melt(id_vars="date", var_name="ticker", value_name="openPrice")
    )
    rows = rows.dropna(subset=["openPrice"])
    rows["tradeDate"] = pd.to_datetime(rows["date"].astype(str)).dt.strftime("%Y-%m-%d")
    rows = rows[["ticker", "tradeDate", "openPrice"]]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output_csv)
    return output_csv


def _prepare_report_input_layout(run_dir: Path) -> None:
    group_ret_path = run_dir / "group_ret.csv"
    group_window_path = run_dir / "group_pnls" / "group_ret_window1.csv"
    if group_ret_path.exists() and not group_window_path.exists():
        group_window_path.parent.mkdir(parents=True, exist_ok=True)
        group_data = pd.read_csv(group_ret_path)
        group_data.to_csv(group_window_path, index=False)


def _import_existing_generator():
    if str(REPORT_CODE_DIR) not in sys.path:
        sys.path.insert(0, str(REPORT_CODE_DIR))
    with pushd(REPORT_CODE_DIR):
        try:
            return importlib.import_module("FacRepGene_v2")
        except ModuleNotFoundError as exc:
            if exc.name in {"LinearIndicator", "NonLinearIndicator", "PureFactorReturn"}:
                raise RuntimeError(
                    "Report generation requires the Python indicator modules "
                    f"LinearIndicator.py, NonLinearIndicator.py, and PureFactorReturn.py, but '{exc.name}' "
                    "could not be imported."
                ) from exc
            raise


def generate_report(
    run_dir: Path,
    factor_name: str,
    factor_file: Path,
    output_pdf: Path | None = None,
    *,
    data_root: Path | None = None,
    stock_price_daily: Path | None = None,
    comparison_factor_dir: Path | None = None,
    comparison_backtest_dir: Path | None = None,
    mkt_data_path: Path | None = None,
    stock_folder: Path | None = None,
    alpha_folder: Path | None = None,
    barra_folder: Path | None = None,
    reverse: bool = False,
    insample_last_day: int = 20241231,
    outsample_last_day: int = 20260123,
) -> Path:
    run_dir = run_dir.resolve()
    factor_file = factor_file.resolve()
    output_pdf = (output_pdf or (run_dir / f"{factor_name}_factor_report.pdf")).resolve()

    if stock_price_daily is None:
        if data_root is None:
            raise ValueError("Either --stock-price-daily or --data-root is required for the existing report generator.")
        stock_price_daily = _make_stock_price_daily_from_backtest_data(
            data_root.resolve(), run_dir / "_report_inputs" / "stock_price_daily.csv"
        )
    else:
        stock_price_daily = stock_price_daily.resolve()

    mkt_data_path = (mkt_data_path or (data_root or SKILL_ROOT / "data")).resolve()
    comparison_factor_dir = comparison_factor_dir.resolve() if comparison_factor_dir else None
    comparison_backtest_dir = comparison_backtest_dir.resolve() if comparison_backtest_dir else None
    stock_folder = stock_folder.resolve() if stock_folder else None
    alpha_folder = alpha_folder.resolve() if alpha_folder else None
    barra_folder = barra_folder.resolve() if barra_folder else None

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    _prepare_report_input_layout(run_dir)

    generator = _import_existing_generator()
    with pushd(REPORT_CODE_DIR):
        generator.get_report(
            _ensure_trailing_slash(run_dir),
            str(factor_file),
            _optional_dir(comparison_factor_dir),
            _optional_dir(comparison_backtest_dir),
            _ensure_trailing_slash(mkt_data_path),
            _optional_dir(stock_folder),
            _optional_dir(alpha_folder),
            _optional_dir(barra_folder),
            str(output_pdf),
            str(stock_price_daily),
            factor_name,
            reverse,
            insample_last_day,
            outsample_last_day,
        )
    return output_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a factor PDF report for a completed backtest run.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Directory containing backtest outputs.")
    parser.add_argument("--factor-name", required=True, help="Factor column/name.")
    parser.add_argument("--factor-file", type=Path, required=True, help="Factor CSV, Parquet file, or factor directory.")
    parser.add_argument("--output-pdf", type=Path, help="PDF path. Defaults to <run-dir>/<factor-name>_factor_report.pdf.")
    parser.add_argument("--data-root", type=Path, help="BacktestData_pq root, used to derive stock_price_daily when needed.")
    parser.add_argument("--stock-price-daily", type=Path, help="CSV with ticker, tradeDate, openPrice for report diagnostics.")
    parser.add_argument("--comparison-factor-dir", type=Path, help="Optional factor library directory for factor correlation.")
    parser.add_argument("--comparison-backtest-dir", type=Path, help="Optional backtest result directory for excess-return correlation.")
    parser.add_argument("--mkt-data-path", type=Path, help="Market daily data path for report diagnostics.")
    parser.add_argument("--stock-folder", type=Path, help="Stock daily data folder for pure factor return.")
    parser.add_argument("--alpha-folder", type=Path, help="Alpha factor folder for pure factor return.")
    parser.add_argument("--barra-folder", type=Path, help="Barra exposure folder for pure factor return.")
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--insample-last-day", type=int, default=20241231)
    parser.add_argument("--outsample-last-day", type=int, default=20260123)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_pdf = generate_report(
        args.run_dir,
        args.factor_name,
        args.factor_file,
        args.output_pdf,
        data_root=args.data_root,
        stock_price_daily=args.stock_price_daily,
        comparison_factor_dir=args.comparison_factor_dir,
        comparison_backtest_dir=args.comparison_backtest_dir,
        mkt_data_path=args.mkt_data_path,
        stock_folder=args.stock_folder,
        alpha_folder=args.alpha_folder,
        barra_folder=args.barra_folder,
        reverse=args.reverse,
        insample_last_day=args.insample_last_day,
        outsample_last_day=args.outsample_last_day,
    )
    print(json.dumps({"report_pdf": str(output_pdf)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
