# Factor Backtest

**简体中文** | [English](README.en.md)

> 对用户提供的交易因子和行情数据执行横截面多空以外的 long-only 因子回测，并输出 IC、分组收益、净值、持仓、成交和 PDF 诊断报告。

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

## 这是什么

`skill-factor-backtest` 是一个通用横截面交易因子回测技能。它用于回答这类问题：

- 这个因子在给定交易池和行情数据上是否有稳定 IC？
- 按因子值分组后，各组收益是否单调？
- long-only 等权组合的净值、回撤、换手和胜率如何？
- 回测结果是否可以生成一份包含线性、非线性、自相关和收益诊断的 PDF 报告？

本技能不绑定某一个市场。只要用户数据满足输入格式，股票、ETF、期货、加密资产或其他可交易标的都可以使用。内置 `data/test_data/` 只用于检查技能是否能正常运行；真实分析必须使用用户自己的数据。

## 必要输入

真实回测必须提供三个输入：

| 输入 | 参数 | 说明 |
| --- | --- | --- |
| 因子文件 | `--input-file` | CSV、Parquet，或包含 CSV/Parquet 的目录。 |
| 因子列名 | `--factor-column` | 要排序和交易的数值列；一次运行一个因子。 |
| 行情数据根目录 | `--data-root` | 与因子标的和日期对齐的 Parquet 行情库。 |

`--input-file` 只包含因子信号；`--data-root` 包含回测必须使用的交易日历、价格、mask、benchmark 等市场数据。真实回测不能缺少 `--data-root`。只有 `--test-data` 模式会从内置测试数据的 manifest 自动填充它。

如果用户没有给出这三个输入，Agent 应该询问缺失的文件、路径或列名，不要自动使用测试数据。

因子文件至少需要：

| 列 | 含义 |
| --- | --- |
| `date` | `YYYYMMDD` 整数格式的因子日期。 |
| `ticker` | 可转成整数的标的代码，需要和行情矩阵列名匹配。 |
| 因子列 | 数值越高默认越优；如果数值越低越优，使用 `--reverse`。 |

行情数据根目录需要包含日历、价格、复权因子、交易状态、排除 mask、benchmark 等文件。完整格式见 [references/backtest-contract.md](references/backtest-contract.md)。

## 快速运行

```bash
python3 scripts/run_factor_backtest.py \
  --input-file /path/to/factor.csv \
  --factor-column my_factor \
  --data-root /path/to/BackTestData_pq \
  --timespan 20250101 20250630
```

默认输出目录：

```text
output/run_YYYYMMDD_HHMMSS/
```

常用可选参数：

| 参数 | 作用 |
| --- | --- |
| `--reverse` | 反转因子方向，适用于低值更优的因子。 |
| `--override longx=200` | 设置最多持仓数。 |
| `--override benchmark=benchmark` | 指定 `Benchmark/<name>.parquet`。 |
| `--output-dir <dir>` | 指定固定输出目录；通常不需要。 |
| `--report` | 回测后生成 PDF 诊断报告。 |
| `--optimizer-root <dir>` | 仅用于 `--pure-alpha` 等归因数据；普通回测通常不需要。 |

## PDF 报告

```bash
python3 scripts/run_factor_backtest.py \
  --input-file /path/to/factor.csv \
  --factor-column my_factor \
  --data-root /path/to/BackTestData_pq \
  --timespan 20250101 20250630 \
  --report
```

报告会尽量使用本次回测输出生成核心页面。下面这些输入是可选的；不提供时，对应比较或归因部分会跳过或留空，不会创建占位数据目录：

| 参数 | 用途 |
| --- | --- |
| `--report-stock-price-daily` | 已整理好的 `ticker, tradeDate, openPrice` 日线数据；不提供时可由 `--data-root` 的 `open_price.parquet` 生成。 |
| `--report-comparison-factor-dir` | 因子库目录，用于因子值相关性比较。 |
| `--report-comparison-backtest-dir` | 历史回测结果目录，用于超额收益相关性比较。 |
| `--report-barra-folder` | Barra 或风格暴露目录，用于纯因子收益归因。 |

如果已经有回测结果，也可以单独补生成报告：

```bash
python3 scripts/generate_factor_report.py \
  --run-dir output/run_YYYYMMDD_HHMMSS \
  --factor-name my_factor \
  --factor-file /path/to/factor.csv \
  --data-root /path/to/BackTestData_pq
```

## 输出

核心输出包括：

| 文件 | 含义 |
| --- | --- |
| `stats.csv` | 组合现金、净值、benchmark、hedged NAV、IC、日收益和回撤。 |
| `ICs.csv` | 多个 forward window 的 IC 序列。 |
| `group_ret.csv` / `group_return.png` | 因子分组收益。 |
| `Pnl.png` | 净值、benchmark、hedged NAV 和关键统计。 |
| `transaction.csv` | 成交记录。 |
| `holdings.csv` | 持仓记录。 |
| `<factor>_factor_report.pdf` | 使用 `--report` 时生成的 PDF 诊断报告。 |

## 技能自测数据

只有当用户明确要求“测试技能”或“运行 test data”时，才使用内置测试数据：

```bash
python3 scripts/run_factor_backtest.py --test-data
python3 scripts/run_factor_backtest.py --test-data --report
```

`data/test_data/` 来自 Yahoo Finance 日线数据，只用于验证流程和报告生成，不代表任何真实研究结论。刷新测试数据需要网络：

```bash
python3 scripts/make_test_data.py
```

## 免责声明

本仓库仅作研究方法和回测流程整理，不构成任何投资建议。

## 维护者

创建与维护：`davideliu`（QuantSkills community）。

## License

GPL-3.0. See [LICENSE](LICENSE).
