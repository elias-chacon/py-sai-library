"""`/api/prompt/v1/chat/completions`: conversa com um modelo."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sai_library.models import ChatOptions
from sai_library.result import Result
from sai_library.services.base import BaseService, compact


class ChatService(BaseService):
    """Chat completions."""

    async def send_completion(
        self,
        messages: Sequence[Mapping[str, Any]],
        model: str,
        options: ChatOptions | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> Result[Any]:
        """`seed` e `tools` (function calling nativo) só são enviados quando informados; `seed=0` é válido."""
        options = options or ChatOptions()
        data = {
            "messages": [dict(message) for message in messages],
            "model": model,
            "temperature": options.temperature,
            "max_tokens": options.max_tokens,
            **compact(seed=options.seed, tools=[dict(tool) for tool in tools or ()]),
        }
        return await self._post("/api/prompt/v1/chat/completions", data)
