# TASK-M2-007：艺术字映射与弧形文字编辑

**状态**：已完成（2026-07-16；自动高还原能力按风险边界降级）  
**依赖**：TASK-M2-003

在可编辑图层之上实现合法字体候选映射、基础艺术效果参数和弧形路径布局/人工控制点；未达到自动复刻基线时保持可编辑和可导出，不承诺像素级复制原艺术字。

## 完成记录

- 新增二次曲线文字路径模型，包含起点、控制点、终点和反向排列；路径支持采样点、切线、弧长估算以及随文字框移动、缩放、旋转。
- Qt 先对完整文本执行 shaping，再将生成的字形运行沿路径放置；连字和复杂脚本不在 shaping 前按 Unicode 字符拆分。
- 画布显示弧线、控制多边形和三个控制点，可直接拖动；“弧形”页也可以编辑六个原图坐标、反向排列、生成默认上弧和恢复直线。
- 弧形路径修改、画布控制点拖动、直线恢复以及既有文字/样式修改共用统一撤销重做历史。
- 字体推荐只从操作系统已安装字体中筛选，并检查当前文字覆盖；不复制或分发系统字体。
- 样式页新增清晰描边、电商海报和立体阴影近似预设，仍保留字体、颜色、描边、阴影和路径的人工调整。

## 明确不承诺

- 未实现从任意商品图中可靠识别原字体名称、渐变、纹理填充、扭曲网格或 3D 艺术效果。
- 未实现从被 OCR 拆散的任意弧形文字中可靠自动恢复原曲线路径；当前提供默认弧线和人工控制点。
- 因此本任务不宣称“复杂艺术字像素级复刻”或“所有弧形文字全自动定位”验收通过。若客户要求完全自动且高度复刻，应调整范围或提供人工验收素材和专门模型预算。

## 修改文件

- `src/domain/layout.py`
- `src/application/composition.py`
- `src/infrastructure/text_renderer.py`
- `src/platform/font_candidates.py`
- `src/ui/image_canvas.py`、`src/ui/layer_style_panel.py`、`src/ui/curved_text_panel.py`、`src/ui/main_window.py`
- `tests/unit/test_curved_text_models.py`
- `tests/integration/test_curved_text_rendering.py`
- `tests/ui/test_curved_text_ui.py`

## 测试

```powershell
python -m pytest -q tests/unit/test_curved_text_models.py tests/integration/test_curved_text_rendering.py tests/ui/test_curved_text_ui.py
python -m pytest -q
```

- 定向测试 `8 passed`，完整回归 `165 passed`。
