# TASK-M4-004：多语言字体与复杂脚本视觉回归

**状态**：待实施  
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

