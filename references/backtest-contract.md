# Backtest Contract

This reference is the detailed contract for running the backtest workflow.
It defines required user inputs, data schema, parameters, outputs, and report
behavior.

## Data Modes

| Mode | Purpose | Command |
| --- | --- | --- |
| User backtest | Run the user's factor on the user's own schema-compatible trading database. This is the normal workflow. | `python3 scripts/run_factor_backtest.py --input-file ... --factor-column ... --data-root ...` |
| Test fixture | Verify the skill, dependencies, wrapper, report path, and output parsing. Not for research conclusions. | `python3 scripts/run_factor_backtest.py --test-data` |

Never use `data/test_data/` unless the user explicitly asks to run the test
fixture or validate the skill. For real use, require the user to provide their
own factor file, universe, benchmark, market data, masks, and optional report
libraries.

## Runtime Files

- `scripts/backtest_engine/BackTest.py` - backtest engine. It reads factor
  data, Parquet market data, filters signals, calculates IC/group returns,
  trades a long-only equal-weight portfolio, plots NAV, and saves result files.
- `scripts/config/backtestconfig.ini` - strategy parameters. Default section:
  `long_only_equal_weight`.
- `scripts/config/pathconfig.ini` - path configuration file.
- `scripts/run_factor_backtest.py` - portable entrypoint. Use this for all
  normal runs.
- `scripts/generate_factor_report.py` - PDF report adapter for existing output
  folders.
- `scripts/factor_report_generate/` - report-generation modules.

## Required User Inputs

For a real run, all three are required:

| Input | CLI | Required content |
| --- | --- | --- |
| Factor data | `--input-file` | CSV, Parquet, or directory of CSV/Parquet files. |
| Factor column | `--factor-column` | Numeric column in the factor data. One factor column per run. |
| Market data root | `--data-root` | Parquet database root with the files below. |

If the user's request does not provide these three, ask for the missing
file/path/column. Do not substitute test data.

## Agent Run Checklist

Use this checklist for every run:

1. Confirm mode: user-data run or explicit test-fixture run.
2. For user data, confirm `--input-file`, `--factor-column`, and `--data-root`.
3. Check that the factor input exists and contains `date`, `ticker`, and the
   selected factor column.
4. Check that `--data-root` contains the required Parquet files and the selected
   benchmark file.
5. Run `scripts/run_factor_backtest.py` and inspect the printed JSON summary.
6. Verify that every file in `expected_outputs` exists under `output_dir`.
7. If `--report` was requested, verify that `report_pdf` exists.
8. Report the mode, output directory, key metrics, skipped optional sections, and
   assumptions. Do not turn fixture output into research evidence.

## Factor Input Schema

Factor data must contain at least:

| Column | Required type | Meaning |
| --- | --- | --- |
| `date` | integer-like `YYYYMMDD` | Factor observation date. |
| `ticker` | integer-like instrument/security code | Must match market-data matrix columns after integer conversion. |
| selected factor column | numeric | Factor value used for ranking. |

Behavior:

- The selected factor column is renamed internally to `proba`.
- Higher values are treated as better signals.
- Use `--reverse` when lower values should be better.
- Duplicate `(date, ticker)` rows are removed after keeping the first observed
  value.
- `--timespan START END` filters factor rows before pivoting.
- The engine later shifts the signal by `buy_sell_shift`; the default `1` means
  next-trading-day execution.

## Market Data Root Schema

Minimum layout:

```text
BackTestData_pq/
├── calendar.parquet
├── name_dict.parquet
├── adjfactor.parquet
├── pre_close.parquet
├── trade_price.parquet
├── balance_price.parquet
├── open_price.parquet
├── mask_isopen.parquet
├── mask_isST.parquet
└── Benchmark/
    └── <benchmark>.parquet
```

If `stock_pool != whole`, also provide:

```text
BackTestData_pq/
└── stock_pool/
    └── <stock_pool>.parquet
```

Matrix files:

| File | Shape | Expected contents |
| --- | --- | --- |
| `adjfactor.parquet` | date index x ticker columns | Adjustment factor. |
| `pre_close.parquet` | date index x ticker columns | Previous close. |
| `trade_price.parquet` | date index x ticker columns | Trade price used by the engine. |
| `balance_price.parquet` | date index x ticker columns | Mark-to-market close/balance price. |
| `open_price.parquet` | date index x ticker columns | Open price for limit checks and report stock daily input. |
| `mask_isopen.parquet` | date index x ticker columns | Boolean tradability/open mask. |
| `mask_isST.parquet` | date index x ticker columns | Boolean excluded/security-status mask. |
| `stock_pool/<name>.parquet` | date index x ticker columns | Boolean stock-pool membership when enabled. |

