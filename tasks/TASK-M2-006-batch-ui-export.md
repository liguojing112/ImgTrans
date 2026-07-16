# TASK-M2-006：多图界面与选择性导出

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M2-005

实现多图导入、任务列表、单图状态/错误、结果切换、导出选择和选择性批量导出；单张失败不得终止其余图片。

## 完成记录

- 主窗口新增“批量导入”入口和“批量”侧边页，可一次添加 JPG/JPEG、PNG、WebP，并自动去除同一路径的重复项。
- 列表显示图片名、等待/处理/成功/失败/取消状态、当前处理阶段和单图错误；进度显示完成、失败、取消和总数。
- 批量任务复用 OCR 页和翻译页的语言、指定语言及保护词设置，通过现有 Qt 后台任务运行；运行期间保留批次取消按钮。
- 成功项默认勾选，用户可取消任意项或重新选择全部成功项；双击成功项按需从缓存载入画布预览。
- 选择性导出支持 JPG、PNG、WebP、静态单帧 GIF 和单页 TIFF，逐张加载和导出；同名文件自动追加序号且不覆盖已有文件。
- 单项加载或导出失败只记录该项失败，不终止其余选择；批量缓存可清理，窗口关闭时清理当前会话批次。

## 修改文件

- `src/application/batch_export.py`
- `src/ui/batch_panel.py`、`src/ui/main_window.py`
- `src/main.py`
- `tests/integration/test_batch_export.py`
- `tests/ui/test_batch_ui.py`

## 测试

```powershell
python -m pytest -q tests/integration/test_batch_export.py tests/ui/test_batch_ui.py
python -m pytest -q
```

- 选择性导出和 UI 定向测试通过；完整回归 `157 passed`。
