# 回测与 Shadow Validation

## Walk-forward backtest

回测按时间顺序运行，只使用赛前可获得的信息生成预测，再用赛果更新评估指标，避免未来数据泄漏。

## 指标

- Brier Score: 概率校准误差。
- Log Loss: 对错误高置信预测更敏感。
- ROI: 每单位 stake 的收益表现。
- CLV: 推荐赔率相对收盘赔率的价格优势。
- Max Drawdown: 最大回撤。

## Edge Quality Optimizer

优化器在历史样本上遍历 True Odds / Edge Quality 参数网格，比较 baseline 与 filter 后表现。

## Config grid

配置网格包含 lowerBoundEV、edge score、uncertainty z、method agreement、draw threshold、high odds threshold 等参数。

## Baseline vs True Odds Filter

Baseline 表示原始生产推荐逻辑。True Odds Filter 的目标不是增加推荐数量，而是降低低质量推荐，改善 CLV、ROI 和回撤。

## Blocked recommendation analysis

系统会分析被拦截推荐的赛后表现。如果被拦截样本平均 CLV 或 ROI 更差，说明过滤器有价值。

## Live Shadow Validation

Shadow Validation 在真实赛前比赛上运行候选配置，只写入 `live_shadow_predictions`，不改变生产推荐、stake 或 lifecycle。

## Post-match evaluation

赛后将 shadow prediction 与实际结果、closing SP 对齐，计算 baseline/shadow profit、CLV、hit rate 和 block/pass 表现。

## Promotion Gate

Promotion Gate 只给出建议：

- `ENABLE_FILTER_ONLY_RECOMMENDED`
- `KEEP_SHADOW`
- `NEED_MORE_DATA`
- `REJECT_CONFIG`

即使建议启用，也必须人工执行：

```powershell
.\.venv\Scripts\python.exe -m football_agents.cli activate-filter-only <config_version_id> --confirm
```
