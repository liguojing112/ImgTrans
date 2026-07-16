# TASK-M3-003：翻译代理、安全与桌面接入

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M3-001

## 目标

实现服务端翻译适配器和桌面 API 客户端，使生产模式只通过本项目后端调用 Microsoft Translator。

## 范围

- `/v1/translations` 批量逐项契约、大小限制和稳定错误码。
- Microsoft Translator 供应商代码映射、超时、限流和部分失败适配。
- 凭据只由服务端环境/秘密引用读取，日志和响应不记录授权头或完整正文。
- 桌面客户端 HTTP 适配器、关联 ID 和模拟/服务端模式切换。
- 测试只使用伪供应商，不使用真实密钥和外部计费请求。

## 验收

- 25 种内部语言映射契约通过。
- 超时、429、5xx 和逐项失败不会破坏其他结果。
- 仓库、日志和响应秘密扫描通过，网络契约不含图片。

## 完成结果

- `/v1/translations` 已实现严格批量契约：最多 100 项、单项最多 5000 字符、总计最多 20000 字符、唯一项目 ID 和 25 种内部语言校验。
- 服务端逐项返回成功或稳定失败；供应商全局失败转换为逐项失败，桌面保留对应原文且不擦除。
- Microsoft Translator v3 适配器已完成 25 种语言映射、自动源语言、区域头、关联 ID、响应校验以及 408/429/500/503 有界重试和稳定错误映射。
- Microsoft 密钥只从 `IMGTRANS_TRANSLATOR_KEY` 读取，秘密字段不进入配置 repr、公共摘要、URL、请求正文、日志或响应。
- 代理默认关闭；配置临时客户端令牌后才接受请求。该令牌只用于 M3 开发闭环，M3-005 将替换为设备激活凭据。
- 桌面新增 `mock`/`server` 模式；服务端模式只发送受保护后的文字、语言和项目 ID，不上传图片。
- 所有供应商测试使用伪响应，无真实密钥、外部请求或计费。
- 完整回归 `208 passed`；编译检查及桌面/服务端双入口烟测通过。

## 预计修改文件

- `server/application/`、`server/api/`、`server/infrastructure/`
- `src/infrastructure/`、`src/main.py`
- `tests/server/`、`tests/integration/`

## 实际修改文件

- `server/domain/translation.py`
- `server/application/translation.py`
- `server/infrastructure/microsoft_translator.py`
- `server/api/translation.py`
- `server/config.py`、`server/app.py`
- `src/domain/translation.py`
- `src/application/translation.py`
- `src/infrastructure/server_translation_adapter.py`
- `src/main.py`、`src/ui/translation_panel.py`、`src/ui/main_window.py`
- `tests/server/test_translation_proxy.py`
- `tests/server/test_microsoft_translator.py`
- `tests/integration/test_server_translation_adapter.py`

## 测试命令

```powershell
python -m pytest -q tests/server tests/integration/test_server_translation_adapter.py
python -m pytest -q
python -m src --smoke-test
python -m server --smoke-test
```
