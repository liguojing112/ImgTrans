# TASK-M3-004：模型清单、对象存储与客户端更新

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M3-001

## 目标

实现平台模型清单发布以及客户端断点下载、校验、原子安装和旧版回退。

## 范围

- 模型 ID、版本、Windows x64/macOS arm64、大小、SHA-256 和发布状态。
- 管理 API 与 `GET /v1/models/manifest`。
- S3 兼容对象存储端口和短期下载地址适配器。
- 客户端 Range 续传、对象变化检测、哈希校验、原子切换和回退。
- 不把模型权重提交仓库或打入安装包。

## 验收

- [x] 中断后保留可信部分并使用 Range/If-Range 续传。
- [x] 对象版本变化、断点状态缺失或服务端忽略 Range 时安全重下，不重复追加。
- [x] 错误平台、错误大小、错误哈希、磁盘写入失败和旧版回退测试通过。
- [x] 未发布或已撤回模型不出现在客户端清单中；同模型只返回最新已发布目标版本。
- [x] 新文件完成大小与 SHA-256 校验后，才原子安装并替换 `current.json`；失败保留旧指针。
- [x] 模型权重、对象存储凭据和签名 URL 不进入仓库、安装元数据或日志。

## 预计修改文件

- `server/domain/`、`server/application/`、`server/api/`、`server/infrastructure/`
- `server/migrations/versions/`
- `src/application/`、`src/infrastructure/`
- `tests/server/`、`tests/integration/`

## 实际实现

- 服务端新增模型发布领域、SQLAlchemy 仓储、Alembic `0002` 迁移、管理 API 和受客户端令牌保护的清单 API。
- 对象存储保存对象键，S3 兼容适配器按请求生成短期 URL；`boto3` 只属于服务端可选依赖。
- 客户端新增严格清单解析、平台探测、断点身份文件、HTTP Range 下载、完整性校验和文件活动指针。
- 桌面启动优先解析已安装 LaMa 活动版本；配置后端和临时客户端令牌时，在 Qt 后台线程检查并安装模型，不阻塞主线程。
- 新模型在当前重型推理实例未加载前完成安装；为避免热替换正在使用的 ONNX 会话，新版本在下次启动加载。

## 测试命令

```powershell
python -m pytest tests/server/test_model_manifest_api.py tests/unit/test_model_delivery.py tests/integration/test_http_model_download.py -q
python -m pytest -q
python -m compileall -q src server tests
python -m src --smoke-test
python -m server --smoke-test
```
