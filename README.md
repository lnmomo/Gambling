# 竞彩足球多 Agent 概率决策辅助系统

一个可运行、可审计的胜平负（1X2）概率研究系统，实现策划案中的核心闭环：赔率快照、Elo、Dixon-Coles Poisson、市场去水、概率集成、EV 比较、批判者硬规则、分数凯利、回测指标、REST API 和中文看板。

> 重要：本项目只用于数据分析、课程研究与理性决策参考。不保证收益，不自动购买彩票，不提供追损或倍投能力，不面向未成年人。默认输出是 `NO_BET`。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m football_agents.cli init-db
python -m football_agents.cli seed-demo
python -m football_agents.cli sync-official
python -m football_agents.cli sync-data
python -m football_agents.cli serve
```

打开 `http://127.0.0.1:8000` 查看看板，`http://127.0.0.1:8000/docs` 查看 OpenAPI 文档。

## 官方比赛数据同步

系统通过本机 Microsoft Edge 渲染中国竞彩网公开赛事页面，读取页面中已展示的官方比赛、销售状态与胜平负 SP。默认 60 秒内不会重复抓取，可用以下命令强制刷新：

```powershell
python -m football_agents.cli sync-official --force
```

对应接口为 `POST /api/official/sync`、`GET /api/official/status` 和 `GET /api/official/matches`。浏览器路径、超时和最小同步间隔可在 `.env` 中配置。SP 不完整的比赛仍会进入官方比赛池，但不会写入有效赔率快照，也不会驱动推荐。

本实现只读取公开页面正常渲染的内容，不绕过验证码、登录、访问控制或网站限制。正式长期运行前，应向数据提供方确认授权、频率与使用条款。

## 外部数据与模型

- 外部胜平负赔率：The Odds API。需要在 `.env` 配置 `THE_ODDS_API_KEY`，系统按球队和开赛时间匹配并计算多家机构平均赔率。
- 新闻：优先读取 Google News RSS，GDELT DOC API 作为备用；文章标题、链接、时间和来源置信度会保存到数据库。
- 天气：使用 Open-Meteo 逐小时预报。必须先通过 `PUT /api/matches/{id}/metadata` 保存真实场地经纬度，系统不会根据主队猜测中立场地。
- 模型：只有具备真实 Elo 实力评分及双方预期进球参数时，才生成 Elo + Poisson 基线概率和模型公平赔率（`1 / 概率`）。缺少球队特征时不使用默认参数；只有外部市场赔率匹配成功后，才生成市场校准集成预测、EV 和最终风控信号。模型公平赔率不是对未来庄家开盘值的猜测。

统一同步命令和接口：

```powershell
python -m football_agents.cli sync-data --limit 40
```

```text
POST /api/data/sync
GET  /api/data/status
```

也可以直接使用 Docker：

```powershell
docker compose up --build
```

## 系统结构

```text
football_agents/
  agents/          确定性多 Agent 工作流与审计链
  backtesting/     时间序列回测、Brier、Log Loss、ECE、ROI、回撤
  database/        SQLite schema（表边界可迁移到 PostgreSQL）
  models/          Elo、Dixon-Coles Poisson、市场概率与集成
  risk/            批判者硬规则、四分之一凯利、额度控制
  sample_data/     仅用于功能验证的虚构历史数据
  web/             无构建依赖的中文响应式看板
```

## 决策逻辑

1. 保存官方 SP 与外部市场赔率快照，缺少任一完整 1X2 组即 `NO_BET`。
2. Elo 估计长期实力，Dixon-Coles Poisson 估计比分分布，市场赔率去水后形成市场概率。
3. 默认权重为 Elo 20%、Poisson 45%、市场 35%，输出归一化集成概率。
4. 对三个选项计算 `EV = probability * SP - 1`，选择最高 EV 候选。
5. 批判者检查赔率新鲜度、来源置信度、模型分歧、EV、比赛状态、历史回测、日周暴露及连续亏损。
6. 全部通过才允许 `BET`；正 EV 但未通过为 `WATCH`；其余为 `NO_BET`。
7. 仓位为四分之一凯利，并受单场 1%、单日 3%、单周 8% 硬上限约束。

所有阈值都可通过 `.env.example` 中的环境变量调整。正式使用前应基于真实、合法获得的历史数据完成 walk-forward 验证与概率校准。

## 数据导入与回测

CSV 字段参考 `football_agents/sample_data/historical_matches.csv`：

```powershell
python -m football_agents.cli backtest football_agents/sample_data/historical_matches.csv
```

API 支持 `POST /api/backtest/run`（JSON）和 `POST /api/backtest/upload-csv`。回测严格按日期排序，先用赛前信息预测，再用赛果更新 Elo。

## 数据源边界

项目不内置绕过反爬或访问控制的采集器。生产接入应优先使用授权 API、公开下载、合规 CSV 导入或人工录入，并为每条数据保存来源与时间戳。第三方新闻、天气、xG 与赔率源可通过仓储接口增加适配器，但未经验证的数据不应驱动推荐。

## 测试

```powershell
python -m unittest discover -s tests -v
```

覆盖概率归一化、赔率去水、数据过期 veto、连续亏损暂停、仓位硬上限、缺失数据 `NO_BET`、持久化审计链及样例回测。
