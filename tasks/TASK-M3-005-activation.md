# TASK-M3-005：激活方案与激活码基础闭环

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M3-001

## 目标

实现无支付的激活方案、手工发码、单设备绑定、有效期校验和后台停用闭环。

## 范围

- 方案名称、金额最小货币单位、有效期和启停状态。
- 高熵唯一激活码只存不可逆摘要，明文仅创建响应显示一次。
- 原子单设备绑定、过期/停用校验和并发竞争处理。
- 客户端激活验证 API 契约；支付和自动订单发码不包含在内。

## 验收

- [x] 金额以整数最小货币单位保存，拒绝小数；方案修改不改变已发码的有效期快照。
- [x] 单批最多 100 个高熵码且唯一；碰撞时整批回滚并有界重试。
- [x] 两台设备并发绑定同一码时只有一台成功。
- [x] 首次绑定开始计算有效期；过期、单码停用和异设备验证均被拒绝。
- [x] 设备令牌可访问翻译/模型客户端 API，激活过期或停用后立即失效。
- [x] 数据库只保存激活码、设备 ID 和设备令牌的 HMAC-SHA-256 摘要；列表 API 不返回明文或摘要。
- [x] 明文激活码仅在手工创建响应出现一次，响应禁止缓存。

## 预计修改文件

- `server/domain/`、`server/application/`、`server/api/`、`server/infrastructure/`
- `server/migrations/versions/`
- `tests/server/`

## 实际实现

- 新增方案创建、更新和列表 API；金额字段为 `amount_minor`，默认货币代码为 `CNY`，有效期限制为 1～3650 天。
- 新增手工批量发码、码列表和停用 API；方案停用阻止后续发码，但不追溯撤销已发码。
- 新增 `POST /v1/activations/validate`，首次验证原子绑定设备并返回设备 Bearer 令牌。
- 激活码格式使用 32 个去歧义随机字符，熵约 160 bit；服务端 `IMGTRANS_ACTIVATION_SECRET` 作为 HMAC pepper，未配置时激活服务默认关闭。
- 设备 Bearer 令牌接入翻译代理和模型清单的统一客户端鉴权；M3 临时部署令牌仍保留用于部署和自动测试，生产切换在 M3-006 收口。
- 服务端渲染管理页面属于 TASK-M3-006；该页面不得显示明文激活码或数据库摘要。
- 支付、扫码、订单和自动发码未实现。

## 测试命令

```powershell
python -m pytest tests/server/test_activation_api.py -q
python -m pytest -q
python -m compileall -q src server tests
python -m src --smoke-test
python -m server --smoke-test
```
