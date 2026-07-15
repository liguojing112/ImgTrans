# TASK-M0-001：Windows x64/macOS arm64 PySide6 启动与打包验证

**里程碑**：M0 技术风险验证
**状态**：进行中（Windows x64 已验证；macOS arm64 GitHub Actions 已实现、首次运行待完成）
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-PLAT-001、FR-PLAT-002、FR-PLAT-004、FR-PLAT-005、NFR-001、NFR-005、NFR-006
**对应决策**：DEC-002、DEC-017

## 验证目标

验证 Python 3.11 + PySide6 以及计划中的原生依赖，能否在 Windows 10/11 x64 和 macOS 13+ Apple Silicon arm64 上完成启动、工作任务、自动测试和打包。Windows 在本地完成构建验证；macOS arm64 在 GitHub Actions 自动构建和测试，后期在真实 Apple Silicon Mac 完成 GUI、签名、公证和安装验证。

## 实现范围

- 独立 `prototypes/platform_bootstrap/` 应用，不引用 `src/`。
- 一个最小主窗口，显示 OS、CPU 架构、Python、Qt、高 DPI 和依赖探测结果。
- 一个模拟耗时工作任务，支持进度、取消和关闭应用时收敛。
- 探测 PySide6、Pillow、OpenCV、RapidOCR 候选推理后端、修复模型候选运行时是否可导入和加载最小会话。
- 提供统一构建脚本，分别生成 Windows x64 与 macOS arm64 目录式原型包。
- 检查打包产物中的 DLL/Mach-O 架构、Qt imageformats 插件和开发机绝对路径。
- 提供 GitHub Actions macOS arm64 自动测试和构建流程，不在仓库中保存证书材料。
- 记录真实 Apple Silicon Mac 的 GUI、签名、公证和安装验证清单，安排在 M4 执行。
- 不实现图片翻译、正式主窗口、自动更新或生产安装器。

## 测试素材

- 64×64 RGB PNG、RGBA PNG 和一张含中文文件名的测试图。
- 固定 3 秒模拟 CPU/IO 工作任务。
- OCR/修复运行时只使用无敏感最小探测资源，不提交大型模型权重。
- Windows 10/11 x64 本地或受控测试机。
- GitHub Actions macOS arm64 runner。
- M4 使用真实 macOS 13+ Apple Silicon Mac 完成 GUI 和安装验证。
- 每个平台记录 CPU、内存、系统版本、Python 与依赖版本。

## 成功标准

- Windows x64 与 GitHub Actions macOS arm64 均能从干净环境安装锁定依赖并通过自动测试。
- RGB/RGBA 和中文路径图片能够由 Qt 插件读取。
- 模拟任务运行时窗口保持响应，取消后 1 秒内不再报告新工作，退出后无残留进程。
- 计划中的原生依赖要么成功加载，要么在报告中给出可验证的替代后端，不存在未记录的隐式缺口。
- Windows x64 和 macOS arm64 目录式原型包构建成功。
- macOS 产物的 Mach-O 依赖均为 arm64，Qt imageformats 插件完整。
- M4 在真实 Apple Silicon Mac 完成 GUI、签名、公证、安装和启动验证。
- 产物扫描不包含密钥、令牌或开发机绝对工作区路径。

## 失败时替代方案

- 为不同平台锁定不同但接口等价的推理后端。
- macOS arm64 缺少 wheel 时评估受维护兼容版本或独立构建该原生依赖。
- 单文件打包失败时保留目录式应用分发，不以单文件为交付门槛。
- 某个模型运行时无法覆盖 Windows x64 与 macOS arm64 时，将其替换为 M0 验证过的等价本地运行时；核心接口保持不变。
- PySide6 本身无法满足目标平台时才提交新的架构决策评估 Qt/C++ 或其他桌面壳，不在本任务内迁移。

## 预计修改文件

