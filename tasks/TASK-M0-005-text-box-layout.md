# TASK-M0-005：自动字号、换行和旋转文字框验证

**里程碑**：M0 技术风险验证
**状态**：待开始
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-LAYOUT-001～003、FR-LAYOUT-007
**对应决策**：DEC-008、DEC-009、DEC-015

## 验证目标

验证给定矩形或旋转四边形时，译文能否确定性完成字体测量、自动字号拟合、语言相关换行、对齐、描边/阴影边界计算和旋转合成，并可靠报告溢出。

## 实现范围

- UI 无关布局接口：文本、字体、字号范围、文字框、对齐、换行、旋转、描边、阴影 → 布局结果。
- 矩形和旋转四边形两种目标区域。
- 自动字号搜索、自动/手动换行、左/中/右与上/中/下对齐。
- 输出行、最终字号、像素边界、变换矩阵、效果边界和溢出状态。
- Pillow 负责字体测量/栅格化，OpenCV 负责几何变换；复杂脚本通过抽象 shaping 输入，不在本任务重做 TASK-M0-003。
- 输出透明文字图层和调试图，不实现正式编辑器或弧形文字。

## 测试素材

- 简体/繁体中文、英文、俄语、日语、韩语、越南语及混合数字的短/中/长文本。
- 宽、窄、高、扁、极小和不同旋转角的文字框。
- 固定合法字体与人工给定期望行数/边界的合成用例。
- 棋盘格、十字中心和角点标记背景用于检测旋转偏移。
- 无法容纳、缺字、空文本和极端描边/阴影参数用例。

## 成功标准

- 同一输入重复运行产生相同布局数据和溢出状态。
- 可容纳用例不发生非预期裁切，文字和效果像素边界均位于允许区域。
- 工程几何基线：旋转角误差 ≤3°，中心偏差 ≤目标框短边 5%，文字边界 IoU ≥0.75。
- 不可容纳用例显式返回 `overflow`，不静默截断或使用低于配置最小值的字号。
- 测量与渲染使用一致字形数据，描边和阴影计入边界。
- 模块不导入 PySide6，布局与渲染分别可测。

## 失败时替代方案

- 连续字号搜索不稳定时采用离散候选字号和代价函数。
- Pillow 测量/绘制不一致时统一使用 TASK-M0-003 选定的 shaping/raster 后端。
- 四边形直接变换模糊时使用高分辨率离屏渲染再降采样。
- 自动容纳失败时保留溢出状态，由正式编辑器允许扩框、手动换行或调整最小字号。

## 预计修改文件

- `prototypes/text_box_layout/run.py`
- `prototypes/text_box_layout/contracts.py`
- `prototypes/text_box_layout/layout_engine.py`
- `prototypes/text_box_layout/font_metrics.py`
- `prototypes/text_box_layout/renderer.py`
- `prototypes/text_box_layout/geometry.py`
- `tests/prototypes/text_box_layout/test_font_fit.py`
- `tests/prototypes/text_box_layout/test_wrapping.py`
- `tests/prototypes/text_box_layout/test_rotation.py`
- `tests/prototypes/text_box_layout/test_overflow.py`
- `tests/prototypes/text_box_layout/fixtures/cases.json`

不得修改 `src/`。

## 测试命令

```powershell
python -m pytest tests/prototypes/text_box_layout -q
python prototypes/text_box_layout/run.py --cases tests/prototypes/text_box_layout/fixtures/cases.json --output artifacts/m0/text-box-layout
```

## 交付物

- 自动布局 JSON、视觉基准和工程指标结果。
- 正式文字框、样式与溢出领域模型建议。
- Pillow/OpenCV 路径的保留或替代结论。

## 审查边界

审查只评价直线/旋转文字框布局与渲染，不包含弧形路径、OCR、字体识别或 UI 拖拽交互。
