# TASK-M0-006：弧形文字渲染验证

**里程碑**：M0 技术风险验证
**状态**：待开始
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-LAYOUT-004～006、FR-EDIT-003
**对应决策**：DEC-009、DEC-015

## 验证目标

验证按圆弧和 Bézier 路径布置已塑形字形簇的几何、渲染质量、方向控制、碰撞检测和人工调整数据模型，为“自动复刻 + 人工编辑”弧形文字方案提供稳定核心接口。

## 实现范围

- 输入已塑形字形簇、字体、字号、圆弧/二次 Bézier 路径、方向、起止范围和对齐。
- 按弧长计算字形簇中心，按路径切线旋转。
- 支持上弧、下弧、顺时针、逆时针和路径反转。
- 输出每个字形簇的位置、角度、边界、碰撞和越界状态。
- 输出透明文字图层、路径、控制点和边界调试图。
- 提供路径控制点数据的序列化往返，用于未来编辑器。
- 只用合成已知路径验证；自动从原图估计曲线只做最小候选接口，不训练或引入曲线检测模型。

## 测试素材

- 半径已知的上/下半圆、四分之一圆、S 型和不同曲率 Bézier。
- 短/中/长 LTR 文本，以及一组已由 TASK-M0-003 正确塑形的 RTL 字形簇。
- 固定合法字体、带理想中心和切线角的几何基准 JSON。
- 不同描边宽度、字号、路径长度不足和字形碰撞用例。
- 原始需求中的弧形示例只在本地授权测试中作为视觉参考。

## 成功标准

- 合成基准中字形簇中心线偏差 ≤输出短边 0.5%，切线角误差 ≤3°。
- 方向、起止范围和上/下弧能够显式控制，反转路径不打乱内部字形簇顺序规则。
- 路径不足、碰撞和越界均显式报告，不静默重叠。
- 更换文本后可重新布局，不依赖逐像素手工定位。
- 路径控制点序列化往返后几何结果一致。
- 高分辨率离屏渲染后无不可接受的锯齿或字符裁切。

## 失败时替代方案

- 逐字形栅格旋转质量不足时采用矢量路径或高分辨率离屏渲染后降采样。
- 连写脚本逐字形簇放置不自然时评估整段路径变形后端。
- 自动路径估计不稳定时，以用户调整控制点作为正式兜底，不阻断导出。
- 译文过长时在字号、字距和路径占用范围中进行受限优化，仍失败则明确溢出。

## 预计修改文件

- `prototypes/curved_text/run.py`
- `prototypes/curved_text/contracts.py`
- `prototypes/curved_text/path_geometry.py`
- `prototypes/curved_text/glyph_placement.py`
- `prototypes/curved_text/renderer.py`
- `prototypes/curved_text/collision.py`
- `tests/prototypes/curved_text/test_arc_length.py`
- `tests/prototypes/curved_text/test_placement.py`
- `tests/prototypes/curved_text/test_direction.py`
- `tests/prototypes/curved_text/test_serialization.py`
- `tests/prototypes/curved_text/fixtures/curves.json`

不得修改 `src/`。

## 测试命令

```powershell
python -m pytest tests/prototypes/curved_text -q
python prototypes/curved_text/run.py --cases tests/prototypes/curved_text/fixtures/curves.json --output artifacts/m0/curved-text
```

## 交付物

- 曲线路径、字形位置和碰撞结果 JSON。
- 视觉基准与误差报告。
- 正式 `LayoutPath` 和弧形编辑数据接口建议。

## 审查边界

审查只关注已知路径上的字形簇布局和人工可调数据模型，不包含自动 OCR 曲线检测、正式画布控件或完整艺术字系统。
