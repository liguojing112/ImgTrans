# TASK-M2-002：画布缩放平移与文字框几何编辑

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M2-001

实现图层选择、画布缩放/平移、文字框移动/缩放/旋转及对应撤销重做；所有领域坐标保持在原图空间。验收覆盖坐标往返、视图变换不污染模型和拖拽后重新渲染。

## 完成记录

- 画布使用独立的原图坐标↔视图坐标变换；滚轮围绕指针缩放，中键拖动平移，并提供“适应画布”重置入口。
- 点击文字框会与编辑列表同步选择；拖动框体移动、右下手柄缩放、顶部手柄旋转。
- 拖动期间只更新临时不可变布局，释放后才通过 `EditComposition.replace_box` 后台重新拟合和渲染；提交失败恢复正式布局。
- 几何命令与文字修改共享有界撤销/重做历史，原始 `TextLayout` 不被视图操作修改。
- 定向测试 `7 passed`，完整回归 `136 passed`；编译、启动、正式源码依赖与敏感信息检查通过。

## 测试

```powershell
python -m pytest tests/integration/test_edit_composition.py tests/ui/test_canvas_geometry.py tests/ui/test_text_editing.py -q
```
