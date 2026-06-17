# Demo Script

## 1. Dashboard

- 页面：Dashboard
- 展示重点：今日及未来官方比赛池、系统概览、状态汇总。
- 讲解话术：这里展示系统当前可分析的官方比赛。比赛池会随时间和官方同步任务更新。

## 2. Recommendations

- 页面：Recommendations
- 展示重点：推荐、WATCH、NO_BET 和拦截原因。
- 讲解话术：系统不是强行推荐所有比赛，而是优先过滤低质量机会。

## 3. Match Detail

- 页面：Match Detail
- 展示重点：模型概率、官方 SP、市场共识、True Odds Analysis、Edge Quality、Critic 报告。
- 讲解话术：单场详情能解释为什么推荐或为什么禁止推荐。

## 4. Backtest

- 页面：Backtest
- 展示重点：历史回测、ROI、CLV、Brier、Log Loss、Optimizer。
- 讲解话术：回测用于检验策略质量，但不能代表未来结果。

## 5. Live Monitor

- 页面：Live Monitor
- 展示重点：赔率快照、过期判断、刷新链路。
- 讲解话术：赛前赔率变化很快，系统必须先保证数据新鲜。

## 6. Bankroll

- 页面：Bankroll / Portfolio Risk
- 展示重点：stake 建议、单场上限、日暴露、drawdown mode。
- 讲解话术：即使有正 EV，也必须被资金和组合风险约束。

## 7. System Health

- 页面：System Health
- 展示重点：DB、同步、数据质量、模型治理、Shadow Validation。
- 讲解话术：工程系统要能知道自己什么时候不可靠。

## 8. Settings

- 页面：Settings
- 展示重点：风险配置、真实同步开关、自动下注关闭。
- 讲解话术：自动下注是关闭并禁止的，真实 key 只在本地环境配置。

## 9. Shadow Validation

- 页面：System Health / Agent Monitor / CLI
- 展示重点：Shadow 配置、shadow metrics、promotion decision。
- 讲解话术：新配置先旁路观察，Promotion Gate 只给建议，必须人工 confirm。

## 10. 结束声明

强调：系统不自动下注，不保证盈利。它是概率建模、风险过滤和决策辅助研究平台。
