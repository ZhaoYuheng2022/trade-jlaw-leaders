# 数据格式

## prices.csv

UTF-8 长表，每行一个交易日的一只证券：

```csv
theme,symbol,date,open,high,low,close,volume
AI,AAA,2025-01-02,100,102,99,101,1200000
AI,AAA,2025-01-03,101,103,100,102,1350000
AI,BBB,2025-01-02,50,51,49,50,3000000
AI,BBB,2025-01-03,50,50,48,49,2800000
```

要求：

- `theme`：题材名称；一次运行只分析一个题材。
- `symbol`：题材内唯一证券代码。
- `date`：`YYYY-MM-DD`。
- `open/high/low/close`：使用一致的前复权或后复权价格，不能混用未复权价格。
- `volume`：与价格口径匹配的成交股数；脚本以 `close × volume` 估算成交额。
- 每只股票至少 220 个有效交易日，且最新日期必须与题材当前截止日期一致，否则排除并说明。

不处理缺失 K 线插值、公司行动或实时行情。输入前必须完成数据清洗。历史回测还需当时题材成分、退市股票和当时指数成分，防止幸存者偏差。

## relevance.csv（可选）

```csv
symbol,name,relevance,note
AAA,示例公司,90,年报披露相关收入占比
BBB,观察公司,50,仅有产品合作，收入贡献待核实
```

- `relevance`：0–100，是使用者基于证据输入的相关性标签，不由脚本计算，也不进入默认价格评分。
- `note`：简短证据说明；正式报告还应给来源和日期。
- 未提供此文件时，结果只能称为“价格领导力候选”，不能声称题材相关性已经核验。

## rank_leaders.py

```bash
python scripts/rank_leaders.py \
  --prices prices.csv \
  --theme AI \
  --metadata relevance.csv \
  --top 3 \
  --min-dollar-volume 2000000 \
  --output leaders.json
```

`--no-trend-gate` 可关闭默认趋势门槛用于对照研究。输出包括候选指标、排除原因和警告。

## plan_trade.py

```bash
python scripts/plan_trade.py \
  --equity 100000 \
  --risk-pct 0.5 \
  --entry 50 \
  --stop 47 \
  --target 60 \
  --max-position-pct 20 \
  --lot-size 1
```

输出风险预算、理论股数、仓位上限后的实际股数、止损距离和目标 R。脚本不获取行情、不发送订单，也不模拟跳空和交易成本。
