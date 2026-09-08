from src.application.copywriting import GenerateCopywriting
from src.domain.copywriting import CopywritingSettings
from src.domain.product_info import ProductFact, ProductManualInfo


class RecordingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def chat(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if "SPECIFICATION TRANSLATION" in prompt:
            return "- 商品名: フェイスクロス\n- ブランド: 棉小飞\n- 仕様: 30枚"
        return '{"overview": "製品概要", "advantages": "利点", "functions": "機能", "scenes": "用途"}'


def _fact() -> ProductFact:
    return ProductFact(
        name="洗脸巾", brand="棉小飞", specs="30片装", color="白色",
        material="100%天然植物纤维",
    )


def test_copywriting_prompt_uses_selected_language_name_and_code() -> None:
    llm = RecordingLLM()
    generator = GenerateCopywriting(llm)
    settings = CopywritingSettings(target_language="ja")

    generator.execute(_fact(), ProductManualInfo(), settings)

    assert llm.prompts
    assert all("Japanese" in prompt for prompt in llm.prompts)
    assert all("locale ja" in prompt for prompt in llm.prompts)


def test_specifications_are_generated_by_target_language_specific_request() -> None:
    llm = RecordingLLM()
    generator = GenerateCopywriting(llm)
    settings = CopywritingSettings(target_language="ja")

    result = generator.execute(_fact(), ProductManualInfo(), settings)
    specs = next(module for module in result.detail_modules if module.section == "specs")

    assert "フェイスクロス" in specs.content
    assert any("SPECIFICATION TRANSLATION" in prompt for prompt in llm.prompts)
    assert result.target_language == "ja"


def test_regenerated_item_preserves_target_language() -> None:
    llm = RecordingLLM()
    generator = GenerateCopywriting(llm)
    settings = CopywritingSettings(target_language="fr")

    result = generator.regenerate_item(
        _fact(), ProductManualInfo(), settings, "detail:specs"
    )

    assert result.target_language == "fr"


class _FullLLM:
    """按 prompt 特征路由到预设响应；intro/tags 支持多次调用返回不同响应。"""

    def __init__(
        self,
        intro_responses: list[str] | None = None,
        tag_batches: list[list[str]] | None = None,
    ) -> None:
        self.intro_responses = intro_responses or [
            '{"one_liner": "L", "short_description": "S", "standard_intro": "D"}'
        ]
        self.tag_batches = tag_batches or [[f"tag {i}" for i in range(10)]]
        self.intro_calls = 0
        self.tag_calls = 0

    def chat(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        if "one_liner" in prompt:
            self.intro_calls += 1
            return self.intro_responses[
                min(self.intro_calls - 1, len(self.intro_responses) - 1)
            ]
        if "电商图片标签" in prompt:
            self.tag_calls += 1
            batch = self.tag_batches[
                min(self.tag_calls - 1, len(self.tag_batches) - 1)
            ]
            return "\n".join(batch)
        if "SPECIFICATION TRANSLATION" in prompt:
            return "- 规格: 30片装"
        if "长尾搜索场景词" in prompt:
            return "keyword a (场景A)\nkeyword b (场景B)"
        if "个产品标题" in prompt:
            return "Title A\nTitle B"
        if "按以下分类各生成" in prompt:
            return (
                '{"core": ["c1"], "function": ["f1"], "scene": ["s1"], '
                '"material": ["m1"], "packaging": ["p1"]}'
            )
        return (
            '{"overview": "ov", "advantages": "ad", "functions": "fn", '
            '"scenes": "sc", "packing": "pk", "instructions": "in", "notes": "nt"}'
        )


def _full_settings() -> CopywritingSettings:
    return CopywritingSettings(tag_count=10, keyword_count=2, title_count=2)


def test_intro_retries_on_invalid_json_then_succeeds() -> None:
    llm = _FullLLM(intro_responses=[
        "好的，以下是商品简介：",
        '{"one_liner": "L", "short_description": "S", "standard_intro": "D"}',
    ])
    result = GenerateCopywriting(llm).execute(
        _fact(), ProductManualInfo(), _full_settings()
    )
    assert llm.intro_calls == 2
    assert result.intro.one_liner == "L"
    assert result.intro.standard_intro == "D"


def test_intro_stays_empty_and_logs_after_exhausted_retries(capsys) -> None:
    llm = _FullLLM(intro_responses=["不是 JSON"])
    result = GenerateCopywriting(llm).execute(
        _fact(), ProductManualInfo(), _full_settings()
    )
    assert llm.intro_calls == 3
    assert result.intro.one_liner == ""
    assert "JSON 解析失败" in capsys.readouterr().out


def test_tags_retry_until_reaching_requested_count() -> None:
    llm = _FullLLM(tag_batches=[
        ["a", "b", "c", "d"],
        [f"tag {i}" for i in range(10)],
    ])
    result = GenerateCopywriting(llm).execute(
        _fact(), ProductManualInfo(), _full_settings()
    )
    assert llm.tag_calls == 2
    assert len(result.tags) == 10


def test_tags_keep_best_result_when_count_never_reached(capsys) -> None:
    llm = _FullLLM(tag_batches=[
        [f"tag {i}" for i in range(6)],
        ["a", "b"],
    ])
    result = GenerateCopywriting(llm).execute(
        _fact(), ProductManualInfo(), _full_settings()
    )
    assert llm.tag_calls == 3
    assert len(result.tags) == 6
    assert "标签数量不足" in capsys.readouterr().out
