# TASK-M1-001：正式项目骨架和应用启动入口

**里程碑**：M1 单图翻译闭环  
**状态**：已完成  
**优先级**：P0  
**依赖**：M0 已完成，部分非阻塞验证延期

## 用户可见结果

执行 `python -m src` 打开正式“图片翻译”桌面窗口，显示 M1 单图翻译工作区空状态和应用就绪状态。

## 实现范围

- 建立 `src/domain`、`src/application`、`src/infrastructure`、`src/ui`、`src/platform` 正式分层及组合入口。
- 建立产品信息、启动用例、平台数据/缓存目录和脱敏日志基础。
- 建立最小 PySide6 主窗口和 `python -m src --smoke-test` 自动启动冒烟入口。
- 声明正式运行和测试依赖，不引用 `prototypes/`。

## 预计修改文件

- `pyproject.toml`
- `src/__main__.py`、`src/main.py`
- `src/domain/*`、`src/application/*`、`src/infrastructure/*`、`src/ui/*`、`src/platform/*`
- `tests/unit/*`、`tests/ui/*`、`tests/integration/*`

## 测试与完成标准

```powershell
python -m pytest tests/unit tests/ui tests/integration -q
python -m src --smoke-test
```

- 分层模块可独立导入，领域层不依赖 PySide6、基础设施或原型。
- 平台目录发现与启动用例有单元测试。
- 窗口可在 offscreen 环境创建并关闭，冒烟命令返回 0。
- 不包含 OCR、翻译、修复或图片导入的占位假结果。

## 单代理边界

只建立可运行骨架和真实启动入口；不提前实现后续业务能力。
