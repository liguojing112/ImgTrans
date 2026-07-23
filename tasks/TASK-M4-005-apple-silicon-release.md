# TASK-M4-005：Apple Silicon 真机、签名、公证与安装验证

**状态**：构建流程已准备，等待真实 Apple Silicon Mac、签名和公证验证（2026-07-23）
**依赖**：TASK-M4-002～TASK-M4-004

## 目标

在真实 macOS 13+ Apple Silicon 设备上完成 GUI、Keychain、模型、签名、公证、安装、升级和卸载验收。

## 范围与验收

- 自动化先由 GitHub Actions macOS arm64 执行；真机只承担无法由 CI 证明的系统集成。
- 验证 Gatekeeper、Keychain、首次模型下载、Retina、文件对话框和安装生命周期。
- 无 P0 缺陷，签名和公证检查通过；问题证据只收集发布所需内容，不要求普通中间 Artifact。

## 预计修改文件

- `.github/workflows/`、签名/公证脚本、`tests/release/`、发布检查记录

## 测试命令

```bash
python -m pytest tests/release -q
codesign --verify --deep --strict --verbose=2 ImgTrans.app
spctl --assess --type execute --verbose=2 ImgTrans.app
```

## 当前结论

- `macos-arm64` 是唯一 macOS 构建目标，最低系统版本为 macOS 13。
- PyInstaller spec、GitHub Actions 原生架构门禁、Mach-O 架构检查、Qt/ONNX/OpenCV/RapidOCR 资源检查、临时签名检查和发布 manifest 已具备。
- 不包含 Intel Mac、x86_64 macOS 或 Universal 2。
- 构建流程已准备，但未在真实 macOS Apple Silicon 设备验收。
- Developer ID 签名、公证、Gatekeeper、Keychain、Retina、文件对话框、模型下载和安装生命周期仍需按 `MANUAL_ACTIONS.md` 人工执行。

