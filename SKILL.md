---
name: factor-backtest
description: >-
  Cross-sectional trading-factor backtest skill for schema-compatible user
  data. Use when an agent needs to run or explain a long-only factor backtest,
  validate factor and market-data inputs, inspect timestamped outputs, generate
  a PDF diagnostic report, or explicitly verify the skill pipeline with the
  checked-in test fixture.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-factor-backtest
  repository_url: https://github.com/quantskills/skill-factor-backtest
  project_type: skill
  collection: factor-tools
  creator: davideliu
  creator_url: https://github.com/davideliu
  maintainer: davideliu
  maintainer_url: https://github.com/davideliu
quantSkills:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-factor-backtest
  repository_url: https://github.com/quantskills/skill-factor-backtest
  project_type: skill
  collection: factor-tools
  category: tooling
  tags:
    - backtest
    - factor-validation
    - trading-data
    - cross-sectional
    - long-only
    - test-fixture
  platforms:
    - claude-code
    - codex
    - cursor
    - openclaw
  language: zh-en
  status: draft
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 对用户提供的交易因子和行情数据执行通用横截面回测；内置测试数据仅用于技能自测。
  summary_en: Run a cross-sectional factor backtest on schema-compatible trading data; bundled test data is only for skill validation.
---

# Factor Backtest

Use this skill to run a long-only cross-sectional factor backtest on
schema-compatible trading data.

The engine is not limited to one market as long as the user's trading data
matches the required schema: integer-like dates, integer-like tickers, aligned
price/mask matrices, and a benchmark file. The checked-in `data/test_data/`
fixture is only for testing the skill pipeline. Do not use it unless the user
explicitly asks to run the test data or to validate the skill itself.

Use the command-line entrypoints in `scripts/` for normal operation. Keep edits
scoped to the user's request.

## Required User Inputs

For a real run, the user must provide all three:

- `--input-file`: factor CSV, factor Parquet file, or a directory of factor
  CSV/Parquet files.
- `--factor-column`: the factor column to rank. The engine runs one factor
  column per invocation.
- `--data-root`: the user's Parquet market-data root.

`--input-file` is the signal file; `--data-root` is the market database used to
price, filter, benchmark, and trade those signals. A real backtest cannot run
without `--data-root`. Only `--test-data` mode fills it from
`data/test_data/manifest.json`.

If any of these three are missing and the user did not explicitly ask to run the
test fixture, ask the user for the missing file/path/column before running. Do
not silently fall back to `data/test_data/`.

Optional user inputs include `--timespan`, `--output-dir`, `--reverse`,
`--savemode`, `--strategy`, `--override key=value`, `--report`, report
auxiliary paths, `--pure-alpha`, and `--optimizer-root`.

## Core Workflow

1. Read `references/backtest-contract.md` before preparing data or running a
   user backtest.
2. Decide mode:
   - Real run: require `--input-file`, `--factor-column`, and `--data-root`.
   - Test-fixture run: use `--test-data` only when the user explicitly asks for
     a skill correctness test.
3. Validate factor input:
   - File or directory exists.
   - Data has `date`, `ticker`, and the selected factor column.
   - `date` is integer-like `YYYYMMDD`.
   - `ticker` values match market-data matrix columns after integer conversion.
4. Validate market data root:
   - Required files: `calendar.parquet`, `name_dict.parquet`,
     `adjfactor.parquet`, `pre_close.parquet`, `trade_price.parquet`,
     `balance_price.parquet`, `open_price.parquet`, `mask_isopen.parquet`,
     `mask_isST.parquet`, and `Benchmark/<benchmark>.parquet`.
   - If `stock_pool` is not `whole`, require `stock_pool/<stock_pool>.parquet`.
5. Run through `scripts/run_factor_backtest.py`.
6. Inspect `output/run_<timestamp>/` unless the user passed `--output-dir`.
   Report `stats.csv`, `ICs.csv`, `group_ret.csv`, `Pnl.png`, and when
   `savemode=3`, `transaction.csv` and `holdings.csv`.
7. Add `--report` only when the user requests a PDF report. Optional
   comparison factor, comparison backtest, stock daily, Barra, and alpha
   folders determine which report sections are populated.
8. In the final response, state whether the run used user data or test data,
   the output directory, key metrics, missing optional report sections, and any
   assumptions such as factor direction, benchmark, holding count, and date
   range.

