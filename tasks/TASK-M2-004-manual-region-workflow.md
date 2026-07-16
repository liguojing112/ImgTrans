# TASK-M2-004：手动框选与独立擦除区域

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M2-003

实现手动框选后的 OCR→翻译→擦除→渲染，以及直接输入原文/译文；擦除区域和文字区域可独立调整并局部重算。

## 完成记录

- 画布提供一次性拖拽框选，视图坐标会转换并限制在原图坐标范围内。
- 手动路径支持自动 OCR 后翻译、直接输入原文后翻译、直接输入最终译文三种模式。
- 框选区域仅用于 OCR；擦除框和译文框拥有独立几何参数，译文框另支持旋转。
- OCR、翻译、本地修复、排版、渲染全部在现有后台任务执行器中运行，不阻塞 Qt 主线程。
- 修复结果只以擦除蒙版包围盒像素补丁写入编辑会话；补丁与新增译文图层作为同一命令撤销/重做，不保存整图历史快照。
- 使用现有 RapidOCR、翻译、LaMa 和排版端口，不从 `src` 依赖原型目录，不包含真实 API 密钥。

## 预计及实际修改文件

- `src/domain/manual_region.py`、`src/domain/composition.py`
- `src/application/manual_region.py`、`src/application/composition.py`、`src/application/ports.py`
- `src/infrastructure/pillow_image_cropper.py`
- `src/ui/image_canvas.py`、`src/ui/manual_region_panel.py`、`src/ui/main_window.py`
- `src/main.py`
- `tests/unit/test_manual_region.py`
- `tests/integration/test_manual_region_workflow.py`
- `tests/ui/test_manual_region.py`

## 测试

```powershell
python -m pytest -q tests/unit/test_manual_region.py tests/integration/test_manual_region_workflow.py tests/ui/test_manual_region.py
python -m pytest -q
```

- 定向测试 `7 passed`，完整回归 `147 passed`。
