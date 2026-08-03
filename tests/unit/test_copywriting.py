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
