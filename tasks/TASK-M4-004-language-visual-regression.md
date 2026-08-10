# TASK-M4-004：多语言字体与复杂脚本视觉回归

**状态**：实现完成，待 macOS arm64 CI 验证（2026-07-18）
**依赖**：TASK-M4-002、TASK-M4-003

## 目标

对客户指定语言的 OCR 路由、字体回退、BiDi、shaping、换行、旋转和弧形排版建立跨平台正式回归。

## 范围与验收

- 覆盖 25 种语言的代表性文本和缺字检测。
- 重点覆盖阿拉伯语、乌尔都语、印地语、泰语及混合 RTL/LTR。
- 视觉基线按平台维护，偏差超过批准阈值时失败。
- 缺少原字体时只使用最接近的合法字体并报告降级。

## 预计修改文件

- `src/platform/fonts.py`、`src/infrastructure/text_renderer.py`、`tests/visual/`

## 测试命令

```powershell
python -m pytest tests/visual -q
```

## 实施结果

- 25 种客户语言均建立代表文本的字体解析、Qt shaping、缺字 glyph、墨迹范围和布局溢出门禁。
- 阿拉伯语、波斯语、乌尔都语覆盖 RTL 与拉丁字母/数字混排；印地语、孟加拉语和泰语覆盖组合字形。
- Windows 修正系统字体文件名为 `Nirmala.ttc`，复杂脚本不再错误降级到 Segoe UI；日语补充 Yu Gothic 注册候选。
- 字体解析返回明确的降级状态和原因，自动排版将该状态写入文字样式，单图完成面板提示需要人工检查的区域数。
- 跨平台视觉门禁采用 glyph、布局、墨迹边界和对齐等结构化指标，不要求 Windows 与 macOS 字体栅格逐像素相同。
- Windows 专项回归与完整 `359 passed` 已通过；macOS arm64 随下一次现有桌面 CI 验证，不新增工作流或 Artifact 要求。
