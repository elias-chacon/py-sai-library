"""Resultado de uma chamada à API: erros HTTP e de rede viram `Result.error`, nunca exceção."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Result[T]:
    """`success` indica se `data` é válido; em erro, `error_message` explica e `metadata` pode trazer `status`."""

    success: bool
    data: T | None = None
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, **metadata: Any) -> Result[T]:
        return cls(True, data, "", metadata)

    @classmethod
    def error(cls, message: str, **metadata: Any) -> Result[T]:
        return cls(False, None, message, metadata)
