# TASK-M0-007：50/100 张批量内存和取消机制验证

**里程碑**：M0 技术风险验证
**状态**：待开始
**优先级**：P0
**类型**：独立技术原型
**关联需求**：FR-IMG-001、FR-IMG-006、FR-IMG-010、NFR-003～005
**对应决策**：DEC-007、DEC-014、DEC-017

## 验证目标

验证 50/100 张图片任务能否采用轻量入队、惰性解码、有界并发和及时释放中间数据；比较线程与工作进程对模型复用、内存回收、单图失败和取消的影响。

## 实现范围

- 独立命令行调度器，不实现正式批量 UI。
- 状态机：queued、decoding、ocr、translating、inpainting、rendering、exporting、succeeded、failed、cancelled。
- 使用可配置的固定延迟/内存模拟阶段；可选接入小型 OCR 冒烟，但不依赖其他 M0 任务完成。
- 有界队列、惰性解码、最多两张活动图片和重型阶段串行默认值。
- 对比线程执行器与独立工作进程执行器。
- 支持单图失败、单图取消、批次取消和模拟应用退出。
- 记录 RSS、阶段耗时、队列长度、活动图数量、取消延迟和终态。
- 结果允许落入受控临时目录；不创建可重开项目文件。

## 测试素材

- 50 张和 100 张两个 manifest，包含小、中、大三档自制图片。
- 一张损坏文件、一张触发解码上限的图片和多个阶段故障注入条目。
- 固定内存分配和固定延迟模拟器，保证不同执行模型可比较。
- 测试报告必须记录机器 CPU、总内存、系统和执行器配置。

## 成功标准

- 入队时只读取轻量元数据，不解码全部图片。
- 活动图片数不超过配置边界；重型阶段并发不超过默认 1。
- 相同分布下，100 张相对 50 张峰值 RSS 增长 ≤25%。
- 取消后 1 秒内不再启动新图片；运行中的阶段在最近安全检查点收敛。
- 单图失败不终止批次，已完成结果和失败原因仍可读取。
- 连续三轮 100 张测试后，空闲 RSS 不持续阶梯式增长。
- 线程/进程对比形成明确选择和原因。

## 失败时替代方案

- 降低活动图片数，所有重型模型采用单独串行工作器。
- 中间结果和完成预览落到受控临时缓存，编辑时按需加载。
- 原生调用无法合作取消时放入独立进程并在超时后终止进程。
- 进程模型重载模型成本过高时使用常驻单模型工作进程与消息队列。
- 内存仍无界时增加阶段级显式释放和进程轮换策略。

## 预计修改文件

- `prototypes/batch_scheduler/run.py`
- `prototypes/batch_scheduler/contracts.py`
- `prototypes/batch_scheduler/state_machine.py`
- `prototypes/batch_scheduler/thread_executor.py`
- `prototypes/batch_scheduler/process_executor.py`
- `prototypes/batch_scheduler/stages.py`
- `prototypes/batch_scheduler/metrics.py`
- `tests/prototypes/batch_scheduler/test_state_machine.py`
- `tests/prototypes/batch_scheduler/test_failure_isolation.py`
- `tests/prototypes/batch_scheduler/test_cancellation.py`
- `tests/prototypes/batch_scheduler/test_memory_bounds.py`
- `tests/prototypes/batch_scheduler/fixtures/manifest-50.json`
- `tests/prototypes/batch_scheduler/fixtures/manifest-100.json`

不得修改 `src/`。

## 测试命令

```powershell
python -m pytest tests/prototypes/batch_scheduler -q
python prototypes/batch_scheduler/run.py --manifest tests/prototypes/batch_scheduler/fixtures/manifest-50.json --executor thread --output artifacts/m0/batch-50-thread
python prototypes/batch_scheduler/run.py --manifest tests/prototypes/batch_scheduler/fixtures/manifest-100.json --executor process --output artifacts/m0/batch-100-process
```

## 交付物

- 50/100 张内存曲线、取消延迟和终态报告。
- 线程/进程选择与默认并发建议。
- 正式 `ImageJob`、`BatchJob` 状态机契约建议。

## 审查边界

审查只关注调度、状态、内存、失败隔离和取消，不评价真实 OCR、翻译或修复质量。
