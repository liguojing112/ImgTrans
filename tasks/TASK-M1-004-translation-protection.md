# TASK-M1-004：翻译接口、模拟翻译器和保护词规则

**里程碑**：M1 单图翻译闭环  
**状态**：已完成  
**优先级**：P0  
**依赖**：TASK-M1-003

## 用户可见结果

用户可选择目标语言和“全部语言/指定源语言”，执行模拟翻译后查看每个区域的原文、译文、跳过原因和保护片段。

## 实现范围

- 建立翻译单元、语言选择策略、`TranslationAdapter` 端口和错误模型。
- 实现无密钥的确定性模拟翻译器，为本地完整闭环服务。
- 实现品牌名、商品型号、SKU、网址和纯数字默认保护规则，并保留可注入词表。
- 先保护再翻译、后恢复占位符；非目标语言区域不进入后续擦除。
- 翻译任务在后台执行，不在源码、测试或日志中出现真实服务密钥。

## 预计修改文件

- `src/domain/translation.py`、`src/domain/protection.py`
- `src/application/translation.py`、`src/application/ports.py`
- `src/infrastructure/mock_translator.py`
- `src/ui/main_window.py`、`src/ui/translation_panel.py`
- `tests/unit/test_language_filter.py`
- `tests/unit/test_protection_rules.py`
- `tests/integration/test_mock_translation.py`
- `tests/ui/test_translation_action.py`

## 测试与完成标准

```powershell
python -m pytest tests/unit/test_language_filter.py tests/unit/test_protection_rules.py tests/integration/test_mock_translation.py tests/ui/test_translation_action.py -q
```

- 指定语言之外的区域保持原样且不生成擦除请求。
- 默认保护类别均有边界测试，占位符冲突和翻译异常不会损坏原文。
- UI 可见模拟译文和跳过状态；无网络、无密钥也能继续本地闭环。

## 单代理边界

只完成语言过滤、保护和模拟翻译，不连接真实 Microsoft Translator。

## 实施结果（2026-07-16）

- 建立 `TranslationSelection`、`TranslationUnit`、逐区域状态、`TranslationResult` 和 `TranslationAdapter` 正式契约。
- “全部区域”和“仅指定语言”两种筛选均在应用层完成；跳过语言和全部受保护区域的 `should_erase_source` 为假，后续不得生成擦除请求。
- 默认规则自动保护网址、SKU、含字母数字型号和数字；品牌名通过可注入词表和界面逗号分隔输入保护，避免把普通大写词误判为品牌。
- 重叠匹配保留完整 URL/SKU/型号；翻译前使用不可变占位符，返回结果缺失或复制占位符时整次失败，不输出被破坏的文字。
- 无密钥 `MockTranslationAdapter` 提供确定性本地词典和明确模拟回退，不访问网络、不包含真实服务配置。
- 正式窗口在 OCR 后启用模拟翻译，显示模式、源/目标语言、品牌保护词、原文、译文、跳过状态和完整保护摘要。
- 任务级 8 项测试、全仓 107 项测试全部通过；真实“导入→RapidOCR→模拟翻译→保护词”Windows 产品路径通过。
- 当前语言筛选使用 OCR 区域携带的模型语言。自动区域语言检测完成后可直接替换该字段，不改变翻译用例契约。
