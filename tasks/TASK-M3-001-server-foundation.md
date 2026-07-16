# TASK-M3-001：后端骨架、API 契约与数据库基础

**状态**：已完成（2026-07-16）  
**依赖**：M2 完成

## 目标

建立与桌面客户端隔离的 FastAPI 正式后端包，提供可运行入口、环境配置、版本化路由、关联 ID、统一错误边界和 SQLAlchemy/Alembic 数据库基础。

## 实现范围

- 新建独立顶层 `server/` 包，不让桌面 `src/` 依赖服务端框架。
- 提供存活、就绪和服务信息接口。
- 配置只从环境读取；启动和响应不得回显数据库凭据或翻译秘密。
- 为每个请求接受或生成关联 ID，并在响应头和错误响应中返回。
- 建立 SQLAlchemy 会话工厂和 Alembic 配置，生产目标为 PostgreSQL，测试允许注入 SQLite。
- 本任务不实现翻译、配置发布、模型发布、管理页面或激活码业务。

## 用户可见进展

开发者可独立启动后端并调用 `/health/live`、`/health/ready` 和 `/v1/service-info`，为桌面客户端和部署探针提供稳定入口。

## 预计修改文件

- `pyproject.toml`
- `server/`
- `alembic.ini`
- `tests/server/`
- 相关架构、决策、里程碑和追踪文档

## 验收

- 后端模块入口烟测成功。
- API 契约、关联 ID、环境配置和数据库会话测试通过。
- 完整桌面测试无回归，且 `src/` 不依赖 `server/`。

## 完成结果

- 独立 `server/` 包、`python -m server` 和 `imgtrans-server` 入口已建立。
- `/health/live`、`/health/ready`、`/v1/service-info` 契约已实现。
- 环境配置、关联 ID、统一错误响应、数据库探针/事务和 Alembic 环境已实现。
- 服务端依赖位于 `server` 可选依赖组，不进入桌面默认安装依赖。
- 服务端专项 `14 passed`；完整回归 `186 passed`；桌面与服务端双入口烟测、编译检查通过。

## 测试命令

```powershell
python -m pytest -q tests/server
python -m server --smoke-test
python -m pytest -q
```
