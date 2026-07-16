# TASK-M4-001：桌面激活与系统安全凭据存储

**状态**：已完成（2026-07-16）；真实 Apple Silicon Keychain/GUI 验证归入 TASK-M4-005  
**依赖**：TASK-M3-005、TASK-M3-006

## 目标

让桌面用户输入激活码后经后台任务完成设备激活，并将设备标识和 Bearer 令牌只保存在 Windows Credential Manager 或 macOS Keychain 中；翻译与模型服务在不重启应用的情况下使用新令牌。

## 范围

- 激活领域模型、远程激活接口和应用协调器。
- Windows Credential Manager 与 macOS Keychain 平台适配器，不提供明文文件降级。
- PySide6 激活入口、状态展示、错误反馈和后台执行。
- 翻译与模型清单适配器改为逐次请求安全解析令牌。
- `IMGTRANS_API_TOKEN` 仅保留为开发/自动化覆盖，不写入源码或仓库。

## 验收

- [x] UI 主线程不执行激活网络请求。
- [x] 激活成功后界面不显示令牌，并可立即访问受保护的翻译/模型接口。
- [x] 设备标识和令牌不写入应用数据、缓存、日志或异常文本。
- [x] Windows/macOS 安全凭据适配契约通过隔离自动化测试；当前 Windows 原生临时凭据写入、读取和删除通过。
- [x] 凭据后端不可用时默认关闭，绝不回退到明文文件。

## 预计修改文件

- `src/domain/activation.py`
- `src/application/activation.py`
- `src/infrastructure/activation_client.py`
- `src/platform/credentials.py`
- `src/ui/activation_dialog.py`
- `src/ui/main_window.py`
- `src/main.py`
- `tests/unit/`、`tests/integration/`、`tests/ui/`

## 测试命令

```powershell
python -m pytest tests/unit/test_activation.py tests/unit/test_secure_credentials.py tests/integration/test_activation_client.py tests/ui/test_activation_dialog.py -q
python -m pytest -q
python -m compileall -q src server tests
python -m src --smoke-test
```

## 实际实现

- 新增激活会话、远程客户端和线程安全协调器；设备 ID 与会话按后端地址隔离。
- Windows 使用 Credential Manager generic credential，macOS 使用 Security.framework Keychain generic password；不使用命令行传令牌，不写明文文件。
- 主界面新增“账户 → 激活…”；验证、清除和后续模型检查均经 `QtTaskRunner` 执行。
- 翻译与模型清单在每次请求前解析当前令牌，因此激活后无需重启。开发环境变量仍可显式覆盖。
- 自动回归为 `257 passed`；真实 Apple Silicon 上的 Keychain 授权提示、GUI 和安装包行为随 TASK-M4-005 验收。
