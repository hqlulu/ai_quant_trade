# 美股多空趋势检查

判断美股大盘（标普500、纳斯达克综合、道琼斯工业、罗素2000）当前处于 **多头 / 空头 / 震荡**，
每次运行把结果追加到历史记录，并生成交互式图表报告。

## 运行

```bash
pip install pandas requests
python us_market_trend.py                 # 检查并更新历史与报告
python us_market_trend.py --backfill 60   # 首次运行可补写最近 60 个交易日
python us_market_trend.py --years 10      # 图表展示更长历史
```

输出：
- `history/trend_log.csv`：检查历史记录（同一交易日同一指数只保留最新一次，`checked_at=backfill` 为补写）
- `history/us_market_trend.html`：图表报告（价格 + MA50/MA200 + 多空区间底色 + 每日评分 + 历史记录表）

## 判定规则

每项 +1 / −1，总分 −5 ~ +5；≥ 3 多头，≤ −3 空头，其余震荡。整体趋势取四个指数平均分。

1. 收盘价在 MA200 之上 / 之下
2. MA50 在 MA200 之上（金叉）/ 之下（死叉）
3. MA200 近 20 个交易日向上 / 向下
4. 收盘价在 MA50 之上 / 之下
5. 距 52 周高点回撤 < 10% 记 +1，> 20%（技术性熊市）记 −1，其余 0

数据来源 Yahoo Finance 日线。仅为技术面趋势参考，不构成投资建议。
