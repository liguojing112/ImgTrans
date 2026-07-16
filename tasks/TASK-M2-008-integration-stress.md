# TASK-M2-008：M2 集成、100 张压力与会话保护

**状态**：已完成（2026-07-16）  
**依赖**：TASK-M2-001～007

## 验证目标

- 验证 M2 编辑命令可以组合执行，并完整撤销回初始布局和像素。
- 验证 100 张混合 JPG/PNG/WebP 在正式批量调度、真实编解码和磁盘结果缓存下不会无界驻留。
- 验证连续三轮批量任务结束后的空闲 RSS 不持续阶梯式增长。
- 验证未导出单图或批量结果在关闭/丢弃前提示用户。
- 验证会话缓存不会形成可再次打开的项目文件。

## 实现范围

- 在 `src/domain/session.py` 维护未导出单图和批量结果的轻量状态。
- 在主窗口的重新导入、重新批处理、清空批次和关闭路径接入丢弃确认。
- 在 `src/platform/process_memory.py` 提供 Windows/Linux/macOS 进程 RSS 采样边界。
- 修复 `PngBatchResultStore` 首次并发写入前缓存根目录未固定导致的 Windows 路径竞争。
- 压力测试使用正式 `RunBatch`、`ImportImage`、`PillowImageCodec` 和 `PngBatchResultStore`；OCR、翻译、LaMa 与渲染阶段使用确定性透传工作流，以隔离批量资源驻留问题。

## 测试素材

- 动态生成 100 张 160×96～640×360 的 JPG、RGBA PNG 和 WebP 混合图片。
- 一张包含文字、框体、样式、弧线和手动局部修复的编辑合成图。

## 成功标准与结果

- 100 张全部完成，单次最大活动项为 2。
- 同一数据分布下，100 张峰值 RSS 不超过 50 张的 125%。本机结果：50 张 `30.10 MiB`，100 张 `32.42 MiB`，比例 `1.0771`。
- 连续三轮空闲 RSS 不连续两次增长超过 `4 MiB`。本机结果：`26.18/26.54/26.84 MiB`，相邻增长 `0.36/0.30 MiB`。
- 压力测试曾复现首次缓存目录并发路径竞争；修复后连续 20 轮、每轮 100 张均成功。
- 关闭未导出会话可取消关闭，也可确认丢弃；无未导出结果时不额外提示。
- 缓存目录只包含按需输出 PNG，不包含 JSON、SQLite 或项目清单。
- M2 编辑综合测试的 7 类操作全部撤销后恢复初始布局和像素。

## 验收边界

本任务证明正式调度、真实图片编解码和磁盘缓存的结构性资源控制，不证明 100 张图片同时执行真实 RapidOCR/LaMa 时的吞吐或修复质量。真实模型质量由已有 M0 证据和后续代表性产品验收覆盖；复杂修复继续采用人工蒙版、撤销、重试和保留原图降级。

## 修改文件

- `src/domain/session.py`
- `src/platform/process_memory.py`
- `src/infrastructure/batch_result_store.py`
- `src/ui/main_window.py`
- `tests/unit/test_session_changes.py`
- `tests/ui/test_session_protection.py`
- `tests/integration/test_no_project_files.py`
- `tests/integration/test_m2_batch_stress.py`
- `tests/integration/test_m2_editing_integration.py`

## 测试命令

```powershell
python -m pytest -q
python -m compileall -q src tests
python -m src --smoke-test
```

最终结果：`172 passed`；编译检查和启动烟测通过。
