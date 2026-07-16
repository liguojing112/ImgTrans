# TASK-M3-002：版本化图片限制与客户端缓存

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M3-001

## 目标

实现图片限制草稿、发布、回滚、读取和客户端“远程→最近有效缓存→内置默认”闭环。

## 范围

- 五项图片限制的领域校验、版本和发布状态。
- PostgreSQL 迁移、仓储、事务和并发发布保护。
- `GET /v1/client-config` 与管理 API 契约。
- 桌面客户端后台拉取、原子缓存和损坏缓存回退。
- 不包含管理后台 HTML 页面。

## 验收

- 边界值、非法组合、发布、回滚和并发测试通过。
- 服务不可用或响应损坏时仍使用最近有效配置；无缓存时使用内置限制。

## 完成结果

- 后端不可变版本模型、SQLite/PostgreSQL 兼容约束、SQLAlchemy 仓储和首个 Alembic 业务迁移已完成。
- 受令牌保护的草稿创建/修改、发布、版本列表和历史回滚 API 已完成；回滚生成新版本，不修改历史记录。
- `/v1/client-config` 返回 schema、配置版本、缓存 TTL 和五项限制，并提供 Cache-Control 与 ETag。
- 桌面端启动时先读取最近有效缓存或内置值，再在后台刷新远程配置；导入和批量任务按每张图片开始时读取当前限制。
- 缓存采用大小限制、严格 schema、临时文件、`fsync` 和原子替换；远程/缓存损坏不会污染上次有效值。
- 完整回归 `198 passed`；编译检查和桌面/服务端双入口烟测通过。

## 预计修改文件

- `server/domain/`、`server/application/`、`server/api/`、`server/infrastructure/`
- `server/migrations/versions/`
- `src/application/`、`src/infrastructure/`
- `tests/server/`、`tests/integration/`

## 实际修改文件

- `server/domain/image_limits.py`
- `server/application/image_limits.py`
- `server/infrastructure/image_limits_repository.py`
- `server/api/image_limits.py`
- `server/migrations/versions/0001_image_limit_versions.py`
- `src/application/image_limits.py`
- `src/infrastructure/image_limits_config.py`
- `src/application/image_io.py`
- `src/main.py`、`src/ui/main_window.py`
- `tests/server/test_remote_image_limits_api.py`
- `tests/unit/test_image_limit_configuration.py`

## 测试命令

```powershell
python -m pytest -q tests/server tests/unit/test_image_limit_configuration.py
python -m pytest -q
python -m src --smoke-test
python -m server --smoke-test
```
