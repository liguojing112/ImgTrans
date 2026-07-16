# TASK-M1-005：LaMa 修复接口和已验证实现迁移

**里程碑**：M1 单图翻译闭环  
**状态**：已完成（2026-07-16）  
**优先级**：P0  
**依赖**：TASK-M1-004

## 用户可见结果

翻译区域生成可见擦除蒙版，用户可执行背景修复并在原图/修复图之间切换；失败时可撤销、重试或保留原图。

## 实现范围

- 建立独立 `EraseMask`、保护区、修复请求/结果和 `InpaintingAdapter` 端口。
- 根据 M0 结论在正式代码重新实现 LaMa ONNX Runtime 局部修复和精确蒙版合成，不从 `prototypes` 导入。
- 默认局部裁剪、扩张 2 px、不羽化；保留 OpenCV Telea 简单降级适配器。
- 模型缺失、加载失败、超时和质量风险转换为可恢复产品状态。
- 模型加载和推理在可终止工作进程执行，UI 主线程不持有推理会话。

## 预计修改文件

- `src/domain/inpainting.py`
- `src/application/inpainting.py`、`src/application/ports.py`
- `src/infrastructure/lama_onnx_adapter.py`
- `src/infrastructure/inpainting_process.py`
- `src/infrastructure/fallback_inpaint_adapter.py`
- `src/infrastructure/opencv_inpaint_adapter.py`
- `src/infrastructure/pillow_mask_rasterizer.py`
- `src/ui/inpainting_panel.py`、`src/ui/image_canvas.py`、`src/ui/main_window.py`
- `tests/unit/test_erase_mask.py`
- `tests/integration/test_inpainting_adapters.py`
- `tests/ui/test_inpainting_action.py`

## 测试与完成标准

```powershell
python -m pytest tests/unit/test_erase_mask.py tests/integration/test_inpainting_adapters.py tests/ui/test_inpainting_action.py -q
```

- 输出尺寸/通道正确，蒙版外像素和 Alpha 保持。
- 缺少大模型时测试可使用契约兼容假适配器，正式 LaMa 最小调用单独标记。
- 用户可见蒙版、修复结果、失败状态和原图回退，不承诺所有复杂背景自动无痕。

## 完成记录

- 正式领域模型将擦除蒙版、保护蒙版、修复请求和修复结果与 UI 解耦；仅 `should_erase_source=true` 的翻译区域进入自动擦除蒙版。
- LaMa 使用固定 SHA-256 校验、局部 512×512 推理、蒙版内精确合成和独立可终止进程；模型通过 `IMGTRANS_LAMA_MODEL` 或应用数据目录提供，不进入仓库。
- LaMa 缺失、加载或推理失败时自动降级 OpenCV Telea，并在 UI 显示警告；用户可重新修复、切换原图或撤销并保留原图。
- 正式适配器已使用本地既有模型完成真实推理：蒙版外像素完全一致，蒙版内发生修复；完整测试 `114 passed`，追加保护蒙版和进程边界测试后为 `117 passed`。

## 单代理边界

只实现正式擦除与修复，不完成最终译文合成和全流水线编排。
