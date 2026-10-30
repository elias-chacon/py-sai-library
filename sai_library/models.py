"""Tipos de dados da API: mensagens de chat, opções e tipos de modelo."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

Json = dict[str, Any]


class ModelType(IntEnum):
    """Valor do campo `type` dos modelos retornados por `/api/models`."""

    CHAT = 0
    AUDIO = 1
    IMAGE = 2


@dataclass(frozen=True)
class ChatMessage:
    """Mensagem no formato da API: `content` é sempre uma lista de partes (`text`, `image_url`...)."""

    role: str
    content: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not self.role:
            raise ValueError("role é obrigatório")

    @classmethod
    def text(cls, role: str, text: str) -> ChatMessage:
        return cls(role, ({"type": "text", "text": text},))

    @classmethod
    def with_image(cls, role: str, text: str, image_url: str, detail: str = "auto") -> ChatMessage:
        return cls(role, (
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image_url, "detail": detail}},
        ))

    def to_dict(self) -> Json:
        return {"role": self.role, "content": [dict(part) for part in self.content]}


@dataclass(frozen=True)
class ChatOptions:
    temperature: float = 0.7
    max_tokens: int = 1000
    seed: int | None = None


@dataclass(frozen=True)
class TemplateExecuteOptions:
    """Opções de `TemplateService.execute_template` (query e corpo)."""

    workspace_id: str | None = None
    seed: int | None = None
    model_override: str | None = None
    chat_messages: Sequence[Json] | None = None
    secrets: Mapping[str, Any] | None = field(default=None, repr=False)
