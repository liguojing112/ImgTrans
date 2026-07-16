# TASK-M4-005：Apple Silicon 真机、签名、公证与安装验证

**状态**：待实施（需要真实 Apple Silicon Mac）  
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

