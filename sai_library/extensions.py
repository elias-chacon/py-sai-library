"""Utilitários sobre resultados e conversas (equivalentes às `extensions` do ts-sai-library)."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from sai_library.result import Result


async def execute_with_retry[T](
    operation: Callable[[], Awaitable[Result[T]]],
    max_attempts: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Result[T]:
    """Repete a operação até sucesso, com espera de 2ⁿ segundos. Para repetir só falhas transitórias de rede,
    prefira `with_retry()` no builder, que atua no transporte."""
    attempts = max(1, max_attempts)
    result: Result[T] = Result.error("Nenhuma tentativa feita")
    for attempt in range(1, attempts + 1):
        result = await operation()
        if result.success:
            return result
        if attempt < attempts:
            await sleep(2.0**attempt)
    return result


def extract_text(chat_result: Result[Any]) -> list[str]:
    """Textos de `choices[].message.content`. Conteúdo em partes (`[{"type": "text"...}]`) é concatenado."""
    if not chat_result.success or not isinstance(chat_result.data, Mapping):
        return []
    choices = chat_result.data.get("choices")
    if not isinstance(choices, list):
        return []
    texts = (_message_text(choice) for choice in choices if isinstance(choice, Mapping))
    return [text for text in texts if text is not None]


def _message_text(choice: Mapping[str, Any]) -> str | None:
    message = choice.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    return None if content is None else content_text(content)


def content_text(content: Any) -> str:
    """Texto de um `content` de mensagem, seja string ou lista de partes."""
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, Mapping))
    return str(content)


def conversation_context(messages: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Resumo de um histórico: quantidade, papéis e tamanho total do texto (string ou partes `text`)."""
    messages = list(messages)
    roles = [message["role"] for message in messages if isinstance(message.get("role"), str)]
    total_length = sum(len(content_text(message["content"])) for message in messages if message.get("content"))
    return {
        "message_count": len(messages),
        "roles": roles,
        "total_length": total_length,
        "unique_roles": list(dict.fromkeys(roles)),
    }
