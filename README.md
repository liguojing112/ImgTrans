# 图片翻译软件（ImgTrans）

图片翻译与商品文案工具：识别图片文字 → 翻译 → 回填；上传商品图片 → AI 分析 → 生成多语言文案。

## 功能

- **图片翻译**：OCR 识别图片文字（内置 RapidOCR 模型），服务端代理翻译（微软 Translator），背景修复（内置 LaMa 模型），译文回填渲染。
- **商品详情生成**：上传商品图片，AI 视觉分析（GLM，服务端代理）提取信息，生成多语言标题、卖点、详情文案。
- **套餐与支付**：时长包 / 次数包 / 组合包，微信扫码购买与续购，续购叠加到原激活码。
- **激活体系**：激活码一机一码、设备绑定、自助解绑换机、后台停用/启用。
- **管理后台**：套餐、订单、激活码、图片限制、翻译服务配置、账号权限、审计日志（中文界面）。
- **OCR/修复模型内置**：模型打进安装包，客户开箱即用，无需联网下载。

## 架构

```
客户端（PySide6 桌面应用，Win x64 / macOS arm64）
    │  激活 / 翻译 / 商品详情 / 支付 均通过 API
    ▼
服务端（FastAPI，Clean Architecture）
    ├─ 微软 Translator（翻译）
    ├─ GLM 智谱（商品详情，OpenAI 兼容代理）
    ├─ 微信支付 Native（下单/回调）
    └─ PostgreSQL + Alembic 迁移
```

- 客户端不持有任何密钥，翻译/商品详情/支付均由服务端代理。
- 服务端依赖客户配置：微软翻译密钥、GLM API、微信商户号。

## 客户端构建

要求 Python 3.11 与项目依赖。

```powershell
# 正式 Windows x64 构建（含内置模型 + 文件日志）
python -m scripts.build_desktop --target windows-x64
```

默认输出：`dist/release-candidate/windows-x64/ImgTrans`。

制作 Inno Setup 安装包（需本机安装 Inno Setup 6）：

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\imgtrans_installer.iss
```

产物：`dist/installer/ImgTrans-Setup-<version>.exe`（简体中文向导，LZMA2 压缩）。

运行测试：

```powershell
python -m pytest -q
```

## 服务端部署

服务端通过环境变量注入配置，关键项：

| 变量 | 用途 |
|------|------|
| `IMGTRANS_DATABASE_URL` | PostgreSQL 连接 |
| `IMGTRANS_ADMIN_USERNAME` / `IMGTRANS_ADMIN_PASSWORD_HASH` / `IMGTRANS_ADMIN_SESSION_SECRET` | 后台超管 |
| `IMGTRANS_ACTIVATION_SECRET` | 激活码签名（≥32 字符） |
| `IMGTRANS_TRANSLATOR_KEY` / `IMGTRANS_TRANSLATOR_REGION` | 微软翻译 |
| `IMGTRANS_SETTINGS_ENCRYPTION_KEY` | 后台第三方配置加密 |

微信支付、GLM 密钥在后台「第三方配置」页面配置（加密存储）。

```powershell
python -m server            # 启动服务
python -m server --smoke-test
```

数据库迁移：`alembic upgrade head`。

## 目录结构

```
src/       客户端（PySide6 + 领域/应用/基础设施分层）
server/    FastAPI 服务端（domain/application/infrastructure/api/admin）
packaging/ PyInstaller spec + Inno Setup 安装脚本
scripts/   构建/验证脚本
tests/     测试
docs/      需求与决策文档
```
