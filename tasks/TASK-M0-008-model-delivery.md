# TASK-M0-008：模型下载、续传、校验和更新验证

**里程碑**：M0 技术风险验证
**状态**：待开始
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-MODEL-002～005、NFR-001、NFR-007
**对应决策**：DEC-010、DEC-011

## 验证目标

验证 S3 兼容对象存储模型分发协议，包括平台/架构清单、Range 断点续传、大小与 SHA-256 校验、临时安装、原子切换、旧版回退和敏感下载地址脱敏。

## 实现范围

- 使用本地故障注入 HTTP 服务或隔离测试桶，不连接生产对象存储。
- 最小清单字段：model_id、version、platform、arch、url、size、sha256。
- 分块下载到临时文件，保存断点状态；支持进程退出后续传。
- 校验大小和 SHA-256，通过后安装到版本目录并原子更新 current 指针/元数据。
- 注入断网、超时、错误 Range、对象改变、错误大小、错误哈希、错误架构、磁盘不足和路径穿越。
- 更新失败继续返回上一可用版本。
- 日志对签名 URL 查询参数、授权头和本地敏感路径脱敏。
- 不实现正式后台页面、真实模型发布或客户端 UI。

## 测试素材

- 10 MB、100 MB 和接近预计模型规模的生成文件，不使用真实权重。
- 正确/错误大小、哈希、平台和架构清单。
- 支持 Range、不支持 Range、忽略 Range 和中途改变 ETag/内容的测试端点。
- 已安装 v1、准备更新 v2、损坏 v2 和磁盘不足场景。
- 路径穿越与恶意 model_id/version 输入。

## 成功标准

- 中断并重启后从可信位置续传；远端对象变化时丢弃旧断点并安全重下。
- 不支持可靠 Range 时整文件重下，不发生重复追加。
- 错误大小、哈希、平台或架构的文件永不进入可用目录。
- 新版本只在完整校验后切换；失败时 v1 继续可用。
- model_id/version 不能逃逸模型根目录。
- 磁盘不足产生可恢复错误且不破坏旧版本。
- 日志和测试报告不含完整签名 URL、令牌或授权头。

## 失败时替代方案

- Range 不可靠时采用整文件下载，保留临时目录、完整校验和原子切换。
- 单文件过大时由发布端生成固定分块和逐块哈希。
- 对象存储访问控制不足时由后端返回短期签名 URL 或代理清单访问。
- current 指针在某平台不能原子替换时使用原子元数据文件和启动时恢复协议。
- 断点状态复杂度过高时安全重下优先于不可信续传。

## 预计修改文件

- `prototypes/model_delivery/run.py`
- `prototypes/model_delivery/contracts.py`
- `prototypes/model_delivery/manifest.py`
- `prototypes/model_delivery/downloader.py`
- `prototypes/model_delivery/installer.py`
- `prototypes/model_delivery/recovery.py`
- `prototypes/model_delivery/fault_server.py`
- `tests/prototypes/model_delivery/test_manifest.py`
- `tests/prototypes/model_delivery/test_resume.py`
- `tests/prototypes/model_delivery/test_integrity.py`
- `tests/prototypes/model_delivery/test_atomic_update.py`
- `tests/prototypes/model_delivery/test_path_safety.py`
- `tests/prototypes/model_delivery/fixtures/manifest.json`

不得修改 `src/`，测试凭据只能通过环境变量注入且不得写入报告。

## 测试命令

```powershell
python -m pytest tests/prototypes/model_delivery -q
python prototypes/model_delivery/run.py --scenario all --output artifacts/m0/model-delivery
```

## 交付物

- 故障注入测试结果和恢复状态图。
- 模型清单、安装目录和版本切换契约建议。
- 对 DEC-011 的保留或替代建议。

## 审查边界

审查只评价模型文件分发、完整性、安装和回退，不包含模型推理、生产对象存储部署或管理后台 UI。
