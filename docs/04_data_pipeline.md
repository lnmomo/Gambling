# 数据流程

## 官方赛程 / SP

官方比赛池和 SP 快照用于构建生产赛前判断。系统会记录来源、抓取时间和快照有效性，过期或不完整赔率不会驱动有效推荐。

## The Odds API 外部赔率

外部赔率通过 `THE_ODDS_API_KEY` 配置。系统获取市场事件和多家博彩公司 1X2 赔率，并进行赛事匹配、去水和共识概率计算。

## pandas historical pipeline

历史数据由 pandas 管道处理，用于构建真实球队特征、回测和优化器样本。项目不依赖 soccerdata。

## football-data.co.uk CSV

`sync-history` 支持 football-data.co.uk CSV 增量归档。国家队历史可通过 `sync-international-history` 补充。

## 数据清洗

导入时会识别并报告：

- `missing_date`
- `invalid_date`
- `bad_score`
- `same_team`
- `duplicate_match`
- `future_match`

## 数据质量报告

数据质量结果进入导入报告和 health 信息，用于判断当前数据是否足以生成可信推荐。

## Import audit

关键导入、去重、异常和任务运行会写入审计或任务记录，便于复盘。

## Runtime data policy

不要提交真实运行数据：

- `.env`
- `api.env`
- `data/runtime`
- `data/cache`
- `data/raw`
- `data/logs`
- real `.db` / `.sqlite`

Sample 数据可以提交，用于演示和测试。
