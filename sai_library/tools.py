"""Tools: funções do script que o modelo pode pedir para executar.

O modelo aprende a acioná-las pelas instruções de `ToolRegistry.instructions()`, injetadas no prompt de sistema:
ele responde com blocos `<tool_call>{"tool": ..., "arguments": {...}}</tool_call>`, e a lib devolve o resultado em
`<tool_result>`. O laço da conversa fica em `tool_chat.py`.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
import types
import typing
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CALL_OPEN = "<tool_call>"
CALL_CLOSE = "</tool_call>"
MAX_OUTPUT_CHARS = 20_000
_NAME = re.compile(r"[A-Za-z_]\w{0,63}", re.ASCII)
_JSON_TYPES: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array",
                                dict: "object"}

INSTRUCTIONS = """\
Você pode usar as ferramentas listadas abaixo. Elas são funções executadas pelo programa que conversa com você.

Para usar uma ferramenta, responda SOMENTE com um ou mais blocos neste formato, sem texto antes ou depois:
<tool_call>
{{"tool": "<nome da ferramenta>", "arguments": {{<argumentos em JSON>}}}}
</tool_call>

O programa executa cada ferramenta e responde com:
<tool_result name="<nome da ferramenta>" status="ok">resultado</tool_result>
Se status="erro", corrija os argumentos ou continue sem a ferramenta.

Quando tiver a resposta final, responda normalmente, sem nenhum bloco <tool_call>.
Use apenas as ferramentas e os argumentos descritos.

