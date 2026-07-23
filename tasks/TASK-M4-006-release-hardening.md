# TASK-M4-006：发布加固、秘密扫描、版本与回滚

**状态**：自动化加固完成，商业签名与人工验收待执行（2026-07-23）
**依赖**：TASK-M4-005

## 目标

完成第一阶段发布前的安全、版本、回滚、已知限制和全量验收收口。

## 范围与验收

- 扫描源码、安装产物、日志、崩溃信息和模型清单中的密钥与令牌。
- 固化版本号、兼容性、升级/回滚包和模型独立回滚流程。
- 执行全量自动测试与 Windows/macOS 发布清单，无 P0 缺陷。
- 明确记录艺术字、复杂纹理修复和真实素材质量的已知限制与人工降级路径。

## 预计修改文件

- `src/`、`server/`、`scripts/`、`tests/release/`、现有发布与验收文档

## 测试命令

```powershell
python -m pytest -q
python -m compileall -q src server tests
python -m src --smoke-test
python -m server --smoke-test
```

## 自动化完成项

- 版本一致性、源码和安装产物秘密扫描、目标平台兼容性、发布 ZIP 哈希 manifest 与模型独立回滚契约已实现。
- Windows x64 发布候选已在干净配置目录完成首次启动与重启 smoke test。
- 六张客户图片正式链路全部成功；REVIEW_REQUIRED 与 overflow 多边形像素保护全部通过。
- V1 已知限制、V1.1 候选和人工发布步骤记录在 `RELEASE_NOTES.md`、`MANUAL_ACTIONS.md` 与 release-readiness 报告中。
- Windows 商业签名、macOS Developer ID 签名/公证、真实 Apple Silicon GUI 和客户主观视觉验收仍是人工门禁。