- `prototypes/platform_bootstrap/main.py`
- `prototypes/platform_bootstrap/window.py`
- `prototypes/platform_bootstrap/worker_probe.py`
- `prototypes/platform_bootstrap/dependency_probe.py`
- `prototypes/platform_bootstrap/build.py`
- `prototypes/platform_bootstrap/verify_artifact.py`
- `prototypes/platform_bootstrap/requirements.lock`
- `prototypes/platform_bootstrap/packaging/windows.spec`
- `prototypes/platform_bootstrap/packaging/macos.spec`
- `.github/workflows/m0-platform-bootstrap-macos-arm64.yml`
- `tests/prototypes/platform_bootstrap/test_bootstrap.py`
- `tests/prototypes/platform_bootstrap/test_dependency_probe.py`
- `tests/prototypes/platform_bootstrap/fixtures/`
- `prototypes/platform_bootstrap/results/<platform>.json`（生成结果，不提交机器敏感路径）

不得修改 `src/`。

## 测试命令

```powershell
python -m pytest tests/prototypes/platform_bootstrap -q
python prototypes/platform_bootstrap/dependency_probe.py --json
python prototypes/platform_bootstrap/build.py --target windows-x64
python prototypes/platform_bootstrap/verify_artifact.py --target windows-x64
```

```bash
python -m pytest tests/prototypes/platform_bootstrap -q
python prototypes/platform_bootstrap/dependency_probe.py --json
python prototypes/platform_bootstrap/build.py --target macos-arm64
python prototypes/platform_bootstrap/verify_artifact.py --target macos-arm64
```

## 交付物

- 可复现的原型和自动测试。
- Windows x64/macOS arm64 依赖与打包结果 JSON，以及简短结论。
- 对 DEC-002、DEC-017 的保留或替代建议。

## 当前验证结果

2026-07-15 在 Windows x64 / Python 3.11.9 环境完成：

- 自动测试连续三轮通过，最终复验为 11/11 通过。
- PySide6 6.11.1、Pillow 12.3.0、OpenCV 4.13.0 和 PyInstaller 6.19.0 可加载。
- 源码离屏烟雾测试通过，工作任务正常完成。
- Windows x64 目录式打包成功，产物为 255 个文件、约 286.12 MiB。
- PE 架构验证为 Windows x64/AMD64。
- Qt imageformats 包含 JPEG、WebP、TIFF、GIF 等插件。
- 打包后离屏烟雾测试通过，运行时必需依赖无缺失。
- 工作区绝对路径和敏感模式扫描无发现。
- RapidOCR、ONNX Runtime 尚未安装，已按可选候选记录；由 TASK-M0-002 选择并验证。
- PyTorch 2.6.0 CPU 可加载，但未纳入 UI profile 打包；由 TASK-M0-004 决定修复运行时。
- GitHub Actions macOS arm64 工作流已实现，固定使用 `macos-14` runner，包含架构确认、自动测试、依赖探测、PyInstaller 构建、产物验证、临时签名校验、`.app` 归档和 artifact 上传；本地工作区尚未推送，因此暂无首次 CI 运行结果。

结果文件：

- `prototypes/platform_bootstrap/results/windows-x64-dependencies.json`
- `prototypes/platform_bootstrap/results/windows-x64-source-smoke.json`
- `prototypes/platform_bootstrap/results/windows-x64.json`
- `prototypes/platform_bootstrap/results/windows-x64-verification.json`

下一步是在代码推送后取得 GitHub Actions macOS arm64 首次成功运行证据。真实 Apple Silicon Mac 的 GUI、签名、公证和安装验证归入 M4，不作为 M0 自动构建任务的前置条件。

## 审查边界

审查只关注 Windows x64/macOS arm64 启动、任务生命周期、依赖加载、GitHub Actions 自动构建和原型打包；不审查正式 UI 设计或图片翻译功能。一个代理可以独立完成代码与 CI，真实 Apple Silicon GUI/安装验证在 M4 由平台测试执行。
