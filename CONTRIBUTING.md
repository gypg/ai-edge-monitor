# Contributing Guidelines

感谢您对 **边缘 AI 性能监测仪 (ai-edge-monitor)** 的兴趣！本指南帮助您快速参与项目。

## 开发环境

```bash
git clone https://github.com/gypg/ai-edge-monitor.git
cd ai-edge-monitor
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[all,dev]"
pre-commit install
```

## 分支规范

- `main`：稳定分支，所有 PR 合并目标。
- 功能分支命名：`feat/<short-description>`
- 修复分支命名：`fix/<short-description>`
- 文档分支命名：`docs/<short-description>`

## 提交规范

使用 Conventional Commits：

```
feat: 新增 Jetson 功耗探测
fix: 修复 debug_bundle 在 Windows 上的计时问题
docs: 更新 README 中英双语说明
chore: 更新默认仪表盘端口
test: 新增 SysfsPowerSource 设备名选择测试
```

## 开发流程

1. 从 `main` 创建功能分支。
2. 编写或修改代码。
3. 运行测试：
   ```bash
   python -m pytest tests/ integration/ -q
   ```
4. 运行 lint：
   ```bash
   pre-commit run --all-files
   ```
5. 提交 PR，确保 CI 全部通过。

## 测试要求

- 新增功能必须附带单元测试或集成测试。
- 全量测试必须通过：`609 passed, 3 skipped`。
- 关键路径需保持 30s × 100ms 空跑 RSS 增量 < 0.3 MB。

## PR 检查清单

- [ ] 代码已通过 `black` 和 `isort` 格式化
- [ ] `mypy src/` 无新增错误
- [ ] 新增/修改的代码有对应测试
- [ ] README / 文档已同步更新
- [ ] CHANGELOG.md 已更新（如适用）

## 问题反馈

请通过 GitHub Issues 提交 bug 报告或功能请求，尽量包含：

- 运行环境（OS、Python 版本、是否 Docker）
- 复现步骤
- 预期行为 vs 实际行为
- 相关日志或报错信息
