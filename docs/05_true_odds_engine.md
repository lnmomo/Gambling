# True Odds Engine

## 为什么需要 True Odds Engine

单一模型概率容易过度自信，单一市场赔率也可能包含噪声、偏差或水位。True Odds Engine 的目标是把模型、官方 SP、外部市场和多方法去水结果放在一起比较，过滤掉不稳健的正 EV。

## Multi-de-vig methods

系统支持并比较多种去水方法：

- multiplicative
- additive
- power
- odds-ratio
- shin-like
- conservative

不同方法的一致性越高，市场公平概率估计越可靠。

## Closing line proxy

Closing line proxy 用于估计临近开赛时市场价格变化，帮助判断推荐是否获得正向 CLV。

## Market bias correction

系统可以对主胜、平局、客胜、赔率桶和联赛可靠性进行偏差修正。

## Probability uncertainty

概率不确定性用于计算保守概率和 lowerBoundEV，避免因为单点估计过高而产生虚假的推荐。

## Draw calibrator

平局通常更难估计，系统对平局可以设置额外阈值或校准逻辑。

## Edge Quality Filter

Edge Quality Filter 汇总 EV、lowerBoundEV、方法一致性、CLV proxy、模型分歧和市场质量，输出 HIGH / MEDIUM / LOW / NO_EDGE。

## Adaptive threshold

动态阈值会随市场质量、模型分歧、风险信号和赔率区间调整推荐门槛。

## 模式区别

- `SHADOW`: 只记录候选配置的影子结果，不影响生产推荐。
- `FILTER_ONLY`: 可以过滤生产推荐，但不替换生产概率。
- `ADJUST_PROBABILITY`: 会改变概率，风险更高，项目默认不启用，也不允许自动激活。

## 为什么不默认 ADJUST_PROBABILITY

概率是整个 EV、stake、critic 和风险控制链路的核心输入。未经长期验证直接调整生产概率，可能放大误差。因此当前交付版只允许 FILTER_ONLY 经过 Shadow Validation 和人工确认后启用。
