# TASK-M1-003：OCR 领域模型、接口及 RapidOCR 适配器

**里程碑**：M1 单图翻译闭环  
**状态**：已完成  
**优先级**：P0  
**依赖**：TASK-M1-002

## 用户可见结果

用户点击“识别文字”后，画布显示 OCR 区域框，侧栏列出原文、置信度和识别语言；模型不可用时显示可操作错误。

## 实现范围

- 建立 `TextRegion`、多边形坐标、OCR 结果和 `OcrAdapter` 端口。
- 在 `src/infrastructure` 重新实现 RapidOCR 路由适配器，不反向依赖或整体复制原型。
- 将 RapidOCR 原生结果规范化为领域模型，隔离模型加载、脚本路由和错误。
- OCR 调用通过正式后台任务边界执行，UI 主线程只更新状态和覆盖层。

## 预计修改文件

- `src/domain/ocr.py`
- `src/application/ocr.py`、`src/application/ports.py`
- `src/infrastructure/rapidocr_adapter.py`
- `src/ui/image_canvas.py`、`src/ui/main_window.py`
- `tests/unit/test_ocr_models.py`
- `tests/integration/test_rapidocr_adapter.py`
- `tests/ui/test_ocr_action.py`

## 测试与完成标准

```powershell
python -m pytest tests/unit/test_ocr_models.py tests/integration/test_rapidocr_adapter.py tests/ui/test_ocr_action.py -q
```

- 坐标、文本、置信度和语言代码契约稳定，空结果合法。
- 适配器测试不依赖真实客户图片；可用模型走最小真实调用，不可用模型显式跳过或报告。
- OCR 执行期间窗口保持响应，成功后可见真实框和原文。

## 单代理边界

只完成单图 OCR，不执行翻译、擦除或排版。

## 实施结果（2026-07-16）

- 建立 UI 无关的 `Point`、四点多边形、`TextRegion`、置信度状态和 `OcrResult`，RapidOCR 原生结构不泄漏到应用/UI。
- 正式 `RapidOcrAdapter` 接收 RGB/RGBA `ImageDocument`，转换为 BGR 工作数组，规范化文字、坐标和分数；空 OCR 结果是合法结果。
- 25 个客户语言代码均有显式路由：24 个映射到 PP-OCRv6 通用或 PP-OCRv5 西里尔/韩文/泰文/阿拉伯/天城文模型；`bn` 明确报告模型不可用，禁止静默替换。
- 同一模型配置在进程内缓存并串行调用；模型加载和 OCR 由 `QtTaskRunner` 在主线程之外执行。
- 正式窗口可选择 OCR 模型语言，显示红色多边形、原文、置信度、模型语言和耗时；重新导入图片会清除旧 OCR 结果。
- 任务级 7 项测试通过，其中包含真实 PP-OCRv6 英文调用；全仓 99 项测试通过。Windows 产品路径识别 2 个区域并完成原生界面检查。
- 当前 `language_code` 表示用户选择的识别模型语言，不等同于自动语言检测结果。区域级自动语言识别与指定语言筛选在后续正式编排中实现。
