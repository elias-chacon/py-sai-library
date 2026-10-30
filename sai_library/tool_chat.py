"""Conversa com tools: o modelo pede tools, a lib executa e devolve o resultado, até a resposta final.

Dois protocolos compartilham o mesmo laço (`run_tool_chat`):

- `ToolMode.PROMPT`: as instruções e o formato `<tool_call>` vão no prompt de sistema. Funciona com qualquer modelo.
- `ToolMode.NATIVE`: function calling da API (`tools` → `tool_calls` → mensagens `role: "tool"`). O SAI repassa
  `tools` sem normalizar, então o formato depende do provedor (`NativeToolFormat`). Verificado com OPENAI e EMEA;
  no Gemini a chamada é descartada.

`ToolMode.AUTO` é resolvido pela `SAILibrary` (nativo para os provedores verificados, prompt nos demais) antes de
chegar aqui.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from sai_library.extensions import content_text, extract_text
from sai_library.models import ChatMessage, Json
from sai_library.result import Result
from sai_library.tools import NativeToolFormat, ToolCall, ToolCallRecord, ToolRegistry, parse_tool_calls

# Recebe o histórico e o campo `tools` (None no modo por prompt) e faz uma chamada à API.
Completer = Callable[[Sequence[Json], Sequence[Json] | None], Awaitable[Result[Any]]]
DEFAULT_MAX_ROUNDS = 5


class ToolMode(StrEnum):
    PROMPT = "prompt"
    NATIVE = "native"
    AUTO = "auto"


@dataclass(frozen=True)
class ToolConversation:
    """`answer` é a resposta final; `messages` é o histórico enviado à API; `calls`, as tools executadas."""

    answer: str
    messages: tuple[Json, ...]
    calls: tuple[ToolCallRecord, ...]
    mode: ToolMode = ToolMode.PROMPT


@dataclass(frozen=True)
class Reply:
    """Resposta do modelo já interpretada: mensagem para o histórico, texto e tools pedidas."""

    message: Json
    text: str
    calls: list[ToolCall] = field(default_factory=list)


class ToolProtocol(Protocol):
    """Diferença entre os modos: como as tools chegam ao modelo e como os pedidos e resultados são trocados."""

    def initial_messages(self, message: str, system_prompt: str | None) -> list[Json]: ...

    def tools_field(self) -> list[Json] | None: ...

    def read_reply(self, result: Result[Any]) -> Reply | None:
        """None quando a resposta não tem texto nem pedido de tool."""

    def result_messages(self, records: Sequence[ToolCallRecord]) -> list[Json]: ...


class PromptProtocol:
    """Ensina o formato `<tool_call>` no prompt de sistema e devolve os resultados como mensagem do usuário."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def initial_messages(self, message: str, system_prompt: str | None) -> list[Json]:
        system = "\n\n".join(part for part in (system_prompt, self.registry.instructions()) if part)
        return [ChatMessage.text("system", system).to_dict(), ChatMessage.text("user", message).to_dict()]

    def tools_field(self) -> list[Json] | None:
        return None

    def read_reply(self, result: Result[Any]) -> Reply | None:
        texts = extract_text(result)
        if not texts:
            return None
        return Reply(ChatMessage.text("assistant", texts[0]).to_dict(), texts[0], parse_tool_calls(texts[0]))

    def result_messages(self, records: Sequence[ToolCallRecord]) -> list[Json]:
        return [ChatMessage.text("user", "\n".join(record.as_message() for record in records)).to_dict()]


