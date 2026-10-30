"""Dublês compartilhados pelos testes."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sai_library.http import FileUpload, RequestMethod
from sai_library.result import Result


@dataclass(frozen=True)
class Request:
    """Requisição registrada pelo `FakeHttp`."""

    method: RequestMethod
    url: str
    headers: Mapping[str, str]
    json_body: Any
    file: FileUpload | None


class FakeHttp:
    """`HttpClient` que registra as requisições e devolve as respostas da fila (ou `default`)."""

    def __init__(self, *responses: Result[Any], default: Result[Any] | None = None) -> None:
        self.responses = list(responses)
        self.default = default or Result.ok({}, status=200)
        self.requests: list[Request] = []
        self.closed = False

    async def request(self, method, url, headers, *, json_body=None, file=None) -> Result[Any]:
        self.requests.append(Request(method, url, dict(headers), json_body, file))
        return self.responses.pop(0) if self.responses else self.default

    async def aclose(self) -> None:
        self.closed = True


def chat_reply(content: Any) -> Result[Any]:
    return Result.ok({"choices": [{"message": {"role": "assistant", "content": content}}]}, status=200)


def native_tool_reply(*calls: tuple[str, str, str]) -> Result[Any]:
    """Resposta no formato que o SAI devolve para function calling nativo (OpenAI): (id, nome, argumentos JSON)."""
    tool_calls = [{"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
                  for call_id, name, arguments in calls]
    message = {"role": "assistant", "content": None, "tool_calls": tool_calls}
    return Result.ok({"choices": [{"message": message, "finish_reason": "tool_calls"}]}, status=200)
