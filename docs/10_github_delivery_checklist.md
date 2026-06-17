# GitHub Delivery Checklist

提交前检查：

1. `git status` 确认只包含准备提交的文件。
2. `.env` 未提交。
3. `api.env` 未提交。
4. DB 未提交。
5. `data/runtime` 未提交。
6. `data/cache`、`data/raw`、`data/logs` 未提交。
7. `node_modules` 未提交。
8. 后端测试通过。
9. 前端测试通过。
10. 前端 build 通过。
11. README 已更新。
12. docs 已更新。
13. 风险声明存在。
14. 没有待办占位词。
15. 算法代码没有非确定性随机数调用。
16. 没有夸大收益或必胜类表述。
17. `ENABLE_AUTO_BETTING=false`。
18. tag 版本。

建议命令：

```powershell
git status
.\scripts\check-final.ps1
git add README.md docs scripts .env.example .gitignore
git commit -m "docs: finalize project delivery documentation"
git tag v1.0-core-complete
git push origin main
git push origin v1.0-core-complete
```

不要让脚本自动 commit。最终提交由用户手动执行。
