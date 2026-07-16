# TASK-M1-006：单图处理编排与最小 PySide6 操作界面

**里程碑**：M1 单图翻译闭环  
**状态**：已完成（2026-07-16）  
**优先级**：P0  
**依赖**：TASK-M1-001～005

## 用户可见结果

用户可在一个正式窗口完成“导入 → OCR → 语言筛选 → 模拟翻译 → 保护词 → 擦除 → LaMa 修复 → 基础排版 → 预览 → 导出”的单图闭环，并看到阶段进度、取消和错误。

## 实现范围

- 建立单图任务状态机、阶段结果、取消令牌和 `TranslateImage` 应用编排。
- 实现基础文字框字号拟合、换行、颜色/位置近似和图层合成；复杂艺术字留给 M2 人工编辑。
- 将各正式端口通过组合根注入，不让 UI 直接调用 RapidOCR、翻译器或 LaMa。
- 使用 Qt 后台协调和可终止推理进程，保证主线程只处理视图更新。
- 接入完整最小界面、原图/结果切换、失败重试和最终格式导出。

## 预计修改文件

- `src/domain/job.py`、`src/domain/layout.py`
- `src/application/translate_image.py`（复用已有正式导出用例）
- `src/infrastructure/text_renderer.py`、`src/platform/fonts.py`（复用已有 Qt 后台任务与 LaMa 推理进程）
- `src/ui/main_window.py`、`src/ui/image_canvas.py`、`src/ui/pipeline_panel.py`
- `tests/unit/test_image_job.py`、`tests/unit/test_basic_layout.py`
- `tests/integration/test_single_image_workflow.py`
- `tests/ui/test_single_image_workflow.py`

## 测试与完成标准

```powershell
python -m pytest tests/unit/test_image_job.py tests/unit/test_basic_layout.py tests/integration/test_single_image_workflow.py tests/ui/test_single_image_workflow.py -q
```

- 使用确定性 OCR/翻译/修复测试替身时完整闭环可重复通过，正式适配器另有契约测试。
- 非目标或受保护区域不进入擦除；单区域错误可见且不会静默破坏图片。
- 执行、取消和导出期间窗口保持响应，结果图片可重新打开。

## 单代理边界

只完成单图最小闭环；批量、完整文字编辑、弧形字和项目级历史属于 M2。

## 完成记录

- 新增顺序受控的单图任务状态机、五阶段进度、线程安全取消令牌和 `TranslateImage` 编排用例。
- “自动”页可一键执行 OCR、语言筛选/保护词、模拟翻译、背景修复、字号拟合、换行、旋转渲染和预览；结果沿用正式五格式导出。
- Qt 离屏排版使用平台已安装的合法字体，支持 Unicode shaping/BiDi 基础能力；字体不可用时明确失败，不静默导出空译文。
- LaMa 阶段取消会立即终止工作进程；其他阶段在阶段边界合作取消，所有 UI 更新通过 Qt 信号返回主线程。
- 受保护或非目标语言区域不进入擦除和渲染；最小字号仍无法容纳时记录 `overflow` 并在界面提示。
- 定向测试 `9 passed`，完整回归 `126 passed`，启动冒烟、正式源码原型依赖扫描和敏感信息扫描通过。
- 自动源语言判断、完整字体映射/视觉复刻、艺术字、弧形字和文字框编辑尚未完成，不作为本任务既成能力；继续按需求追踪矩阵进入后续实现与验收。
