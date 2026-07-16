from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import Field, model_validator

from server.api.contracts import StrictContract
from server.api.auth import require_client
from server.api.rate_limit import enforce_rate_limit
from server.domain.translation import (
    SUPPORTED_LANGUAGE_CODES,
    TranslationTextItem,
    TranslationTextRequest,
)


class TranslationItemRequest(StrictContract):
    item_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    text: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def reject_blank_text(self) -> "TranslationItemRequest":
        if not self.text.strip():
            raise ValueError("Translation text cannot be blank")
        return self


class TranslationRequest(StrictContract):
    source_language: str | None = None
    target_language: str
    items: tuple[TranslationItemRequest, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_contract(self) -> "TranslationRequest":
        if (
            self.source_language is not None
            and self.source_language not in SUPPORTED_LANGUAGE_CODES
        ):
            raise ValueError("Unsupported source language")
        if self.target_language not in SUPPORTED_LANGUAGE_CODES:
            raise ValueError("Unsupported target language")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("Translation item IDs must be unique")
        if sum(len(item.text) for item in self.items) > 20_000:
            raise ValueError("Translation request contains too many characters")
        return self


class TranslationItemResponse(StrictContract):
    item_id: str
    status: Literal["translated", "failed"]
    translated_text: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class TranslationResponse(StrictContract):
    correlation_id: str
    provider: str
    items: tuple[TranslationItemResponse, ...]


translation_router = APIRouter(prefix="/v1", tags=["translation"])


@translation_router.post("/translations", response_model=TranslationResponse)
def translate_text(
    payload: TranslationRequest,
    request: Request,
    response: Response,
) -> TranslationResponse:
    enforce_rate_limit(request, "translation", limit=60, window_seconds=60)
    require_client(request, "Translation proxy is not enabled")
    correlation_id = request.state.correlation_id
    try:
        result = request.app.state.translate_text.execute(
            TranslationTextRequest(
                items=tuple(
                    TranslationTextItem(item.item_id, item.text)
                    for item in payload.items
                ),
                source_language=payload.source_language,
                target_language=payload.target_language,
                correlation_id=correlation_id,
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Translation request is invalid") from error
    response.headers["Cache-Control"] = "no-store"
    return TranslationResponse(
        correlation_id=correlation_id,
        provider=result.provider,
        items=tuple(
            TranslationItemResponse(
                item_id=request_item.item_id,
                status="translated" if item.translated_text is not None else "failed",
                translated_text=item.translated_text,
                error_code=item.error_code,
                error_message=item.error_message,
            )
            for request_item, item in zip(payload.items, result.items, strict=True)
        ),
    )
