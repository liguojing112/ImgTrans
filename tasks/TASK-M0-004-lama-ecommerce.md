# TASK-M0-004：LaMa 复杂电商背景修复验证

**里程碑**：M0 技术风险验证
**状态**：待开始
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-REPAIR-001～004、FR-MODEL-001
**对应决策**：DEC-002、DEC-015、DEC-017

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
- `tests/prototypes/lama_ecommerce/test_contracts.py`
- `tests/prototypes/lama_ecommerce/test_mask_protection.py`
- `tests/prototypes/lama_ecommerce/test_evaluate.py`
- `tests/prototypes/lama_ecommerce/fixtures/manifest.json`

不得修改 `src/`，不得提交大模型权重或未授权客户图片。

## 测试命令

```powershell
python -m pytest tests/prototypes/lama_ecommerce -q
python prototypes/lama_ecommerce/run.py --manifest tests/prototypes/lama_ecommerce/fixtures/manifest.json --output artifacts/m0/lama
python prototypes/lama_ecommerce/evaluate.py --results artifacts/m0/lama/results.json
```

## 交付物

- 质量、耗时、内存、模型体积与失败类别报告。
- 默认蒙版和局部/全图策略建议。
- 正式 `InpaintingAdapter` 契约建议。

## 审查边界

审查只评价蒙版驱动的本地背景修复，不评价 OCR 框质量、译文排版或完整产品流水线。
