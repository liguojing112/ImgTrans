# TASK-M0-002：RapidOCR 25 种语言验证

**里程碑**：M0 技术风险验证
**状态**：进行中（验证框架和 Windows 路由加载已完成；25 语种标注集准确率与 macOS arm64 运行待验证）
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-OCR-001～007、FR-MODEL-001、NFR-006
**对应决策**：DEC-002、DEC-012

## 验证目标

验证 RapidOCR 检测与识别路径对正式 25 种语言的覆盖范围，确定是否需要按脚本/语言路由多个识别模型，并验证统一坐标、置信度、语言判定、模型复用和 CPU 性能接口。

## 实现范围

- 独立命令行原型，不建立产品 UI。
- 输入图片、候选源语言和模型配置，输出统一 JSON：四点多边形、文本、置信度、内部语言代码和模型 ID。
- 检测器与识别器通过原型适配器隔离，允许测试多个模型组合。
- 支持模型按批次复用，不允许每图重复初始化。
- 为每种语言计算检测召回率、字符准确率、加载时间、单图耗时和峰值 RSS。
- 生成检测框、文本、语言和置信度可视化图。
- 对低置信和不支持语言显式报告，不执行翻译或擦除。
- 不实现正式模型下载、编辑器或完整翻译流水线。

## 测试素材

- 25 种语言各至少 20 个标注文字区域，覆盖清晰印刷体、小字、旋转、低对比和复杂背景。
- 中英、拉丁/阿拉伯、数字/网址等混合脚本图片。
- 空白图、损坏图、极低置信图、品牌名、型号、SKU、网址和纯数字图。
- `manifest.json` 记录语言代码、转录、区域、许可和预期脚本。
- 合成素材只使用许可允许分发且覆盖目标字形的字体。

## 成功标准

- 25 种语言均能映射到明确的本地识别路径；不支持项被报告，不静默使用错误模型。
- 清晰印刷体集合达到检测召回率和字符准确率各 90% 的工程基线；未达标语言形成独立路由或降级建议。
- 四点区域可正确映射到规范化原图，倾斜框顶点顺序稳定。
- 同一模型批次只初始化一次，连续三轮无持续阶梯式 RSS 增长。
- 生成逐语言指标、失败样本和模型体积报告。
- 原型模块不导入 PySide6，不调用翻译或修复模块。

## 失败时替代方案

- 共用文字检测器，按脚本路由多个 RapidOCR 兼容识别模型。
- 对短文本/混合脚本使用候选语言集合和人工指定语言兜底。
- 自动语言识别低置信时保留原区域，不进入擦除。
- 若某个模型运行时只在部分平台可用，交由平台适配器选择等价后端；不得改为云 OCR。

## 预计修改文件

- `prototypes/rapidocr_multilingual/run.py`
- `prototypes/rapidocr_multilingual/contracts.py`
- `prototypes/rapidocr_multilingual/adapter.py`
- `prototypes/rapidocr_multilingual/model_router.py`
- `prototypes/rapidocr_multilingual/evaluate.py`
- `prototypes/rapidocr_multilingual/visualize.py`
- `prototypes/rapidocr_multilingual/model-config.json`
- `prototypes/rapidocr_multilingual/requirements.lock`
- `tests/prototypes/rapidocr_multilingual/test_contracts.py`
- `tests/prototypes/rapidocr_multilingual/test_router.py`
- `tests/prototypes/rapidocr_multilingual/test_adapter.py`
- `tests/prototypes/rapidocr_multilingual/test_evaluate.py`
- `tests/prototypes/rapidocr_multilingual/fixtures/manifest.json`

不得修改 `src/`，不得提交模型权重或无授权字体。

## 测试命令

```powershell
python -m pytest tests/prototypes/rapidocr_multilingual -q
python prototypes/rapidocr_multilingual/run.py --manifest tests/prototypes/rapidocr_multilingual/fixtures/manifest.json --output artifacts/m0/rapidocr
python prototypes/rapidocr_multilingual/evaluate.py --results artifacts/m0/rapidocr/results.json
```

## 当前验证结果（2026-07-15）

- 已实现与 UI 解耦的命令行验证框架、统一四点区域契约、模型路由、延迟/RSS/准确率评估、可视化和模型文件体积清单。
- 25 个内部语言代码均有显式路由状态；24 种映射到六类本地识别配置，孟加拉语因 RapidOCR 3.9.1 官方模型表无明确识别路径而显式报告为未覆盖，不会错误使用天城文模型。
- Windows x64 已验证 `PP-OCRv6 multilingual small`、`PP-OCRv5 cyrillic/korean/thai/arabic/devanagari mobile` 六类配置均能初始化并执行；每类模型在同一适配器实例中只初始化一次。
- 官方中文样例识别得到 18 个区域，区域契约和低置信/脚本不匹配状态输出正常；该样例只属于运行时烟雾测试，不替代逐语言准确率验收。
- RapidOCR 阿拉伯路径需要未被主包硬依赖覆盖的 `python-bidi`，已在原型锁文件中显式固定。
- 为保留 macOS 13 arm64 安装能力，原型暂锁 `onnxruntime==1.23.2`；更新版本前必须重新检查 wheel 的最低 macOS 版本。
- 已通过 pip 跨平台解析确认锁文件中的八个直接依赖均有兼容 macOS 13 arm64 的 wheel；OpenCV 固定为与 NumPy 1.26.4 兼容的 4.11.0.86，实际导入、推理和打包仍须由 macOS arm64 CI 验证。
- 已新增 GitHub Actions `macos-14` arm64 工作流，自动运行测试、RapidOCR 自检和六类模型加载并上传运行证据；首次运行仍待代码推送。
- 合同 fixture 仅验证工具链，不作为 OCR 准确率证据。正式完成仍需 25 语种各至少 20 个授权标注区域、三轮 RSS 测试和 macOS arm64 CI 结果。

## 交付物

- 25 种语言逐项覆盖矩阵和指标报告。
- 推荐模型路由配置与失败样本可视化。
- 对 DEC-012 以及正式 OCR 适配器接口的建议。

## 审查边界

审查只评价本地 OCR 覆盖、坐标、模型路由和指标可靠性，不评价翻译质量、背景修复或产品 UI。
