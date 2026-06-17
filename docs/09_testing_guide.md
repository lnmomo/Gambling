# Testing Guide

## 后端测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 前端测试

```powershell
cd frontend
npm test
```

## Build

```powershell
cd frontend
npm run build
```

## Smoke tests

```powershell
.\.venv\Scripts\python.exe -m football_agents.cli init-db
.\.venv\Scripts\python.exe -m football_agents.cli create-shadow-config --name smoke-shadow
```

## Final verification checklist

```powershell
git status
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run build
```

## 当前已通过结果

- Backend: 77 passed
- Frontend: 41 files / 130 tests passed
- Build: passed

## 失败处理

先看第一条失败，不要同时改多个方向。后端失败优先确认 DB 迁移和依赖；前端失败优先确认 `npm install`、TypeScript 类型和测试快照；外部 API 失败优先确认 `.env` 配置和网络。
