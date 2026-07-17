# 图片翻译软件 (Image Translator)

将图片中的文字识别、翻译并渲染回图片中。

## 阶段

- **M0**：已完成，部分非阻塞验证延期
- **M1**：单图翻译闭环完成
- **M2**：批量处理和完整编辑完成
- **M3**：后端、管理后台和激活码基础闭环完成
- **M4**：发布适配进行中

## 快速开始

要求 Python 3.11 和项目声明的依赖。

```powershell
python -m src
```

无交互启动冒烟：

```powershell
python -m src --smoke-test
```

运行测试：

```powershell
python -m pytest -q
```

发布维护者可先进行不产生安装产物的正式构建 dry-run：

```powershell
python -m scripts.build_desktop --target windows-x64 --dry-run
```

正式 Windows x64 和 macOS arm64 构建由 `.github/workflows/m4-desktop-release-build.yml` 在对应原生 runner 执行。构建产物不包含 ONNX 模型权重；OCR 与背景修复模型继续由版本化对象存储清单独立安装。

## 当前可用功能

- 单张 JPG/JPEG、PNG、WebP 导入和画布自适应预览。
- EXIF 方向规范化、文件/宽高/像素安全限制和格式内容校验。
- JPG、PNG、WebP、静态单帧 GIF、单页 TIFF 导出。
- 图片解码和编码在后台任务执行，不阻塞 Qt 主线程。
- RapidOCR 本地文字识别、识别模型语言选择、画布文字框和原文/置信度列表。
- 全部/指定语言筛选、品牌/型号/SKU/网址/数字保护和无密钥模拟翻译结果列表。
- 已翻译区域自动擦除蒙版、LaMa ONNX 本地背景修复、OpenCV 明确降级和蒙版可视化。
- 修复图/原图切换、重新修复、撤销保留原图，以及修复结果五种格式导出。
- 一键执行单图五阶段流水线，显示当前阶段并支持取消。
- 使用合法系统字体进行译文颜色近似、字号拟合、换行、旋转和图像合成；长译文无法容纳时显示溢出提示。
- 自动翻译后可选择译文图层、修改文字并重新排版渲染，支持有界撤销和重做。
- 编辑画布支持指针锚点缩放、中键平移、文字框选择、移动、缩放和旋转；几何操作可撤销和重做。
- “样式”页支持字体、字号、颜色、水平/垂直对齐、换行、描边、阴影和旋转，并可新增或删除文字框；所有操作支持撤销和重做。
- “手动”页可在画布框选漏翻区域，支持自动 OCR/翻译、输入原文后翻译或直接输入最终译文；擦除框与译文框可独立调整，处理结果可整体撤销和重做。
- 已完成正式批量调度内核：路径惰性解码、最多两张活动图片、重型工作流串行、单图失败隔离、批次取消和磁盘结果缓存。
- “批量”页已接入正式调度器：支持多图列表、逐图状态/错误、进度与取消、双击结果预览、成功项勾选，以及 JPG/PNG/WebP/GIF/TIFF 选择性导出。
- “弧形”页支持默认弧线、起点/控制点/终点、反向排列和画布控制点拖动；样式页提供已安装字体推荐及描边、海报、立体阴影近似预设，全部可撤销和重做。
- 未导出的单图编辑或批量成功结果在重新导入、丢弃批次和关闭应用前会显示确认提示；应用不生成可再次打开的项目文件。
- M2 的 100 张混合图片资源测试已通过；该测试覆盖正式调度、真实编解码和结果缓存，不替代真实模型质量验收。
- 高 DPI/Retina 使用逻辑坐标与原图像素坐标分离；系统恢复或网络重新在线后会在后台去重刷新配置、激活和模型状态。
- 图片导出和模型下载/安装具有磁盘空间预检、权限错误脱敏和原子失败保护，不覆盖已有导出文件或旧模型活动版本。

LaMa 模型不随源码提供。开发环境可通过 `IMGTRANS_LAMA_MODEL` 指向已校验模型；未安装模型时应用仍可使用 OpenCV 降级完成本地闭环。

## 后端开发入口

M3 后端与桌面默认依赖隔离。安装服务端可选依赖后运行：

```powershell
python -m server
```

无需监听端口的基础烟测：

```powershell
python -m server --smoke-test
```

当前提供 `/health/live`、`/health/ready` 和 `/v1/service-info`；数据库地址通过 `IMGTRANS_DATABASE_URL` 注入，公共响应不回显该值。

M3 图片限制接口现已提供 `/v1/client-config`。桌面端通过 `IMGTRANS_API_BASE_URL` 配置后端地址，在后台刷新五项限制并将最近有效版本原子缓存；服务不可用时继续使用缓存或内置安全值。图片限制、模型、翻译状态和激活管理均已接入 `/admin` 服务端渲染后台。

服务端翻译模式使用以下非源码环境配置：服务端读取 `IMGTRANS_TRANSLATOR_KEY`、可选区域和非生产 `IMGTRANS_CLIENT_API_TOKEN`；桌面设置 `IMGTRANS_TRANSLATION_MODE=server` 和 `IMGTRANS_API_BASE_URL`，再通过“账户 → 激活…”绑定设备。默认仍为无网络的 `mock` 模式。`IMGTRANS_API_TOKEN` 只保留为开发/自动化覆盖；Microsoft 密钥绝不进入客户端。

模型交付接口现已提供 `/v1/models/manifest` 和模型发布管理 API。服务端对象存储配置通过 `IMGTRANS_OBJECT_STORAGE_ENDPOINT`、`IMGTRANS_OBJECT_STORAGE_BUCKET`、可选区域及访问凭据注入；数据库和响应不回显凭据。桌面设置后端地址并完成设备激活后，会在后台按 Windows x64/macOS arm64 清单续传、校验并原子安装模型，失败继续使用旧版本；新安装模型在下次启动加载。

无支付激活基础 API 已提供方案、手工发码、停用和 `/v1/activations/validate`。服务端必须通过 `IMGTRANS_ACTIVATION_SECRET` 注入至少 32 字符的独立 pepper 才会启用发码和激活；激活码明文只在创建响应显示一次。桌面将设备 ID 和验证成功返回的设备令牌保存到 Windows Credential Manager 或 macOS Keychain，不写入应用数据文件；令牌过期或后台停用后立即失效。真实 Apple Silicon 的 Keychain 与安装包验证在发布阶段完成。

管理员密码摘要可通过以下命令交互生成：

```powershell
python -m server --hash-admin-password
```

部署时分别注入 `IMGTRANS_ADMIN_USERNAME`、`IMGTRANS_ADMIN_PASSWORD_HASH` 和至少 32 字符的 `IMGTRANS_ADMIN_SESSION_SECRET`，然后访问 `/admin/login`。生产环境禁止使用临时 `IMGTRANS_ADMIN_TOKEN`；该变量只保留给非生产自动测试。后台所有写表单使用 CSRF 并写入脱敏审计。当前内置限流按服务进程生效，多实例部署还需在网关配置共享限流。
