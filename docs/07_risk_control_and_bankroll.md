# Risk Control and Bankroll

## Kelly / fractional Kelly

系统可以用 Kelly 思路估算理论 stake，但实际使用 fractional Kelly 降低波动。

## Max single bet

单场 stake 有硬上限，防止单一比赛暴露过高。

## Daily exposure

单日总暴露有限制，避免同一天过度集中。

## League exposure

联赛暴露限制用于减少同一数据环境或市场结构导致的集中风险。

## Outcome exposure

系统可以限制同一结果方向，例如过度集中在平局或客胜。

## Correlation risk

同时间、同联赛、同类型推荐可能高度相关，需要组合层面的风险控制。

## Drawdown modes

- `NORMAL`: 正常模式。
- `CAUTION`: 降低 stake。
- `DEFENSIVE`: 更严格限制。
- `PAUSED`: 暂停推荐。

## StakeRecommendation

StakeRecommendation 是风控建议，不代表真实下注指令。

## 声明

系统不自动下注，不代表真实下单。资金风控用于研究和决策辅助，不能消除损失风险。
