"""通用 LLM 适配器 — 支持 OpenAI 和 Anthropic 两种 API 协议。

HTTP 使用标准库 urllib.request，不引入新依赖。
"""

from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from pathlib import Path

from src.infrastructure.llm_config import LLMConfig


class LLMError(Exception):
    """LLM 调用错误。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMAdapter:
    """通用 LLM 适配器 — 支持 OpenAI 和 Anthropic 协议。"""

    _OPENAI_CHAT_PATH = "/chat/completions"
    _ANTHROPIC_MESSAGES_PATH = "/messages"

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    @property
    def config(self) -> LLMConfig:
        return self._config

    def update_config(self, config: LLMConfig) -> None:
        self._config = config

    @staticmethod
    def _extract_openai_text(data: dict) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""
        choice = choices[0]
        msg = choice.get("message", {})

        # 1) 标准 content 字段
        content = msg.get("content")
        if content:
            return content

        # 2) reasoning_content — 推理模型 (glm-5v-turbo 等)
        #    推理模型把思考过程放 reasoning_content，最终答案可能
        #    在 content 或拼接在 reasoning_content 末尾
        reasoning = msg.get("reasoning_content", "")
        if reasoning:
            return reasoning

        # 3) delta（流式响应的兼容）
        delta = choice.get("delta", {})
        if delta.get("content"):
            return delta["content"]

        return ""

    @staticmethod
    def _extract_anthropic_text(data: dict) -> str:
        content = data.get("content", [])
        if content:
            return content[0].get("text", "")
        return json.dumps(data, ensure_ascii=False)

    # GLM OpenAI 兼容端点的 max_tokens 上限
    _GLM_MAX_TOKENS_LIMIT = 1024

    def _clamp_max_tokens(self, max_tokens: int) -> int:
        """GLM 所有模型 max_tokens 上限为 1024（API 限制）。"""
        if self._config.provider == "glm":
            return min(max_tokens, self._GLM_MAX_TOKENS_LIMIT)
        return max_tokens

    # ── 文本生成 ──

    def chat(self, messages: list[dict], model: str | None = None,
             max_tokens: int | None = None, temperature: float | None = None) -> str:
        """发送聊天请求，返回文本响应。"""

        if self._config.provider == "anthropic":
            return self._chat_anthropic(messages, model, max_tokens, temperature)
        return self._chat_openai(messages, model, max_tokens, temperature)

    def _chat_openai(self, messages: list[dict], model: str | None,
                     max_tokens: int | None, temperature: float | None) -> str:
        url = self._resolve_base_url() + self._OPENAI_CHAT_PATH
        body = {
            "model": model or self._config.model,
            "messages": messages,
            "max_tokens": self._clamp_max_tokens(max_tokens or self._config.max_tokens),
            "temperature": temperature if temperature is not None else self._config.temperature,
        }
        print(f"[LLM] OpenAI 请求: {url} model={body['model']}", flush=True)
        data = self._send_request(url, body)
        text = self._extract_openai_text(data)
        print(f"[LLM] OpenAI 响应: {len(text)} 字符", flush=True)
        return text

    def _chat_anthropic(self, messages: list[dict], model: str | None,
                        max_tokens: int | None, temperature: float | None) -> str:
        url = self._resolve_base_url() + self._ANTHROPIC_MESSAGES_PATH
        system = ""
        user_messages: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                user_messages.append(msg)
        body = {
            "model": model or self._config.model,
            "max_tokens": self._clamp_max_tokens(max_tokens or self._config.max_tokens),
            "messages": user_messages,
        }
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        data = self._send_request(url, body, provider="anthropic")
        return self._extract_anthropic_text(data)

    # ── Vision (图片 + 文字) ──

    def chat_with_image(self, image_path: Path, prompt: str,
                        model: str | None = None,
                        max_tokens: int | None = None) -> str:
        """发送带图片的聊天请求。"""
        image_b64 = self.encode_image(image_path)
        media_type = self._image_media_type(image_path)

        if self._config.provider == "anthropic":
            return self._chat_anthropic_vision(image_b64, media_type, prompt, model, max_tokens)
        return self._chat_openai_vision(image_b64, media_type, prompt, model, max_tokens)

    def _chat_openai_vision(self, image_b64: str, media_type: str,
                            prompt: str, model: str | None,
                            max_tokens: int | None) -> str:
        url = self._resolve_base_url() + self._OPENAI_CHAT_PATH
        body = {
            "model": model or self._config.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{media_type};base64,{image_b64}"}},
                ],
            }],
            "max_tokens": self._clamp_max_tokens(max_tokens or self._config.max_tokens),
        }
        data = self._send_request(url, body)
        return self._extract_openai_text(data)

    def _chat_anthropic_vision(self, image_b64: str, media_type: str,
                               prompt: str, model: str | None,
                               max_tokens: int | None) -> str:
        url = self._resolve_base_url() + self._ANTHROPIC_MESSAGES_PATH
        body = {
            "model": model or self._config.model,
            "max_tokens": self._clamp_max_tokens(max_tokens or self._config.max_tokens),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    }},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        data = self._send_request(url, body, provider="anthropic")
        return self._extract_anthropic_text(data)

    # ── 结构化输出 ──

    def structured_chat(self, messages: list[dict], output_fields: list[str],
                        model: str | None = None) -> dict:
        """请求 LLM 返回 JSON 结构化数据。在 prompt 末尾追加格式要求。"""

        schema_desc = "、".join(f'"{f}": "..."' for f in output_fields)
        json_hint = (
            f"\n\n请以 JSON 格式返回结果，只返回 JSON，不要包含其他文字。\n"
            f'格式: {{"result": {{{schema_desc}}}}}'
        )
        messages = [dict(m) for m in messages]
        messages[-1]["content"] = messages[-1].get("content", "") + json_hint

        raw = self.chat(messages, model=model)

        try:
            data = json.loads(raw)
            return data.get("result", data)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            match = re.search(r'\{[\s\S]*"result"[\s\S]*\}', raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                    return data.get("result", data)
                except json.JSONDecodeError:
                    pass
            return {"_raw": raw, "_error": "无法解析 JSON 响应"}

    # ── 辅助方法 ──

    def test_connection(self) -> bool:
        """测试连接是否可用。"""
        try:
            self.chat(
                [{"role": "user", "content": "回复 OK"}],
                max_tokens=16,
            )
            return True
        except LLMError:
            return False

    _GLM_OLD_BASE_URL = "https://open.bigmodel.cn/api/anthropic"
    _GLM_NEW_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

    def _resolve_base_url(self) -> str:
        url = self._config.base_url
        if not url:
            if self._config.provider == "anthropic":
                url = "https://api.anthropic.com/v1"
            elif self._config.provider == "glm":
                url = self._GLM_NEW_BASE_URL
            else:
                url = "https://api.openai.com/v1"
        # GLM 自动迁移：旧 Anthropic 端点 → OpenAI 兼容端点
        if self._config.provider == "glm" and url.rstrip("/") == self._GLM_OLD_BASE_URL:
            url = self._GLM_NEW_BASE_URL
        return url.rstrip("/")

    def _send_request(self, url: str, body: dict,
                      provider: str = "openai") -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        req.add_header("Content-Type", "application/json")

        if provider == "anthropic":
            req.add_header("x-api-key", self._config.api_key)
            req.add_header("anthropic-version", "2023-06-01")
        else:
            req.add_header("Authorization", f"Bearer {self._config.api_key}")

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                print(f"[LLM] HTTP {resp.status} OK ({len(raw)} bytes)", flush=True)
                if len(raw) < 2000:
                    print(f"[LLM] 原始响应: {raw}", flush=True)
                else:
                    print(f"[LLM] 原始响应(前500): {raw[:500]}", flush=True)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            print(f"[LLM] HTTP {e.code} 错误: {e.reason}", flush=True)
            try:
                detail = json.loads(e.read().decode("utf-8"))
                msg = _extract_error_message(detail, provider)
                print(f"[LLM] 错误详情: {msg}", flush=True)
            except Exception:
                msg = f"HTTP {e.code}"
            raise LLMError(msg, status_code=e.code)
        except urllib.error.URLError as e:
            raise LLMError(f"网络连接失败: {e.reason}")

    @staticmethod
    def encode_image(path: Path) -> str:
        raw = path.read_bytes()
        return base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _image_media_type(path: Path) -> str:
        suffix = path.suffix.lower()
        mapping = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".png": "image/png", ".webp": "image/webp",
                   ".bmp": "image/bmp"}
        return mapping.get(suffix, "image/png")


def _extract_error_message(detail: dict, provider: str) -> str:
    if provider == "anthropic":
        if "error" in detail:
            return detail["error"].get("message", str(detail))
        return str(detail)
    if "error" in detail:
        return detail["error"].get("message", str(detail))
    return str(detail)
