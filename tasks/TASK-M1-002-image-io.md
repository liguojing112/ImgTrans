# TASK-M1-002：图片导入、格式验证、显示和导出

**里程碑**：M1 单图翻译闭环  
**状态**：已完成  
**优先级**：P0  
**依赖**：TASK-M1-001

## 用户可见结果

用户可选择一张 JPG/JPEG、PNG 或 WebP，在画布中按 EXIF 正确方向显示，并导出为 JPG、PNG、WebP、静态 GIF 或单页 TIFF。

## 实现范围

- 建立 `ImageAsset`、`ImageLimits`、导入/导出端口和应用用例。
- 使用 Pillow 正式适配器完成格式探测、解码安全限制、EXIF 方向、RGB/RGBA 工作图和原子导出。
- 实现远程配置接口的内置默认限制；远程/缓存实现留给后续后端任务。
- 在正式窗口接入文件选择、预览、错误提示和“导出原始工作图”能力。

## 预计修改文件

- `src/domain/image.py`
- `src/application/image_io.py`、`src/application/ports.py`
- `src/infrastructure/pillow_image_codec.py`
- `src/ui/main_window.py`、`src/ui/image_canvas.py`、`src/ui/qt_task_runner.py`
- `tests/unit/test_image_limits.py`
- `tests/integration/test_image_codec.py`
- `tests/ui/test_image_import_export.py`
- `tests/ui/test_qt_task_runner.py`

## 测试与完成标准

```powershell
python -m pytest tests/unit/test_image_limits.py tests/integration/test_image_codec.py tests/ui/test_image_import_export.py tests/ui/test_qt_task_runner.py -q
```

## 实施结果（2026-07-16）

- 内置限制采用 DEC-006：最小 64×64 px、最大 12000×12000 px、最大 50 MiB、解码安全上限 80 MP。
- 输入扩展名与 Pillow 检测的实际内容必须一致，损坏图片和超限图片返回结构化错误。
- EXIF 方向在进入 RGB/RGBA 工作图前规范化；不承诺保留其他元数据。
- PNG 和 WebP 保留 Alpha；JPG 和静态 GIF 使用白色背景明确扁平化；TIFF 按单页 LZW 导出。
- 导出在同目录临时文件成功编码后原子替换，禁止覆盖导入原图。
- 解码和编码通过 `QtTaskRunner` 在线程池执行，回调回到 UI 主线程。
- 任务级测试 11 项、全仓测试 92 项全部通过；原生 Windows 界面完成真实异步导入视觉检查。

- 输入扩展名与真实内容不一致、越界尺寸、超限文件和损坏图片均明确失败。
- Alpha 与 EXIF 方向满足基线，五种输出可重新解码。
- UI 可见真实图片和导出成功/失败状态，不阻塞主线程处理大图解码。

## 单代理边界

只实现单图 I/O 和显示，不实现 OCR、翻译或结果渲染。
