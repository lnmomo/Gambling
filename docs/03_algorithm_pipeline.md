# 算法流程

核心 EV 公式保持不变：

```text
EV = finalProbability * officialSp - 1
```

## 1. Official SP implied probability

官方 SP 先转换为隐含概率：`impliedProbability = 1 / SP`。三项胜平负的隐含概率通常包含水位。

## 2. De-vig normalization

系统对同一组 1X2 赔率进行去水归一化，得到更接近公平概率的市场概率。

## 3. External market consensus

The Odds API 返回多家博彩公司赔率。系统先对每家公司的胜平负隐含概率去水，再对多家公司的去水概率取平均，形成外部市场共识。

## 4. Pure football model

纯足球模型使用球队历史特征、Elo、预期进球、主客场因素、近期状态等信息生成基础概率。

## 5. Stacking challenger

Stacking 是 challenger 模型，默认不开启。它可以在治理记录中被评估，但不会自动替换 champion。

## 6. Probability calibration

模型概率会进行校准和归一化，避免三项概率不和为 1 或过度自信。

## 7. True Odds Engine

True Odds Engine 对模型概率、官方 SP、外部市场共识和多种去水方法进行比较。默认模式是 FILTER_ONLY，只负责过滤，不替换生产概率。

## 8. Multi-de-vig comparison

系统比较 multiplicative、additive、power、odds-ratio、shin-like、conservative 等方法，判断市场概率估计是否稳定。

## 9. Probability uncertainty

系统估计概率不确定性，用于降低过度自信风险。

## 10. lowerBoundEV

lowerBoundEV 使用保守概率边界重新计算 EV。如果普通 EV 为正但 lowerBoundEV 不足，推荐会被拦截。

## 11. Edge Quality

Edge Quality 将机会分为 HIGH、MEDIUM、LOW、NO_EDGE，并结合方法一致性、赔率桶、联赛可靠性、CLV 历史和模型分歧。

## 12. Adaptive threshold

动态阈值根据市场质量、模型分歧、赔率范围、赛果类型和风险信号调整最低 EV 要求。

## 13. Critic rules

Critic 会检查赔率过期、比赛状态异常、历史样本不足、模型分歧过高、最高 EV 低于动态阈值等原因，最终决定推荐、观察或 NO_BET。

## 14. Bankroll risk control

通过 fractional Kelly、单场上限、日暴露、联赛暴露、结果暴露和相关性风险控制 stake。

## 15. NO_BET

NO_BET 是正常输出，不是失败。它表示当前比赛缺少足够可靠的正期望或风险不可接受。
