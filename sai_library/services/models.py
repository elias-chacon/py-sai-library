"""`/api/models`: modelos disponíveis para a chave."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sai_library.models import ModelType
from sai_library.result import Result
from sai_library.services.base import BaseService


class ModelService(BaseService):
    """Modelos disponíveis."""

    async def get_models(self) -> Result[Any]:
        return await self._get("/api/models")

    async def get_realtime_models(self) -> Result[Any]:
        return await self._get("/api/models/realtime")

    @staticmethod
    def filter_models_by_type(models: Iterable[Mapping[str, Any]], model_type: ModelType) -> list[Mapping[str, Any]]:
        return [model for model in models if model_type_of(model) == model_type]


# Em 2026-10-30 a API respondeu `type` como texto: "LLM" (chat) e "Image". O ts-sai-library esperava 0/1/2, e
# seu filtro devolvia vazio. "Audio" não apareceu em nenhum modelo: o nome é suposição.
_TYPE_NAMES = {"llm": ModelType.CHAT, "chat": ModelType.CHAT, "image": ModelType.IMAGE, "audio": ModelType.AUDIO}


def model_type_of(model: Mapping[str, Any]) -> ModelType | None:
    """Tipo do modelo a partir de `type`, aceitando texto (formato atual da API) ou número (formato do original)."""
    value = model.get("type")
    if isinstance(value, str):
        return _TYPE_NAMES.get(value.strip().casefold())
    # bool é subclasse de int: `True` não pode ser lido como o tipo 1.
    if isinstance(value, int) and not isinstance(value, bool) and value in ModelType:
        return ModelType(value)
    return None