Non-matrix files:

| File | Required columns | Notes |
| --- | --- | --- |
| `calendar.parquet` | `calendarDate`, `isOpen` | `calendarDate` should parse as `YYYY-MM-DD`; only `isOpen == 1` dates are used. |
| `name_dict.parquet` | `ticker`, `secShortName` | Used for transaction/holding labels. |
| `Benchmark/<benchmark>.parquet` | `tradeDate`, `closeIndex`, `openIndex` | `benchmark` must match the config/override value. |

Ticker columns must be convertible to integers because the engine calls
`rename(columns=int)` when loading market matrices.

## Config Files

Users can customize strategy behaviour and default paths by editing the two
INI files under `scripts/config/`.

### `backtestconfig.ini` — strategy parameters

Each `[section]` defines a named strategy. The default strategy is
`[long_only_equal_weight]`. The engine reads the section corresponding to
`--strategy` (or the default when `--strategy` is omitted).

```ini
[long_only_equal_weight]
longx=200
stock_pool=whole
trade_price_type=twap
buy_sell_shift=1
transaction=1.4
benchmark=benchmark
turnover_mode=flex
keep=0.7
```

| Key | Meaning |
| --- | --- |
| `longx` | Maximum number of long holdings. |
| `stock_pool` | `whole` disables stock-pool filtering; any other value loads `stock_pool/<value>.parquet`. |
| `trade_price_type` | Price source metadata (`twap`; market prices are read from the `--data-root` files). |
| `buy_sell_shift` | Signal/trade delay in trading days. `1` means next-day execution. |
| `transaction` | Round-trip cost in per-mille (‱); split half buy, half sell. |
| `benchmark` | Benchmark file name under `Benchmark/<name>.parquet`. |
| `turnover_mode` | `flex` retains existing holdings first, then fills with top-ranked names. |
| `keep` | Fraction of portfolio value retained before rebalancing in `flex` mode. |

Any strategy value can be overridden at runtime with `--override key=value`
(repeatable). For example:

```bash
--override longx=100 --override benchmark=hs300
```

### `pathconfig.ini` — path defaults

```ini
[PATH]
BASE_PATH_PQ=.
OPT_PATH=.
```

| Key | Meaning |
| --- | --- |
| `BASE_PATH_PQ` | Default market-data root; overridden by `--data-root`. |
| `OPT_PATH` | Default optimizer/attribution root; overridden by `--optimizer-root`. |

In normal use these are left as `.` and the CLI arguments supply the real
paths. Edit `pathconfig.ini` only if you want to hard-code a fixed data root
for repeated local runs.

## Parameters

Common CLI parameters:

| Parameter | Meaning |
| --- | --- |
| `--input-file` | Factor CSV, Parquet file, or directory. Required for real runs. |
| `--factor-column` | Factor column in the input. Required for real runs. |
| `--data-root` | Market-data Parquet root. Required for real runs. |
| `--timespan START END` | Inclusive factor-date filter before pivoting. |
| `--output-dir` | Output folder. Omit to use `output/run_YYYYMMDD_HHMMSS/`. |
| `--reverse` | Negate the factor before ranking. |
| `--savemode` | Controls saved outputs. Default `3` saves stats, transactions, and holdings. |
| `--strategy` | Section in `scripts/config/backtestconfig.ini`. Default `long_only_equal_weight`. |
| `--override key=value` | Override one strategy config value. Repeatable. |
| `--report` | Generate PDF report after raw backtest outputs. |
| `--pure-alpha` | Run pure-alpha attribution; needs optimizer/Barra data. |
| `--optimizer-root` | Optimizer or attribution data root; defaults to `--data-root`. |
| `--test-data` | Explicitly run the checked-in test fixture. Not for real analysis. |

Default strategy values:

| Config value | Meaning |
| --- | --- |
| `longx` | Maximum number of long holdings. |
| `stock_pool` | `whole` means no stock-pool mask; otherwise read `stock_pool/<name>.parquet`. |
| `trade_price_type` | Strategy metadata; market prices are read from the configured market-data root. |
| `buy_sell_shift` | Signal/trade delay in trading days. `1` means next-day trading. |
| `transaction` | Round-trip cost in per-mille; the engine splits it half buy, half sell. |
| `benchmark` | Benchmark file under `Benchmark/<benchmark>.parquet`. |
| `turnover_mode` | `flex` keeps old holdings first, then fills with top-ranked names. |
| `keep` | Old-position value retention target in `flex` mode. |

