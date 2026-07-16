# TASK-M4-006：发布加固、秘密扫描、版本与回滚

**状态**：待实施  
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
