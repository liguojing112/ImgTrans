# TASK-M2-005：批量任务调度与资源控制

**状态**：已完成（2026-07-16；真实混合图片 RSS 基准留待 M2-008）  
**依赖**：TASK-M1-006

实现惰性解码、有界活动图片、重型推理串行、单图失败隔离、批次进度和取消状态机；以 50/100 张自动测试验证不无界驻留图片像素。

## 完成记录

- 新增批次、单图快照、批次/单图状态和聚合进度领域模型。
- `RunBatch` 的队列只持有路径和轻量状态，默认最多提交两张活动图片；仅在工作项开始时调用正式图片导入用例。
- 共享单图翻译工作流通过互斥门串行执行，避免 RapidOCR/LaMa 重型模型并发争用；图片导入和完成结果落盘仍保持有界活动数。
- 单张导入、识别、翻译、修复或缓存失败只将该项标为失败，调度器继续处理后续图片。
- 取消后停止补充新工作项，尚未启动项标为取消，并将取消信号传给当前单图工作流。
- 成功图片以无损 PNG 写入会话缓存，批次状态只保存结果引用；支持按需加载和整批安全清理，PNG Alpha 可往返。
- 50/100 张合成压力测试的最大活动解码图片数均为 2；真实混合尺寸图片的进程 RSS 比例仍按 M2-008 验收，不在本任务中虚报通过。

## 修改文件

- `src/domain/batch.py`
- `src/application/batch.py`、`src/application/ports.py`
- `src/infrastructure/batch_result_store.py`
- `tests/unit/test_batch_models.py`
- `tests/integration/test_batch_scheduler.py`
- `tests/integration/test_batch_result_store.py`

## 测试

```powershell
python -m pytest -q tests/unit/test_batch_models.py tests/integration/test_batch_scheduler.py tests/integration/test_batch_result_store.py
python -m pytest -q
```

- 定向测试覆盖失败隔离、重型任务串行、100 项取消、50/100 张活动上限以及缓存 Alpha 往返。