## Engine Flow

`TradingSystem.run()` executes:

1. `load_data()`
2. `load_date_list()`
3. `load_auxilliary()`
4. `preclean_data()`
5. `calculate_IC()`
6. `calc_group()`
7. `main_loop()`
8. `plot()`
9. `save()`
10. `Pure_alpha_analysis()` only when `pure_alpha=True`

Behavior details:

- `load_data()` pivots factor rows into `date x ticker`.
- `load_date_list()` aligns factor dates to the trading calendar and applies
  `buy_sell_shift` to determine the executable date range.
- `load_auxilliary()` loads prices, masks, adjustment factors, benchmark, and
  optional stock-pool data.
- `preclean_data()` filters shifted signals by limit-up, limit-down, open mask,
  status mask, and stock-pool membership.
- `calculate_IC()` computes rank IC over multiple forward windows.
- `calc_group()` builds decile group returns.
- `main_loop()` trades a long-only portfolio using top-ranked signals.
- `plot()` writes performance figures; `save()` writes CSV outputs according to
  `savemode`.

## Output Files

Expected core outputs:

- `ICs.csv` - IC series for multiple forward windows.
- `group_ret.csv` - cumulative decile group returns.
- `group_return.png` - decile group return plot.
- `Pnl.png` - NAV, benchmark, hedged NAV, IC bars, and summary metrics when
  `savemode != 0`.
- `winrate.png` - monthly win-rate chart.
- `stats.csv` - cash, absolute NAV, benchmark NAV, hedged NAV, IC, daily return,
  and max drawdown when `savemode >= 2`.
- `transaction.csv` - transaction details when `savemode == 3`.
- `holdings.csv` - holding details when `savemode == 3`.
- `<factor>_factor_report.pdf` - generated only when `--report` is passed or
  `scripts/generate_factor_report.py` is run.

Typical `stats.csv` columns include `cash`, `unrealized_pnl`, `IC`,
`benchmark`, `hedged_unrealized_pnl`, `DailyPCT`, and `MaxDrawdown`.

## PDF Report Generation

PDF report generation uses the current run outputs and optional auxiliary
datasets. The wrapper `scripts/generate_factor_report.py` prepares the minimal
layout files needed by the report generator, such as stock daily data derived
from `open_price.parquet` when `--stock-price-daily` is omitted.

The report generator can use more than raw backtest outputs:

- Python source modules: `LinearIndicator.py`, `NonLinearIndicator.py`, and
  `PureFactorReturn.py`.
- Original factor file or factor directory matching `--factor-column`.
- Comparison factor files for factor-value correlation tables.
- Comparison backtest result folders for excess-return correlation tables.
- Stock daily data with `ticker`, `tradeDate`, and `openPrice`.
- Barra/style, stock daily, and alpha folders for pure-factor return sections.

If optional comparison, Barra, or alpha datasets are absent, the report should
run where possible and leave those sections empty or skipped.

## Test Fixture Data

`data/test_data/` exists only to verify skill correctness. It currently contains:

- Yahoo Finance daily bars fetched through `yfinance`.
- 70 US-listed symbols mapped to integer tickers.
- SPY as the benchmark source, saved as `Benchmark/benchmark.parquet`.
- A deterministic factor column named `test_factor`.
- Enough dates and tickers to populate the report's linear and nonlinear metric
  tables.

Use only when the user explicitly asks for test data:

```bash
python3 scripts/run_factor_backtest.py --test-data --report
```

Do not use fixture results as evidence about the user's factor, market, or
production universe.

## Known Runtime Notes

- Current pandas versions removed `DatetimeIndex.week`; the wrapper adds a
  compatibility alias before running.
- Limit-up/limit-down checks use a fixed `LOCKED_LIMIT = 0.095`; provide
  masks/prices that make sense for the user's trading universe.
- Pure-alpha mode needs extra optimizer or attribution files.

## Registry And Packaging Notes

The skill should stay registry-compatible:

- Keep `output/` and runtime caches ignored.
- Run Python syntax checks before packaging:
  `find scripts -name '*.py' -print0 | xargs -0 python3 -m py_compile`.
- Large fixture or font files can trigger registry git-hygiene warnings. Keep
  them only when they are required for deterministic fixture/report behavior,
  and avoid adding extra bundled data.
- If the checked-in fixture changes, refresh `data/test_data/manifest.json` and
  rerun both `--test-data` and `--test-data --report`.
