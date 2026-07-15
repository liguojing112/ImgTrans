# TASK-M0-003：复杂脚本与 RTL 排版验证

**里程碑**：M0 技术风险验证
**状态**：实施中（Windows x64 已通过；macOS arm64 CI 与母语视觉审阅待完成）
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-LAYOUT-002、FR-LAYOUT-006、FR-LAYOUT-007
**对应决策**：DEC-002、DEC-009、DEC-012

## 验证目标

验证阿拉伯语、乌尔都语、波斯语的 RTL/BiDi，印地语、孟加拉语的复杂字形塑形，以及泰语的组合标记和断行。选择可在 Windows x64 与 macOS arm64 打包的 shaping、双向算法和断行后端。

## 实现范围

- 定义与 UI 无关的布局接口：文本、内部语言代码、字体、方向、矩形、字号、对齐 → 行、字形簇、位置和边界。
- 对比至少两条候选实现：独立 shaping/BiDi/断行组合与 Qt 离屏文本布局。
- 支持 RTL/LTR 混排、数字、括号、标点、手动换行和自动换行。
- 布局单位使用字形簇，不按 Unicode 码点拆分。
- 输出透明文字层、字形边界和阅读顺序调试图。
- 不实现 OCR、翻译、弧形路径或正式文字编辑器。

## 测试素材

- 阿拉伯语、乌尔都语、波斯语、印地语、孟加拉语、泰语各 20 组短句/长句。
- 每种语言包含数字、英文、括号和标点混排。
- 覆盖相应字形且许可允许原型分发的固定字体。
- 正确阅读顺序、期望断行和参考渲染图；由母语审核资源或可信公开基准提供。
- 极窄框、组合附标、连字和跨行边界用例。

## 成功标准

- RTL 语言阅读顺序、连接形态、数字和标点位置正确。
- 印地语/孟加拉语连字、重排和附标位置正确。
- 泰语组合标记不分离、不裁切，不在错误音节边界断行。
- 不在字形簇内部换行，像素边界包含全部组合附标。
- Windows x64 与 macOS arm64 使用同一字体时行数、方向和字形簇顺序一致。
- 两个候选后端产生可比较报告，并选出一个正式首选和一个替代后端。

## 失败时替代方案

- Pillow 基础绘制不足时采用成熟 shaping + BiDi + 语言断行组件。
- 独立组件跨平台打包失败时，使用 Qt 离屏布局作为复杂脚本后端，领域接口保持无 UI 控件依赖。
- 自动断行不稳定时允许用户手动换行，但字形连接和阅读顺序必须仍然正确。
- 单一字体无法覆盖时采用按脚本配置的合法字体 fallback 链。

## 预计修改文件

- `prototypes/complex_script_layout/run.py`
- `prototypes/complex_script_layout/contracts.py`
- `prototypes/complex_script_layout/shaping_backend.py`
- `prototypes/complex_script_layout/qt_backend.py`
- `prototypes/complex_script_layout/line_breaker.py`
- `prototypes/complex_script_layout/compare.py`
- `prototypes/complex_script_layout/prepare_fonts.py`
- `prototypes/complex_script_layout/verify_runtime_evidence.py`
- `prototypes/complex_script_layout/font-sources.json`
- `prototypes/complex_script_layout/requirements.lock`
- `.github/workflows/m0-complex-layout-macos-arm64.yml`
- `tests/prototypes/complex_script_layout/test_bidi.py`
- `tests/prototypes/complex_script_layout/test_shaping.py`
- `tests/prototypes/complex_script_layout/test_line_breaking.py`
- `tests/prototypes/complex_script_layout/fixtures/cases.json`

不得修改 `src/`，字体文件必须附带可验证许可元数据。

## 测试命令

```powershell
python -m pytest tests/prototypes/complex_script_layout -q
python prototypes/complex_script_layout/run.py --cases tests/prototypes/complex_script_layout/fixtures/cases.json --output artifacts/m0/complex-layout
python prototypes/complex_script_layout/compare.py --results artifacts/m0/complex-layout
```

## 交付物

- 六种重点语言的视觉基准和结构化测试结果。
- 首选/替代 shaping 后端及 Windows x64/macOS arm64 打包风险结论。
- 正式布局接口建议。

## 当前验证证据（2026-07-15）

- 固定 Noto Fonts 提交 `ffebf8c1ee449e544955a7e813c54f9b73848eac`，5 个字体文件均记录 OFL-1.1 许可来源与 SHA-256。
- Windows x64 已执行六种语言各 20 例，共 120 例；Qt 与 HarfBuzz 两个后端均完成 120/120，失败为 0。
- 两后端的行数与基础方向比较均为 120/120 一致；缺字、字素边界断行和横向越界结构检查违规为 0。
- Windows 结构签名为 `2fff0ecb950920b98600e0a076c4106db17a5c9e2d2db1edbb74d6000bf5ba87`；证据位于忽略提交的 `artifacts/m0/complex-layout/run-003/`。
- 首选后端为通过 UI 无关接口封装的 Qt `QTextLayout`；替代后端为 HarfBuzz + python-bidi + 字素安全贪心断行。
- 已验证 PySide6 6.11.1 和 uharfbuzz 0.55.0 均存在可由 macOS 13 arm64 Python 使用的官方 wheel。第三方依赖采用同时含 arm64 切片的 wheel 不改变本项目仅生成 arm64 应用产物的范围。
- macOS arm64 必须通过新增 GitHub Actions 工作流生成运行证据，并与 Windows 结构签名比较后，才能关闭跨平台验收项。
- 阿拉伯语、乌尔都语、波斯语、印地语、孟加拉语和泰语调试图仍需母语审阅；自动结构检查不替代语言正确性审核。

## 审查边界

审查只关注复杂脚本塑形、方向和断行；不包含字体识别、艺术字或弧形路径。
