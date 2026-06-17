# Runbook

## 1. Clone repo

```powershell
git clone <repo-url>
cd Gambling
```

## 2. 创建 venv

```powershell
C:\Users\86186\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv
```

## 3. 安装后端

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 4. 安装前端

```powershell
cd frontend
npm install
cd ..
```

## 5. 配置环境

```powershell
Copy-Item .env.example .env
```

只在 `.env` 中填真实 key，不提交。

## 6. 初始化 DB

```powershell
.\.venv\Scripts\python.exe -m football_agents.cli init-db
```

## 7. 导入 sample historical data

```powershell
.\.venv\Scripts\python.exe -m football_agents.cli import-history football_agents\sample_data\historical_matches.csv
```

如果 sample 文件不存在，可先运行测试或使用自己的合法 CSV。

## 8. 启动后端

```powershell
.\.venv\Scripts\python.exe -m football_agents.cli serve
```

## 9. 启动前端

```powershell
cd frontend
npm run dev
```

## 10. 打开页面

- `http://127.0.0.1:8000/dashboard`
- Vite dev server printed URL
- `http://127.0.0.1:8000/docs`

## 11. Health

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 12. Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run build
```

## 常见问题

- 端口 8000 被占用：`serve --port 8001`。
- PowerShell Activate.ps1 不允许：不需要 activate，统一使用 `.\.venv\Scripts\python.exe -m ...`。
- `THE_ODDS_API_KEY` 缺失：真实外部赔率同步不可用，但本地测试仍可运行。
- DB dirty：删除本地 `data/runtime/*.db` 后重新 `init-db`，不要提交 DB。
- frontend build error：先运行 `npm install`，确认 Node 版本和 lockfile 一致。
