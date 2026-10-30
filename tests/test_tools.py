"""Registro de tools a partir da assinatura, validação, execução, instruções e leitura dos blocos <tool_call>."""
# pylint: disable=missing-class-docstring,missing-function-docstring
# As anotações viram texto aqui (como em muitos scripts): o registro precisa resolvê-las.
from __future__ import annotations

import json
import threading
import time
import unittest
from typing import Optional, Union

from sai_library.tools import (
    MAX_OUTPUT_CHARS, NativeToolFormat, ToolArgumentError, ToolCall, ToolCallRecord, ToolRegistry, parse_tool_calls,
)


# Assinatura propositalmente longa: cobre todos os tipos suportados.
def completa(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        texto: str, vezes: int, fator: float, ativo: bool, itens: list[str], extra: dict[str, int],
             opcional: str | None = None, *, nome: Optional[str] = "x") -> str:
    return f"{texto}{vezes}{fator}{ativo}{itens}{extra}{opcional}{nome}"


class RegistrationTest(unittest.TestCase):
    def test_schema_comes_from_signature(self):
        registry = ToolRegistry()
        tool = registry.register(completa, " Descrição ", params={"texto": "o texto"})
        self.assertEqual(tool.description, "Descrição")
        self.assertEqual(tool.schema(), {
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "o texto"},
                "vezes": {"type": "integer"},
                "fator": {"type": "number"},
                "ativo": {"type": "boolean"},
                "itens": {"type": "array"},
                "extra": {"type": "object"},
                "opcional": {"type": ["string", "null"]},
                "nome": {"type": ["string", "null"]},
            },
            "required": ["texto", "vezes", "fator", "ativo", "itens", "extra"],
        })

    def test_decorator_registers_and_returns_function(self):
        registry = ToolRegistry()

        @registry.tool("Soma", name="soma_numeros")
        def somar(a: int, b: int) -> int:
            return a + b

        self.assertEqual(somar(1, 2), 3)
        self.assertEqual([tool.name for tool in registry], ["soma_numeros"])
        self.assertEqual(len(registry), 1)
        self.assertIsNone(registry.get("somar"))

    def test_invalid_signatures_fail_at_registration(self):
        def sem_tipo(a) -> str:
            return a

        def varargs(*a: str) -> str:
            return "".join(a)

        def kwargs(**a: str) -> str:
            return str(a)

        def posicional(a: str, /) -> str:
            return a

        def tupla(a: tuple) -> str:
            return str(a)

        def uniao(a: Union[str, int]) -> str:
            return str(a)

        for function, message in ((sem_tipo, "anotação"), (varargs, "nomeado"), (kwargs, "nomeado"),
                                  (posicional, "nomeado"), (tupla, "não suportado"), (uniao, "não suportado")):
            registry = ToolRegistry()
            with self.subTest(function.__name__), self.assertRaisesRegex(TypeError, message):
                registry.register(function, "x")

    def test_invalid_names_duplicates_and_unknown_param_descriptions(self):
        registry = ToolRegistry()
        registry.register(completa, "x")
        cases = (({"name": "com espaço"}, "inválido"), ({"name": "ação"}, "inválido"), ({"name": "a" * 65}, "inválido"),
                 ({}, "já registrada"), ({"name": "outro", "params": {"zzz": "?"}}, "inexistentes"))
        for kwargs, message in cases:
            with self.subTest(kwargs), self.assertRaisesRegex(ValueError, message):
                registry.register(completa, "x", **kwargs)


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.tool = ToolRegistry().register(completa, "x")
        self.valid = {"texto": "a", "vezes": 1, "fator": 2, "ativo": False, "itens": [], "extra": {}}

    def test_valid_arguments(self):
        self.tool.validate(self.valid)
        self.tool.validate({**self.valid, "opcional": None, "fator": 1.5})

    def test_all_problems_are_reported_together(self):
        with self.assertRaises(ToolArgumentError) as error:
            self.tool.validate({"texto": 1, "vezes": True, "fator": "1", "ativo": 1, "itens": {}, "zzz": 0})
        message = str(error.exception)
        for expected in ("desconhecido 'zzz'", "ausente 'extra'", "'texto' deve ser string",
                         "'vezes' deve ser integer", "'fator' deve ser number", "'ativo' deve ser boolean",
                         "'itens' deve ser array"):
            self.assertIn(expected, message)

    def test_none_only_for_nullable(self):
        with self.assertRaisesRegex(ToolArgumentError, "'texto' deve ser string"):
            self.tool.validate({**self.valid, "texto": None})


class ExecutionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.main_thread = threading.get_ident()
        self.threads = []

        @self.registry.tool("síncrona")
        def sincrona(valor: int) -> dict:
            self.threads.append(threading.get_ident())
            return {"dobro": valor * 2, "texto": "ção"}

        @self.registry.tool("assíncrona")
        async def assincrona(texto: str) -> str:
            return texto.upper()

        @self.registry.tool("falha")
        def falha() -> str:
            raise RuntimeError("deu ruim")

        @self.registry.tool("grande")
        def grande() -> str:
            return "x" * (MAX_OUTPUT_CHARS + 10)

    async def execute(self, name, arguments=None, error=""):
        return await self.registry.execute(ToolCall(name, arguments or {}, error))

    async def test_sync_tool_runs_off_the_event_loop_thread_and_output_is_json(self):
        record = await self.execute("sincrona", {"valor": 21})
        self.assertEqual((record.ok, json.loads(record.output)), (True, {"dobro": 42, "texto": "ção"}))
        self.assertIn("ção", record.output)
        self.assertNotEqual(self.threads, [self.main_thread])

    async def test_async_tool(self):
        self.assertEqual((await self.execute("assincrona", {"texto": "oi"})).output, "OI")

    async def test_errors_become_records_instead_of_exceptions(self):
        cases = [
            ("falha", None, "", "RuntimeError: deu ruim"),
            ("inexistente", None, "", "tool desconhecida; disponíveis: sincrona, assincrona, falha, grande"),
            ("sincrona", {"valor": "1"}, "", "argumentos inválidos: 'valor' deve ser integer"),
            ("", None, "JSON inválido", "JSON inválido"),
        ]
        for name, arguments, error, expected in cases:
            with self.subTest(name=name, error=error):
                record = await self.execute(name, arguments, error)
                self.assertEqual((record.ok, record.output), (False, expected))

    async def test_long_output_is_truncated(self):
        output = (await self.execute("grande")).output
        self.assertTrue(output.endswith(f"[saída truncada em {MAX_OUTPUT_CHARS} caracteres]"))
        self.assertLess(len(output), MAX_OUTPUT_CHARS + 100)

    async def test_call_id_is_kept_in_record(self):
        record = await self.registry.execute(ToolCall("assincrona", {"texto": "a"}, call_id="call_9"))
        self.assertEqual(record.call_id, "call_9")

    def test_native_definitions_in_each_provider_format(self):
        schema = self.registry.get("sincrona").schema()
        responses = self.registry.native_definitions(NativeToolFormat.RESPONSES)[0]
        chat = self.registry.native_definitions(NativeToolFormat.CHAT_COMPLETIONS)[0]
        self.assertEqual(responses, {"type": "function", "name": "sincrona", "description": "síncrona",
                                     "parameters": schema})
        self.assertEqual(chat, {"type": "function", "function": {"name": "sincrona", "description": "síncrona",
                                                                 "parameters": schema}})

    def test_record_message_format(self):
        self.assertEqual(ToolCallRecord("t", {}, "saída", ok=False).as_message(),
                         '<tool_result name="t" status="erro">\nsaída\n</tool_result>')


class InstructionsTest(unittest.TestCase):
    def test_lists_each_tool_with_schema_and_call_format(self):
        registry = ToolRegistry()
        registry.register(completa, "Faz tudo", params={"texto": "descrição com acento"})
        text = registry.instructions()
        self.assertIn("<tool_call>\n{\"tool\": \"<nome da ferramenta>\", \"arguments\": {<argumentos em JSON>}}", text)
        self.assertIn('<tool_result name="<nome da ferramenta>" status="ok">', text)
        self.assertIn("- completa: Faz tudo\n  Argumentos (JSON Schema): ", text)
        self.assertIn(json.dumps(registry.get("completa").schema(), ensure_ascii=False), text)


class ParseTest(unittest.TestCase):
    def test_no_blocks(self):
        self.assertEqual(parse_tool_calls("Resposta final sem ferramentas."), [])

    def test_blocks_in_order_with_surrounding_text(self):
        text = ('Vou consultar.\n<tool_call>\n{"tool": "a", "arguments": {"x": 1}}\n</tool_call>\n'
                '<tool_call>{"tool": "b"}</tool_call> fim')
        self.assertEqual(parse_tool_calls(text), [ToolCall("a", {"x": 1}), ToolCall("b", {})])

    def test_malformed_blocks_become_calls_with_error(self):
        cases = {
            "<tool_call>{nao é json}</tool_call>": "JSON inválido",
            "<tool_call>[1, 2]</tool_call>": 'precisa ser {"tool"',
            '<tool_call>{"arguments": {}}</tool_call>': 'precisa ser {"tool"',
            '<tool_call>{"tool": "a", "arguments": [1]}</tool_call>': '"arguments" precisa ser um objeto',
            '<tool_call>{"tool": "a"}': "sem </tool_call>",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                calls = parse_tool_calls(text)
                self.assertEqual(len(calls), 1)
                self.assertIn(expected, calls[0].error)

    def test_large_adversarial_input_is_linear(self):
        text = "<tool_call>" + "x" * 200_000 + "<tool_call>" * 20_000
        started = time.perf_counter()
        calls = parse_tool_calls(text)
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