Ferramentas disponíveis:
{tools}"""


class NativeToolFormat(StrEnum):
    """Formato do campo `tools`. O SAI repassa o campo sem normalizar, e cada provedor exige um (2026-10-30)."""

    RESPONSES = "responses"  # {"type": "function", "name", ...}: provedor OPENAI (API Responses)
    CHAT_COMPLETIONS = "chat_completions"  # {"type": "function", "function": {...}}: provedor EMEA


class ToolArgumentError(ValueError):
    """Argumentos enviados pelo modelo não batem com a assinatura da tool."""


@dataclass(frozen=True)
class ToolParameter:
    """Parâmetro de uma tool, com o tipo JSON derivado da anotação Python."""

    name: str
    json_type: str
    required: bool
    nullable: bool = False
    description: str = ""

    def schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": [self.json_type, "null"] if self.nullable else self.json_type}
        if self.description:
            schema["description"] = self.description
        return schema

    def accepts(self, value: Any) -> bool:
        """Se o valor enviado pelo modelo tem o tipo JSON esperado (bool não conta como número)."""
        if value is None:
            return self.nullable
        if isinstance(value, bool):
            return self.json_type == "boolean"
        if self.json_type == "number":
            return isinstance(value, (int, float))
        return isinstance(value, _python_type(self.json_type))


def _python_type(json_type: str) -> type:
    return next(python for python, name in _JSON_TYPES.items() if name == json_type)


@dataclass(frozen=True)
class Tool:
    """Função registrada, com nome, descrição e parâmetros mostrados ao modelo."""

    name: str
    description: str
    function: Callable[..., Any]
    parameters: tuple[ToolParameter, ...]

    def schema(self) -> dict[str, Any]:
        """JSON Schema dos argumentos, mostrado ao modelo nas instruções."""
        return {
            "type": "object",
            "properties": {parameter.name: parameter.schema() for parameter in self.parameters},
            "required": [parameter.name for parameter in self.parameters if parameter.required],
        }

    def native_definition(self, tool_format: NativeToolFormat) -> dict[str, Any]:
        """Definição para o campo `tools` (function calling nativo), no formato que o provedor do modelo aceita."""
        function = {"name": self.name, "description": self.description, "parameters": self.schema()}
        if tool_format is NativeToolFormat.RESPONSES:
            return {"type": "function", **function}
        return {"type": "function", "function": function}

    def validate(self, arguments: Mapping[str, Any]) -> None:
        """ToolArgumentError com todos os problemas encontrados, para o modelo corrigir de uma vez."""
        known = {parameter.name: parameter for parameter in self.parameters}
        problems = [f"argumento desconhecido '{name}'" for name in arguments if name not in known]
        problems += [f"argumento obrigatório ausente '{p.name}'" for p in self.parameters
                     if p.required and p.name not in arguments]
        problems += [f"'{name}' deve ser {known[name].json_type}" for name, value in arguments.items()
                     if name in known and not known[name].accepts(value)]
        if problems:
            raise ToolArgumentError("; ".join(problems))

    async def run(self, arguments: Mapping[str, Any]) -> Any:
        """Funções síncronas rodam em thread, para não bloquear o event loop."""
        self.validate(arguments)
        if inspect.iscoroutinefunction(self.function):
            return await self.function(**arguments)
        return await asyncio.to_thread(self.function, **arguments)


@dataclass(frozen=True)
class ToolCall:
    """Pedido do modelo. `error` preenchido quando o pedido não pôde ser interpretado.

    `call_id` só existe no modo nativo: o resultado precisa citá-lo (`tool_call_id`).
    """

    name: str
    arguments: Mapping[str, Any]
    error: str = ""
    call_id: str = ""


@dataclass(frozen=True)
class ToolCallRecord:
    """Execução de uma tool; `as_message()` é o texto devolvido ao modelo no modo por prompt."""

    name: str
    arguments: Mapping[str, Any]
    output: str
    ok: bool
    call_id: str = ""

    def as_message(self) -> str:
        status = "ok" if self.ok else "erro"
        return f'<tool_result name="{self.name}" status="{status}">\n{self.output}\n</tool_result>'


class ToolRegistry:
    """Conjunto de tools de uma conversa. Registre com `@registry.tool("descrição")`."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def tool(
        self, description: str, *, name: str | None = None, params: Mapping[str, str] | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorador; `params` descreve cada parâmetro para o modelo (ex.: formato esperado)."""
        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            self.register(function, description, name=name, params=params)
            return function
        return decorator

    def register(
        self,
        function: Callable[..., Any],
        description: str,
        *,
        name: str | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Tool:
        """TypeError/ValueError no registro, nunca durante a conversa: assinatura inválida falha cedo."""
        tool_name = name or function.__name__
        if not _NAME.fullmatch(tool_name):
            raise ValueError(f"Nome de tool inválido: {tool_name!r} (letras, dígitos e _, até 64)")
        if tool_name in self._tools:
            raise ValueError(f"Tool já registrada: {tool_name}")
        tool = Tool(tool_name, description.strip(), function, _parameters(function, params or {}))
        self._tools[tool_name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def instructions(self) -> str:
        """Texto do prompt de sistema que ensina o modelo a acionar as tools registradas."""
        listing = "\n".join(
            f"- {tool.name}: {tool.description}\n"
            f"  Argumentos (JSON Schema): {json.dumps(tool.schema(), ensure_ascii=False)}"
            for tool in self
        )
        return INSTRUCTIONS.format(tools=listing)

    def native_definitions(self, tool_format: NativeToolFormat) -> list[dict[str, Any]]:
        return [tool.native_definition(tool_format) for tool in self]

    async def execute(self, call: ToolCall) -> ToolCallRecord:
        """Nunca lança: erros da chamada ou da tool voltam ao modelo como resultado com status "erro"."""
        output, ok = await self._run(call)
        return ToolCallRecord(call.name, call.arguments, output, ok, call.call_id)

    async def _run(self, call: ToolCall) -> tuple[str, bool]:
        if call.error:
            return call.error, False
        tool = self.get(call.name)
        if tool is None:
            return f"tool desconhecida; disponíveis: {', '.join(t.name for t in self) or 'nenhuma'}", False
        try:
            output = await tool.run(call.arguments)
        except ToolArgumentError as exc:
            return f"argumentos inválidos: {exc}", False
        except Exception as exc:  # pylint: disable=broad-exception-caught  # erro da tool vira resposta ao modelo
            return f"{type(exc).__name__}: {exc}", False
        return _render_output(output), True


def _parameters(function: Callable[..., Any], descriptions: Mapping[str, str]) -> tuple[ToolParameter, ...]:
    signature = inspect.signature(function)
    unknown = set(descriptions) - set(signature.parameters)
    if unknown:
        raise ValueError(f"{function.__name__}: descrição para parâmetros inexistentes: {sorted(unknown)}")
    hints = typing.get_type_hints(function)  # resolve anotações em texto (`from __future__ import annotations`)
    return tuple(
        _parameter(function.__name__, parameter, hints, descriptions.get(parameter.name, ""))
        for parameter in signature.parameters.values()
    )


def _parameter(owner: str, parameter: inspect.Parameter, hints: Mapping[str, Any], description: str) -> ToolParameter:
    if parameter.kind not in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY):
        raise TypeError(f"{owner}: parâmetro '{parameter.name}' precisa ser nomeado (sem *args, **kwargs ou /)")
    if parameter.name not in hints:
        raise TypeError(f"{owner}: parâmetro '{parameter.name}' precisa de anotação de tipo")
    json_type, nullable = _json_type(owner, parameter.name, hints[parameter.name])
    return ToolParameter(parameter.name, json_type, parameter.default is parameter.empty, nullable, description)


def _json_type(owner: str, name: str, annotation: Any) -> tuple[str, bool]:
    """Tipos aceitos: str, int, float, bool, list[...], dict[...] e as mesmas opções com `| None`."""
    nullable = False
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        options = [arg for arg in typing.get_args(annotation) if arg is not types.NoneType]
        nullable = len(options) < len(typing.get_args(annotation))
        if len(options) == 1:
            annotation = options[0]
    base = typing.get_origin(annotation) or annotation
    if base not in _JSON_TYPES:
        raise TypeError(f"{owner}: tipo de '{name}' não suportado: {annotation!r}")
    return _JSON_TYPES[base], nullable


def _render_output(output: Any) -> str:
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"\n[saída truncada em {MAX_OUTPUT_CHARS} caracteres]"
    return text


def parse_tool_calls(text: str) -> list[ToolCall]:
    """Blocos `<tool_call>` da resposta, na ordem. Bloco sem fechamento ou JSON inválido vira chamada com erro."""
    calls: list[ToolCall] = []
    start = text.find(CALL_OPEN)
    while start != -1:
        body_start = start + len(CALL_OPEN)
        end = text.find(CALL_CLOSE, body_start)
        if end == -1:
            calls.append(ToolCall("", {}, f"bloco {CALL_OPEN} sem {CALL_CLOSE}"))
            break
        calls.append(_parse_call(text[body_start:end]))
        start = text.find(CALL_OPEN, end + len(CALL_CLOSE))
    return calls


def _parse_call(body: str) -> ToolCall:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return ToolCall("", {}, f"JSON inválido no bloco {CALL_OPEN}: {exc.msg}")
    if not isinstance(payload, dict) or not isinstance(payload.get("tool"), str):
        return ToolCall("", {}, 'o bloco precisa ser {"tool": "<nome>", "arguments": {...}}')
    arguments = payload.get("arguments", {})
    if not isinstance(arguments, dict):
        return ToolCall(payload["tool"], {}, '"arguments" precisa ser um objeto JSON')
    return ToolCall(payload["tool"], arguments)
