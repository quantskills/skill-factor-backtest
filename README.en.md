# Factor Backtest

[简体中文](README.md) | **English**

> Run a cross-sectional factor backtest on user-provided trading data, with IC, group-return, portfolio, transaction, holding, and PDF diagnostic outputs.

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

## What This Is

`skill-factor-backtest` is a general-purpose cross-sectional factor backtest
skill. Given a factor signal and market data, it produces a complete
quantitative evaluation:

- **Signal quality** — cross-sectional rank IC across multiple forward windows.
- **Group monotonicity** — decile portfolio returns sorted by factor value.
- **Portfolio performance** — long-only equal-weight NAV, benchmark-hedged
  returns, drawdown, turnover, and win-rate.
- **Trade diagnostics** — per-day transaction and holding logs.
- **PDF report** — optional diagnostic report with linear, nonlinear,
  autocorrelation, and return decomposition.

The engine is market-agnostic: it works with stocks, ETFs, futures, crypto, or
any instrument whose data follows the required schema. The bundled
`data/test_data/` fixture exists only to verify the skill runs correctly; real
analysis must use your own data.

## Required Inputs

A backtest run requires all three inputs:

| Input | Argument | Description |
| --- | --- | --- |
| Factor data | `--input-file` | CSV, Parquet, or a directory of CSV/Parquet files. |
| Factor column | `--factor-column` | Numeric column to rank and trade; one factor per run. |
| Market data root | `--data-root` | Parquet market-data root aligned to the factor dates and tickers. |

`--input-file` contains only factor signals. `--data-root` contains the trading calendar, prices, masks, benchmark, and other market data required to run a real backtest. A real backtest cannot run without `--data-root`; only explicit `--test-data` mode fills paths from the bundled fixture manifest.

If any of these inputs are missing, the agent should ask the user for the missing file, path, or column. It should not substitute `data/test_data/` unless the user explicitly asks to test the skill.

Factor data must contain at least:

| Column | Meaning |
| --- | --- |
| `date` | Factor date as integer-like `YYYYMMDD`. |
| `ticker` | Integer-like instrument code matching market-data matrix columns. |
| factor column | Numeric signal. Higher values are better by default; use `--reverse` when lower values are better. |

The market-data root must contain calendar, price, adjustment, tradability, exclusion mask, and benchmark files. See [references/backtest-contract.md](references/backtest-contract.md) for the full schema.

## Configuration

Strategy parameters and default paths are set in two INI files under `scripts/config/`:

| File | Purpose |
| --- | --- |
| `backtestconfig.ini` | Strategy defaults: `longx`, `benchmark`, `transaction`, `turnover_mode`, `keep`, etc. Edit `[long_only_equal_weight]` or add new `[sections]` for custom strategies. |
| `pathconfig.ini` | Fallback paths for `--data-root` and `--optimizer-root`; normally left as `.` and overridden via CLI. |

Any strategy value can be overridden at runtime with `--override key=value`.

## Quick Run

```bash
python3 scripts/run_factor_backtest.py \
  --input-file /path/to/factor.csv \
  --factor-column my_factor \
  --data-root /path/to/BackTestData_pq \
  --timespan 20250101 20250630
```

Default output directory:

```text
output/run_YYYYMMDD_HHMMSS/
```

Common optional arguments:

| Argument | Use |
| --- | --- |
| `--reverse` | Reverse factor direction when lower values are better. |
| `--override longx=200` | Set maximum holdings. |
| `--override benchmark=benchmark` | Select `Benchmark/<name>.parquet`. |
| `--output-dir <dir>` | Use a fixed output directory; usually omit this. |
| `--report` | Generate a PDF diagnostic report after the backtest. |
| `--optimizer-root <dir>` | Attribution/optimizer data for `--pure-alpha`; usually not needed for normal backtests. |

## PDF Report

```bash
python3 scripts/run_factor_backtest.py \
  --input-file /path/to/factor.csv \
  --factor-column my_factor \
  --data-root /path/to/BackTestData_pq \
  --timespan 20250101 20250630 \
  --report
```

The report uses the current run output for the core pages. These inputs are optional; when absent, the corresponding comparison or attribution section is skipped or left empty:

| Argument | Use |
| --- | --- |
| `--report-stock-price-daily` | Prepared `ticker, tradeDate, openPrice` daily data; otherwise derived from `--data-root/open_price.parquet` when possible. |
| `--report-comparison-factor-dir` | Factor library directory for factor-value correlation. |
| `--report-comparison-backtest-dir` | Backtest-result directory for excess-return correlation. |
| `--report-barra-folder` | Barra/style exposure directory for pure-factor attribution. |

Generate a report for an existing run:

```bash
python3 scripts/generate_factor_report.py \
  --run-dir output/run_YYYYMMDD_HHMMSS \
  --factor-name my_factor \
  --factor-file /path/to/factor.csv \
  --data-root /path/to/BackTestData_pq
```

## Outputs

Core outputs include:

| File | Meaning |
| --- | --- |
| `stats.csv` | Cash, NAV, benchmark, hedged NAV, IC, daily return, and drawdown. |
| `ICs.csv` | IC series across multiple forward windows. |
| `group_ret.csv` / `group_return.png` | Group return diagnostics. |
| `Pnl.png` | NAV, benchmark, hedged NAV, and key summary statistics. |
| `transaction.csv` | Transaction records. |
| `holdings.csv` | Holding records. |
| `<factor>_factor_report.pdf` | PDF diagnostic report when `--report` is used. |

## Verification

A run is complete only after the agent checks the printed JSON summary and the
files on disk:

- `output_dir` exists and contains every file listed in `expected_outputs`.
- `stats.csv` is present for the default `savemode=3` run.
- `transaction.csv` and `holdings.csv` are present for `savemode=3`.
- `report_pdf` exists when `--report` is used.
- Missing real-run inputs fail fast instead of falling back to the fixture.

## Test Fixture

Use bundled test data only when you need to test the skill:

```bash
python3 scripts/run_factor_backtest.py --test-data
python3 scripts/run_factor_backtest.py --test-data --report
```

`data/test_data/` is built from Yahoo Finance daily bars and is only for validating execution and report generation. It is not research evidence. Refreshing it requires network access:

```bash
python3 scripts/make_test_data.py
```

## Registry Notes

The QuantSkills registry checks for required docs, valid frontmatter, Python
syntax, link health, secrets, and git hygiene. Keep `output/` ignored. Large
checked-in assets such as fixture data or fonts should be intentional and
documented; avoid adding more bundled market data unless the fixture contract
requires it.

## Disclaimer

This repository organizes research workflows only. Not investment advice.

## Maintainer

Created and maintained by `davideliu` for the QuantSkills community.

## License

GPL-3.0. See [LICENSE](LICENSE).
