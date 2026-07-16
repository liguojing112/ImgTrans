# TASK-M3-006：管理后台、审计与 M3 集成

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M3-002～005

## 目标

为图片限制、模型、翻译配置状态、激活方案和激活码提供服务端渲染管理界面，并完成 M3 安全与集成收口。

## 范围

- 管理员认证、CSRF 防护、最小权限和安全会话。
- FastAPI 服务端渲染页面与渐进式交互，不建设独立 SPA。
- 写操作审计：管理员、时间、资源、动作和关联 ID，不记录秘密值。
- 配置发布、模型发布/撤回、翻译连通状态、方案与激活码操作页面。
- 后端、桌面契约、迁移、秘密扫描和故障回退集成测试。

## 验收

- [x] 未配置时后台关闭；未登录跳转、错误登录、登录 CSRF、跨会话 CSRF、Cookie 篡改和退出测试通过。
- [x] 管理会话使用 scrypt 密码摘要、HMAC 签名、HttpOnly/SameSite Cookie；生产 Cookie 使用 Secure 并返回 HSTS、CSP、防嵌套和 no-store 头。
- [x] 图片限制、模型发布/撤回、翻译状态/主动连通测试、激活方案/发码/停用和审计页面可用。
- [x] 所有成功的管理页面和 `/v1/admin` 写操作记录管理员、方法/动作、资源、状态、时间和关联 ID，不读取请求正文。
- [x] 页面自动转义；管理页面和 API 不显示完整翻译密钥、对象存储凭据、激活码摘要、设备摘要或设备令牌。
- [x] 明文激活码仍只在创建后的单次 no-store 页面/API 响应显示。
- [x] 登录、激活、翻译、模型清单、客户端配置和非生产管理 API 具备有界进程内限流。
- [x] M3 验收项和完整桌面回归通过。

## 预计修改文件

- `server/admin/`、`server/api/`、`server/infrastructure/`
- `server/templates/`、`server/static/`
- `tests/server/`、`tests/integration/`
- M3 文档

## 实际实现

- 新增 `/admin/login` 及服务端渲染管理后台；模板与静态资源作为 `server.admin` 包数据交付，不建设独立 SPA。
- 管理密码只配置 scrypt 摘要。`python -m server --hash-admin-password` 可交互生成摘要；用户名、摘要和会话密钥必须成组配置。
- 所有管理 POST 表单使用会话绑定 CSRF；登录表单使用独立短期 CSRF Cookie。表单解析限定 URL 编码、64 KiB 和单值字段，不依赖 multipart 上传。
- 生产环境拒绝临时 `IMGTRANS_ADMIN_TOKEN`，只能使用管理员网页登录；该令牌仅保留给非生产 API 自动测试和迁移工具。
- 新增审计表和 `0004_audit_events` 迁移。审计只记录路径，不记录查询串、表单、JSON、授权头或响应正文。
- 翻译连通测试由管理员显式触发，发送固定非敏感短句，页面提示可能产生少量供应商计费。
- 限流器不保存原始 IP/令牌组合，只保存身份 SHA-256。它是单进程防护；多实例生产部署仍需网关或共享限流设施。

## 测试命令

```powershell
python -m pytest tests/server/test_admin_console.py -q
python -m pytest -q
python -m compileall -q src server tests
python -m src --smoke-test
python -m server --smoke-test
```