class NativeProtocol:
    """Envia as definições no campo `tools` e devolve cada resultado numa mensagem `role: "tool"`."""

    def __init__(self, registry: ToolRegistry, tool_format: NativeToolFormat) -> None:
        self.registry = registry
        self.tool_format = tool_format

    def initial_messages(self, message: str, system_prompt: str | None) -> list[Json]:
        messages = [ChatMessage.text("user", message).to_dict()]
        if system_prompt:
            messages.insert(0, ChatMessage.text("system", system_prompt).to_dict())
        return messages

    def tools_field(self) -> list[Json] | None:
        return self.registry.native_definitions(self.tool_format)

    def read_reply(self, result: Result[Any]) -> Reply | None:
        """Pedidos vêm em `message.tool_calls`; o histórico guarda a mensagem com eles, como a API exige."""
        message = _first_message(result)
        if message is None:
            return None
        raw_calls = [call for call in message.get("tool_calls") or () if isinstance(call, Mapping)]
        content = message.get("content")
        text = content_text(content) if content is not None else ""
        if not raw_calls and not text.strip():
            return None
        history: Json = {"role": "assistant", "content": content}
        if raw_calls:
            history["tool_calls"] = [dict(call) for call in raw_calls]
        return Reply(history, text, [_native_call(call) for call in raw_calls])

    def result_messages(self, records: Sequence[ToolCallRecord]) -> list[Json]:
        return [
            {"role": "tool", "tool_call_id": record.call_id, "content": _native_content(record)} for record in records
        ]


def _native_content(record: ToolCallRecord) -> str:
    return record.output if record.ok else f"erro: {record.output}"


def _first_message(result: Result[Any]) -> Mapping[str, Any] | None:
    data = result.data if isinstance(result.data, Mapping) else {}
    choices = data.get("choices")
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], Mapping) else {}
    message = first.get("message")
    return message if isinstance(message, Mapping) else None


def _native_call(raw: Mapping[str, Any]) -> ToolCall:
    """`function.arguments` vem como texto JSON; texto inválido vira chamada com erro, devolvida ao modelo."""
    function = raw.get("function") if isinstance(raw.get("function"), Mapping) else {}
    name, call_id = str(function.get("name", "")), str(raw.get("id", ""))
    try:
        arguments = json.loads(function.get("arguments") or "{}")
    except (TypeError, json.JSONDecodeError):
        return ToolCall(name, {}, "argumentos não são JSON válido", call_id)
    if not isinstance(arguments, dict):
        return ToolCall(name, {}, "argumentos precisam ser um objeto JSON", call_id)
    return ToolCall(name, arguments, call_id=call_id)


def _protocol(mode: ToolMode, registry: ToolRegistry, native_format: NativeToolFormat) -> ToolProtocol:
    if mode is ToolMode.PROMPT:
        return PromptProtocol(registry)
    if mode is ToolMode.NATIVE:
        return NativeProtocol(registry, native_format)
    raise ValueError(f"Modo {mode!r} precisa ser resolvido antes (PROMPT ou NATIVE)")


async def run_tool_chat(  # pylint: disable=too-many-arguments  # opcionais só por nome (após *)
    complete: Completer,
    registry: ToolRegistry,
    message: str,
    *,
    system_prompt: str | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    mode: ToolMode = ToolMode.PROMPT,
    native_format: NativeToolFormat = NativeToolFormat.CHAT_COMPLETIONS,
) -> Result[ToolConversation]:
    """Cada rodada é uma chamada à API. Esgotar `max_rounds` é erro, com a conversa parcial em `metadata`.

    `native_format` só vale no modo NATIVE. ValueError para `ToolMode.AUTO`: a escolha depende do modelo e é feita
    por `SAILibrary.chat_with_tools`.
    """
    protocol = _protocol(mode, registry, native_format)
    messages = protocol.initial_messages(message, system_prompt)
    calls: list[ToolCallRecord] = []
    for _ in range(max(1, max_rounds)):
        result = await complete(messages, protocol.tools_field())
        if not result.success:
            return Result.error(result.error_message, **result.metadata)
        reply = protocol.read_reply(result)
        if reply is None:
            return Result.error("Resposta do modelo sem conteúdo de texto nem pedido de tool", response=result.data)
        messages.append(reply.message)
        if not reply.calls:
            return Result.ok(ToolConversation(reply.text.strip(), tuple(messages), tuple(calls), mode))
        records = [await registry.execute(call) for call in reply.calls]
        calls.extend(records)
        messages.extend(protocol.result_messages(records))
    partial = ToolConversation("", tuple(messages), tuple(calls), mode)
    return Result.error(f"Limite de {max_rounds} rodadas atingido sem resposta final", conversation=partial)
