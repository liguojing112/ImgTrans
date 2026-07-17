# TASK-M4-002：Windows x64/macOS arm64 正式构建与 CI

**状态**：首次 CI 已运行，修复漏提交后端源码问题后待复跑（2026-07-17）
**依赖**：TASK-M4-001

## 目标

建立正式应用而非原型的可重复 Windows 10/11 x64 与 macOS 13+ arm64 构建、测试和安装产物检查。

## 范围与验收

- 固定正式入口、资源、Qt 插件和 OCR/ONNX 原生依赖收集规则。
- GitHub Actions 分别执行 Windows x64 与 macOS arm64 测试、构建、架构和烟雾检查。
- 不包含 Intel Mac、x86_64 macOS 或 Universal 2。
- 产物缺少 Qt 图片插件、架构错误或无法启动时构建失败。

## 预计修改文件

- `pyproject.toml`、正式构建配置、`.github/workflows/`、`scripts/`、`tests/release/`

## 测试命令

```powershell
python -m pytest tests/release -q
python -m src --smoke-test
```

## 实际实现

- 新增正式 `packaging/imgtrans.spec`，只允许 Windows x64 和 macOS arm64 原生构建，入口固定为 `src/__main__.py`。
- RapidOCR 代码/配置、ONNX Runtime、OpenCV 与 Qt 运行时显式收集；所有 `.onnx` 权重排除在安装产物之外，继续经对象存储清单独立安装。
- 正式 RapidOCR 适配器从活动模型仓库解析检测、方向分类和六类识别模型，不依赖依赖包自带权重或第三方直连下载。
- 产物验证覆盖全部 PE/Mach-O 原生文件架构，明确拒绝 macOS Universal/非 arm64 文件；同时检查 JPEG、WebP、GIF、TIFF Qt 插件、OCR/ONNX/OpenCV 运行时、模型权重隔离、工作区路径和敏感模式。
- GitHub Actions 包含 `windows-2022` x64 与已验证为 Apple Silicon 的 `macos-14` 两个原生 job；先跑完整测试，再构建、运行打包后烟雾测试并只上传应用 ZIP。
- 本地未生成安装包；发布契约测试和完整回归为 `269 passed`。任务最终完成状态以工作流两个 job 首次真实通过为准。

## 首次 CI 运行结论

- 2026-07-17 检查运行 `29513386371`：Windows x64 与 macOS arm64 均在完整测试阶段失败，尚未进入打包步骤。
- 对应提交包含 11 个 `tests/server/` 测试文件，但未包含任何 `server/` 正式源码；本地测试通过是因为工作区中仍存在未跟踪的 `server/` 目录。
- 修复要求是将现有 `server/` 正式源码纳入提交，不能通过跳过服务端测试规避；工作流增加必要源码树预检，后续漏提交会在依赖安装前给出明确错误。
- 工作流路径过滤器纳入 `server/**`，后端源码单独变更时也会执行完整发布门禁。
- `actions/checkout` 与 `actions/setup-python` 升级到 Node.js 24 运行时版本，消除首次运行中报告的 Node.js 20 弃用警告。
- 第二次 CI 已确认源码预检与依赖安装通过，但完整测试在收集阶段失败；全新环境复现出测试依赖未完整声明，补充服务端契约测试所需的 `httpx`，以及既有复杂文字、LaMa 原型回归所需的 `python-bidi`、`regex`、`psutil`、`uharfbuzz` 和 `fonttools`。这些库只属于 `test` 可选依赖，不进入正式产品运行时依赖。
- 使用 CI 解析到的最新兼容 FastAPI/Starlette 版本继续回归后，服务端烟雾测试暴露其路由集合包含无 `path` 属性的内部对象；路由契约检查改用稳定的 OpenAPI `paths`，兼容新旧 FastAPI 路由实现。
- 在 Windows x64 与 macOS arm64 两个 job 完成测试、构建、产物校验和上传之前，本任务仍不标记为完成。
