# Portable Loader Prompt

Use this prompt in Claude Code, Hermes, OpenClaw, or any agent runtime that does
not natively discover `SKILL.md` folders. If the runtime supports native skill
folders, install the full folder unchanged and load `SKILL.md` directly.

```text
You have access to a local skill named factor-backtest at:
<FACTOR_BACKTEST_SKILL_ROOT>

This skill runs the schema-compatible trading-factor backtest engine in:
<FACTOR_BACKTEST_SKILL_ROOT>/scripts/backtest_engine/BackTest.py

When the user asks to run or explain a backtest:
1. Read <FACTOR_BACKTEST_SKILL_ROOT>/SKILL.md.
2. Read <FACTOR_BACKTEST_SKILL_ROOT>/references/backtest-contract.md.
3. Do not edit BackTest.py unless the user explicitly asks for source-code
   changes.
4. For an explicit test-data run, use the checked-in Yahoo-backed data under <FACTOR_BACKTEST_SKILL_ROOT>/data/test_data:
   python3 <FACTOR_BACKTEST_SKILL_ROOT>/scripts/run_factor_backtest.py --test-data
5. Treat the checked-in test data as a fixture only. For real backtests, the user
   must provide their own data:
   python3 <FACTOR_BACKTEST_SKILL_ROOT>/scripts/run_factor_backtest.py \
     --input-file <factor.csv> \
     --factor-column <factor_column> \
     --data-root <BackTestData_pq>
6. Add --report only when the existing scripts/factor_report_generate Python
   modules and auxiliary datasets are available.
7. Report the generated output/run_YYYYMMDD_HHMMSS directory and key stats from
   stats.csv. Run make_test_data.py only when the checked-in Yahoo-backed
   test fixture dataset intentionally needs to be refreshed; it requires network
   access.
```

Runtime placement notes:

- Codex: keep the folder under a Codex skill path and invoke `$factor-backtest`.
- Claude Code: keep the folder under a Claude skill path and invoke `$factor-backtest`.
- Cursor: copy this folder to `.cursor/skills/factor-backtest` and enable
  `agents/cursor-rule.mdc`.
- Hermes/OpenClaw: mount the folder as a local skill root or paste the loader
  prompt above with the real path.
