# TASK-M0-004：LaMa 复杂电商背景修复验证

**里程碑**：M0 技术风险验证
**状态**：实施中（Windows 技术证据完成；macOS arm64 CI 与双人盲评待完成）
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-REPAIR-001～004、FR-MODEL-001
**对应决策**：DEC-002、DEC-015、DEC-017、DEC-024

## 验证目标

验证 LaMa 类本地模型在纯色、渐变、重复纹理、商品边缘和高频复杂背景上的文字移除质量，比较蒙版扩张量、局部裁剪与全图推理，并记录 Windows x64 与 macOS arm64 的 CPU 资源和失败模式。

## 实现范围

- 输入原图和同尺寸二值蒙版，输出同尺寸修复图。
- 擦除蒙版与文字框无关，支持固定扩张、羽化和保护区。
- 对比全图推理与带上下文局部裁剪推理。
- 生成原图、蒙版、修复图、差异图和蒙版外保护区指标。
- 记录加载时间、推理时间、峰值 RSS、模型体积和平台。
- 提供 OpenCV 基础修复作为对照，不建立正式策略路由。
- 不接 OCR、翻译、产品 UI 或批量调度。

## 测试素材

- 纯色、渐变、织物、木纹、网格、重复包装图案、跨商品轮廓文字各至少 5 张。
- 每张图包含精确蒙版、蒙版外保护区和人工关注区域。
- 客户原始验收图仅在有授权的本地测试环境使用，不提交仓库。
- 合成图使用可复现脚本生成，并保留无文字参考背景时用于全参考比较。

## 成功标准

- 输出尺寸、模式和 Alpha 处理符合输入工作图契约。
- 无损合成中蒙版外像素不被修改。
- 有参考背景样本生成 PSNR/SSIM/感知指标；无参考样本生成盲评表。
- 两名内部评审对文字残留、模糊、纹理扭曲、主体变形四项平均评分均不低于 4/5。
- 局部/全图和不同蒙版参数形成量化对比，给出默认策略。
- 模型批次只加载一次，连续三轮无持续内存增长。

## 失败时替代方案

- 简单背景使用 OpenCV 修复，复杂背景切换其他本地修复模型。
- 调整局部上下文、分块重叠、蒙版扩张/羽化，并保留人工蒙版编辑。
- 商品轮廓被破坏时缩小蒙版并优先保护主体，允许用户多次局部修复。
- 当前模型在 macOS arm64 无法运行时使用接口等价的轻量本地模型适配器。

## 预计修改文件

- `prototypes/lama_ecommerce/run.py`
- `prototypes/lama_ecommerce/contracts.py`
- `prototypes/lama_ecommerce/lama_adapter.py`
- `prototypes/lama_ecommerce/opencv_baseline.py`
- `prototypes/lama_ecommerce/mask_variants.py`
- `prototypes/lama_ecommerce/evaluate.py`
- `prototypes/lama_ecommerce/generate_dataset.py`
- `prototypes/lama_ecommerce/prepare_model.py`
- `prototypes/lama_ecommerce/runtime.py`
- `prototypes/lama_ecommerce/model-source.json`
- `prototypes/lama_ecommerce/requirements.lock`
- `prototypes/lama_ecommerce/verify_runtime_evidence.py`
- `.github/workflows/m0-lama-macos-arm64.yml`
- `tests/prototypes/lama_ecommerce/test_lama_contracts.py`
- `tests/prototypes/lama_ecommerce/test_mask_protection.py`
- `tests/prototypes/lama_ecommerce/test_lama_evaluate.py`
- `tests/prototypes/lama_ecommerce/fixtures/manifest.json`

不得修改 `src/`，不得提交大模型权重或未授权客户图片。

## 测试命令

```powershell
python -m pytest tests/prototypes/lama_ecommerce -q
python prototypes/lama_ecommerce/prepare_model.py --config prototypes/lama_ecommerce/model-source.json --output artifacts/m0/lama/models
python prototypes/lama_ecommerce/run.py --manifest tests/prototypes/lama_ecommerce/fixtures/manifest.json --output artifacts/m0/lama/run --model artifacts/m0/lama/models/inpainting_lama_2025jan.onnx
python prototypes/lama_ecommerce/evaluate.py --results artifacts/m0/lama/run/results.json
python prototypes/lama_ecommerce/verify_runtime_evidence.py --results artifacts/m0/lama/run/results.json --expected-machine AMD64 --output artifacts/m0/lama/run/runtime-verification.json
```

## 交付物

- 质量、耗时、内存、模型体积与失败类别报告。
- 默认蒙版和局部/全图策略建议。
- 正式 `InpaintingAdapter` 契约建议。

## 审查边界

审查只评价蒙版驱动的本地背景修复，不评价 OCR 框质量、译文排版或完整产品流水线。

## Windows x64 验证证据（2026-07-16）

- 使用 OpenCV 官方 LaMa ONNX 模型，文件大小 `92,591,623` 字节，SHA-256 为 `7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2`，许可证为 Apache-2.0；权重不提交仓库。
- ONNX Runtime CPU 后端完成 7 类、每类 5 张、共 35 张合成对照图；共生成 91 组策略结果，运行失败为 0。
- 默认策略为 `lama-onnxruntime/local-e2-f0`：局部裁剪、蒙版扩张 2 px、不羽化。默认策略平均 PSNR `34.5028 dB`、SSIM `0.981590`、GMSD `0.111260`；中位推理 `3.63 s`、P95 `4.87 s`、最大 `5.88 s`。
- 模型加载 `6.22 s`、预热 `3.69 s`；三轮复用后的 RSS 为 `728.38/728.38/728.40 MiB`，未观察到持续增长。模型仅创建一个会话，59 次正式推理复用该会话。
- 所有结果均保持蒙版外像素不变，RGBA 样例 Alpha 通道保持不变。
- OpenCV Telea 对照中位推理约 `3.65 ms`，但平均质量明显低于 LaMa；只适合作为简单背景快速兜底，不能替代复杂背景模型。
- 自动指标标记 9/35 张风险样例，主要为规则网格、包装重复纹理、织物和文字跨商品边缘。`product_edge-02` 在蒙版扩张 2/5/8 px 时均出现明显主体边缘伪影，扩大蒙版不能可靠消除。
- Windows 结构证据位于忽略提交的 `artifacts/m0/lama/run-005/`；`runtime-verification.json` 全部检查通过。

## 阶段结论与未完成项

- 技术上可进入正式适配器设计：LaMa 使用独立、可终止、单例复用的 CPU 工作进程；首次使用前异步加载和预热；同一进程内修复任务默认串行。
- 默认采用局部 `e2-f0`，保留可编辑擦除蒙版、保护区和重试。羽化会混回原文字，不作为默认；扩大蒙版会增加主体破坏风险，不得自动无限扩张。
- 不能承诺所有复杂纹理和跨主体边缘图片都由自动修复无痕完成。产品必须允许人工调整、撤销、重试和保留原图；若客户要求“每张全自动无明显变化”，当前方案判定为未达到，应协商改为统计验收并允许人工兜底。
- 仍需 GitHub Actions macOS arm64 运行同一证据验证器，并由两名评审填写 `review-sheet.csv`。这两项完成前，TASK-M0-004 不标记完成。
