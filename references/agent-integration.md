# Agent Integration - skill-factor-backtest

## Universal Test-Fixture Check

Run from the skill root:

```bash
python3 scripts/run_factor_backtest.py --test-data
```

The command reads checked-in Yahoo-backed test data from `data/test_data/`,
prints a JSON summary, and creates raw backtest files under
`output/run_YYYYMMDD_HHMMSS/`.

This is only a skill correctness test. For real backtests, require the user to
provide `--input-file`, `--factor-column`, and `--data-root`.

To test the report path too:

```bash
python3 scripts/run_factor_backtest.py --test-data --report
```

Success criteria:

- The command exits with code 0.
- The JSON summary includes `output_dir`.
- Every file in `expected_outputs` exists.
- The report check includes `report_pdf`, and that PDF exists.
- Fixture results are reported only as skill-validation evidence, not research
  evidence for a user factor.

Refresh `data/test_data/` only when the test dataset intentionally changes.
This fetches Yahoo Finance daily bars through `yfinance` and requires network
access:

```bash
python3 scripts/make_test_data.py
```

## Codex

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
rsync -a --exclude '__pycache__' ./ "${CODEX_HOME:-$HOME/.codex}/skills/factor-backtest/"
```

Use:

```text
Use $factor-backtest to run this factor CSV through the factor backtest workflow.
```

## Claude Code

```bash
mkdir -p ~/.claude/skills
rsync -a --exclude '__pycache__' ./ ~/.claude/skills/factor-backtest/
```

## Cursor

```bash
mkdir -p .cursor/skills .cursor/rules
rsync -a --exclude '__pycache__' ./ .cursor/skills/factor-backtest/
cp agents/cursor-rule.mdc .cursor/rules/factor-backtest.mdc
```

## OpenClaw Or Portable Runtimes

Mount the full folder unchanged and use `agents/portable-loader.md` as the
loader prompt.

## Registry Hygiene

Before publishing or reinstalling, check the repository state from the skill
root:

```bash
git status --short --ignored
find scripts -name '*.py' -print0 | xargs -0 python3 -m py_compile
```

Keep generated `output/` files ignored. The fixture data and report fonts are
intentional assets for deterministic test/report behavior; avoid adding more
large bundled data unless the fixture contract changes.