## How The Backtest Works

- `load_data()` reads factor data, filters by `--timespan` when provided,
  renames the selected factor column to `proba`, optionally negates it with
  `--reverse`, de-duplicates `(date, ticker)`, and pivots to a date-by-ticker
  signal matrix.
- `load_date_list()` maps factor dates onto the trading calendar. With
  `buy_sell_shift=1`, a signal observed on day `t` is traded from the next
  trading day.
- `load_auxilliary()` loads prices, adjustment factors, open/ST masks,
  benchmark data, and optional stock-pool masks from `--data-root`.
- `preclean_data()` aligns shifted signals to tradable tickers and removes
  names that are limit-up, limit-down, not open, ST, or outside the stock pool.
- `calculate_IC()` computes cross-sectional rank ICs over multiple forward
  windows.
- `calc_group()` computes decile group returns and `group_return.png`.
- `main_loop()` runs a long-only equal-weight portfolio. Higher factor values
  are bought first unless `--reverse` is set. `longx` controls max holdings.
- `plot()` and `save()` write result files according to `savemode`.
- `Pure_alpha_analysis()` runs only when `--pure-alpha` is set and the required
  optimizer/Barra data is available.

## Commands

Real user-data run:

```bash
python3 scripts/run_factor_backtest.py \
  --input-file /path/to/factor.csv \
  --factor-column my_factor \
  --data-root /path/to/BackTestData_pq \
  --timespan 20250101 20250630 \
  --override longx=200 \
  --override benchmark=benchmark
```

Real user-data run with PDF report:

```bash
python3 scripts/run_factor_backtest.py \
  --input-file /path/to/factor.csv \
  --factor-column my_factor \
  --data-root /path/to/BackTestData_pq \
  --timespan 20250101 20250630 \
  --report
```

Existing-run report refresh:

```bash
python3 scripts/generate_factor_report.py \
  --run-dir output/run_YYYYMMDD_HHMMSS \
  --factor-name my_factor \
  --factor-file /path/to/factor.csv \
  --data-root /path/to/BackTestData_pq
```

Explicit test-fixture run:

```bash
python3 scripts/run_factor_backtest.py --test-data
```

Explicit full test-fixture run with PDF report:

```bash
python3 scripts/run_factor_backtest.py --test-data --report
```

Refresh the checked-in Yahoo-backed test fixture only when it intentionally
needs to change. This requires network access:

```bash
python3 scripts/make_test_data.py
```

## Output Contract

The engine writes results into `output/run_<timestamp>/` by default:

- `ICs.csv` - IC series for multiple forward windows.
- `group_ret.csv` and `group_return.png` - decile group cumulative returns.
- `Pnl.png` and `winrate.png` - NAV, benchmark, hedged NAV, IC, and win-rate
  figures when plotting is enabled.
- `stats.csv` - cash, absolute NAV, benchmark NAV, hedged NAV, IC, daily return,
  and max drawdown when `savemode >= 2`.
- `transaction.csv` and `holdings.csv` - transaction and holding details when
  `savemode == 3`.
- `<factor>_factor_report.pdf` - generated only when `--report` is passed or
  `scripts/generate_factor_report.py` is run.
- Pure-alpha files such as `Explo.csv`, `Pure_alpha.png`, `Style_radar.png`,
  and `Industry_radar.png` only appear when `--pure-alpha` is used and the
  optimizer database is available.

## Runtime Notes

- Default strategy section: `long_only_equal_weight`.
- Do not use `data/test_data/` unless the user explicitly asks for a skill
  correctness test.
- Missing optional report comparison or Barra inputs should leave the
  corresponding report sections empty or skipped.

## Reference Files

- `references/backtest-contract.md` - detailed factor, market-data, parameter,
  output, and report contract.
- `references/agent-integration.md` - cross-agent install and test-fixture
  notes.
- `data/test_data/` - checked-in Yahoo-backed fixture for skill tests only.
- `scripts/backtest_engine/BackTest.py` - backtest engine.
- `scripts/config/backtestconfig.ini` - default strategy parameters.
- `scripts/make_test_data.py` - refreshes `data/test_data/`; requires network
  access to Yahoo Finance through `yfinance`.
- `scripts/run_factor_backtest.py` - wrapper for user-data or explicit
  test-fixture runs.
- `scripts/generate_factor_report.py` - creates PDF reports for existing run
  folders.
