#!/usr/bin/env python3
"""Create a saved Yahoo-backed test fixture for the backtest workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = SKILL_ROOT / "data" / "test_data"
FACTOR_NAME = "test_factor"
BENCHMARK = "benchmark"
START_DATE = "2022-01-03"
END_DATE = "2026-01-01"
REPORT_INSAMPLE_LAST_DAY = "20241231"

YAHOO_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B",
    "LLY", "AVGO", "JPM", "V", "XOM", "UNH", "MA", "COST", "HD", "PG",
    "JNJ", "ABBV", "NFLX", "BAC", "KO", "CRM", "CVX", "WMT", "ORCL",
    "MRK", "CSCO", "AMD", "ACN", "MCD", "IBM", "LIN", "GE", "ADBE",
    "TMO", "PEP", "DIS", "QCOM", "AMAT", "TXN", "INTU", "CAT", "PM",
    "VZ", "BKNG", "ISRG", "GS", "NOW", "SPGI", "RTX", "PFE", "LOW",
    "NKE", "HON", "UPS", "MS", "T", "COP", "AMGN", "BA", "SBUX",
    "ELV", "DE", "BLK", "MDLZ", "GILD", "LMT", "ADP",
]


def _date_ints(dates: pd.DatetimeIndex) -> list[int]:
    return [int(d.strftime("%Y%m%d")) for d in dates]


def _write_matrix(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(SKILL_ROOT))
    except ValueError:
        return str(resolved)


def _download_prices(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    data = yf.download(
        symbols,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if data.empty:
        raise RuntimeError("Yahoo download returned no test fixture stock data.")
    if not isinstance(data.columns, pd.MultiIndex):
        raise RuntimeError("Yahoo download did not return the expected multi-symbol column layout.")
    return data.sort_index()


def _field(data: pd.DataFrame, name: str) -> pd.DataFrame:
    return data.xs(name, axis=1, level=0).sort_index(axis=1)


def _clean_price_panels(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    raw_open = _field(data, "Open")
    raw_close = _field(data, "Close")
    adj_close = _field(data, "Adj Close")

    valid_symbols = [
        symbol
        for symbol in raw_close.columns
        if raw_close[symbol].notna().mean() >= 0.98 and raw_open[symbol].notna().mean() >= 0.98
    ]
    if len(valid_symbols) < 35:
        raise RuntimeError(f"Need at least 35 valid Yahoo symbols, got {len(valid_symbols)}.")

    raw_open = raw_open[valid_symbols].ffill().bfill()
    raw_close = raw_close[valid_symbols].ffill().bfill()
    adj_close = adj_close[valid_symbols].ffill().bfill()
    adjustment = (adj_close / raw_close).replace([np.inf, -np.inf], np.nan).ffill().bfill()

    open_price = raw_open * adjustment
    close_price = adj_close
    trade_price = (open_price + close_price) / 2
    return open_price, close_price, trade_price, valid_symbols


def _make_factor(close_price: pd.DataFrame) -> pd.DataFrame:
    returns = close_price.pct_change()
    momentum = close_price.pct_change(126).shift(1)
    reversal = -close_price.pct_change(21).shift(1)
    low_vol = -returns.rolling(63).std().shift(1)

    def cross_sectional_zscore(frame: pd.DataFrame) -> pd.DataFrame:
        mean = frame.mean(axis=1)
        std = frame.std(axis=1).replace(0, np.nan)
        return frame.sub(mean, axis=0).div(std, axis=0)

    factor = (
        cross_sectional_zscore(momentum)
        + 0.25 * cross_sectional_zscore(reversal)
        + 0.25 * cross_sectional_zscore(low_vol)
    )
    return factor.dropna(how="all")


def _download_benchmark(index: pd.DatetimeIndex) -> pd.DataFrame:
    benchmark = yf.download(
        "SPY",
        start=index.min().strftime("%Y-%m-%d"),
        end=(index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if benchmark.empty:
        raise RuntimeError("Yahoo download returned no SPY benchmark data.")
    if isinstance(benchmark.columns, pd.MultiIndex):
        benchmark = benchmark.xs("SPY", axis=1, level=-1)
    benchmark = benchmark.reindex(index).ffill().bfill()
    adj = benchmark["Adj Close"] / benchmark["Close"]
    return pd.DataFrame(
        {
            "tradeDate": [d.strftime("%Y-%m-%d") for d in index],
            "closeIndex": benchmark["Adj Close"].to_numpy(),
            "openIndex": (benchmark["Open"] * adj).to_numpy(),
        }
    )


def build_test_data(output_root: Path = DEFAULT_OUTPUT_ROOT, *, force: bool = True) -> dict[str, str]:
    output_root = output_root.resolve()
    data_root = output_root / "backtest_db"
    factor_root = output_root / "factors"

    if output_root.exists() and not force:
        raise FileExistsError(f"{output_root} already exists; pass force=True to overwrite files")

    raw_data = _download_prices(YAHOO_SYMBOLS, START_DATE, END_DATE)
    open_price, close_price, trade_price, symbols = _clean_price_panels(raw_data)

    ticker_map = {symbol: 100001 + i for i, symbol in enumerate(symbols)}
    open_price = open_price.rename(columns=ticker_map)
    close_price = close_price.rename(columns=ticker_map)
    trade_price = trade_price.rename(columns=ticker_map)

    date_ints = _date_ints(close_price.index)
    open_price.index = date_ints
    close_price.index = date_ints
    trade_price.index = date_ints
    pre_close = close_price.shift(1).bfill()

    factor = _make_factor(close_price)
    factor = factor.loc[factor.notna().sum(axis=1) >= 35]
    factor_start = int(factor.index.min())
    factor_end = int(factor.index.max())
    factor_rows = (
        factor.rename_axis(index="date", columns="ticker")
        .reset_index()
        .melt(id_vars="date", var_name="ticker", value_name=FACTOR_NAME)
        .dropna()
    )

    adjfactor = pd.DataFrame(1.0, index=close_price.index, columns=close_price.columns)
    isopen = close_price.notna()
    isst = pd.DataFrame(False, index=close_price.index, columns=close_price.columns)
    calendar = pd.DataFrame(
        {"calendarDate": [pd.Timestamp(str(d)).strftime("%Y-%m-%d") for d in close_price.index], "isOpen": 1}
    )
    names = pd.DataFrame(
        {
            "ticker": list(ticker_map.values()),
            "secShortName": [symbol.replace("-", ".") for symbol in ticker_map],
        }
    )
    benchmark = _download_benchmark(pd.to_datetime(close_price.index.astype(str), format="%Y%m%d"))

    _write_matrix(adjfactor, data_root / "adjfactor.parquet")
    _write_matrix(pre_close, data_root / "pre_close.parquet")
    _write_matrix(trade_price, data_root / "trade_price.parquet")
    _write_matrix(close_price, data_root / "balance_price.parquet")
    _write_matrix(open_price, data_root / "open_price.parquet")
    _write_matrix(isopen, data_root / "mask_isopen.parquet")
    _write_matrix(isst, data_root / "mask_isST.parquet")
    _write_matrix(calendar, data_root / "calendar.parquet")
    _write_matrix(names, data_root / "name_dict.parquet")
    _write_matrix(benchmark, data_root / "Benchmark" / f"{BENCHMARK}.parquet")

    factor_root.mkdir(parents=True, exist_ok=True)
    factor_file = factor_root / f"{FACTOR_NAME}.csv"
    factor_rows.to_csv(factor_file, index=False)

    manifest = {
        "factor_file": _portable_path(factor_file),
        "factor_column": FACTOR_NAME,
        "data_root": _portable_path(data_root),
        "benchmark": BENCHMARK,
        "start_date": str(factor_start),
        "end_date": str(factor_end),
        "report_insample_last_day": REPORT_INSAMPLE_LAST_DAY,
        "report_outsample_last_day": str(factor_end),
        "tickers": str(len(symbols)),
        "dates": str(len(close_price.index)),
        "factor_rows": str(len(factor_rows)),
        "source": "Yahoo Finance daily OHLCV via yfinance",
        "source_start_date": START_DATE,
        "source_end_date": "2025-12-31",
        "benchmark_source": "SPY",
        "symbol_map": {str(v): k for k, v in ticker_map.items()},
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["manifest"] = _portable_path(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Yahoo-backed test fixture data for skill-factor-backtest.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--no-force", action="store_true", help="Fail if output root already exists.")
    args = parser.parse_args()

    manifest = build_test_data(args.output_root, force=not args.no_force)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
