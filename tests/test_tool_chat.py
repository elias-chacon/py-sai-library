"""Laço da conversa com tools: pedido do modelo, execução, devolução do resultado e resposta final."""
# pylint: disable=missing-class-docstring,missing-function-docstring
import unittest

from sai_library.config import SaiSettings
from sai_library.extensions import content_text
from sai_library.library import SAILibrary
from sai_library.result import Result
from sai_library.tool_chat import ToolMode, run_tool_chat
from sai_library.tools import NativeToolFormat, ToolRegistry
from tests.support import FakeHttp, chat_reply, native_tool_reply

CALL_SOMAR = '<tool_call>{"tool": "somar", "arguments": {"a": 2, "b": 3}}</tool_call>'


def registry():
    tools = ToolRegistry()

    @tools.tool("Soma dois números")
    def somar(a: float, b: float) -> float:
        return a + b

    return tools


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []
        self.tools = []

    async def __call__(self, messages, tools=None):
        self.sent.append([dict(message) for message in messages])
        self.tools.append(tools)
        return self.replies.pop(0)


def text_of(message):
    return content_text(message["content"])


class RunToolChatTest(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_then_final_answer(self):
        model = ScriptedModel(chat_reply(CALL_SOMAR), chat_reply("  A soma é 5.  "))
        result = await run_tool_chat(model, registry(), "Quanto é 2 + 3?", system_prompt="Seja breve.")
        self.assertTrue(result.success)
        conversation = result.data
        self.assertEqual(conversation.answer, "A soma é 5.")
        self.assertEqual([(c.name, dict(c.arguments), c.output, c.ok) for c in conversation.calls],
                         [("somar", {"a": 2, "b": 3}, "5", True)])
        roles = [m["role"] for m in conversation.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant"])
        system = text_of(conversation.messages[0])
        self.assertTrue(system.startswith("Seja breve.\n\nVocê pode usar as ferramentas"))
        self.assertIn("- somar: Soma dois números", system)
        self.assertEqual(text_of(conversation.messages[3]), '<tool_result name="somar" status="ok">\n5\n</tool_result>')
        self.assertEqual(len(model.sent[1]), 4, "a segunda chamada leva o resultado da tool")

    async def test_tool_errors_are_fed_back_to_the_model(self):
        model = ScriptedModel(chat_reply('<tool_call>{"tool": "dividir"}</tool_call>'), chat_reply("Não consigo."))
        result = await run_tool_chat(model, registry(), "?")
        self.assertEqual(result.data.answer, "Não consigo.")
        self.assertIn('status="erro">\ntool desconhecida; disponíveis: somar', text_of(result.data.messages[3]))

    async def test_round_limit_returns_error_with_partial_conversation(self):
        model = ScriptedModel(*[chat_reply(CALL_SOMAR)] * 3)
        result = await run_tool_chat(model, registry(), "?", max_rounds=3)
        self.assertFalse(result.success)
        self.assertIn("Limite de 3 rodadas", result.error_message)
        self.assertEqual(len(result.metadata["conversation"].calls), 3)

    async def test_api_failure_and_empty_reply(self):
        cases = (
            (Result.error("HTTP 401: chave inválida", status=401), "HTTP 401: chave inválida"),
            (Result.ok({"choices": []}, status=200), "sem conteúdo de texto"),
        )
        for reply, message in cases:
            with self.subTest(message):
                result = await run_tool_chat(ScriptedModel(reply), registry(), "?")
                self.assertFalse(result.success)
                self.assertIn(message, result.error_message)

    async def test_content_in_parts_is_understood(self):
        model = ScriptedModel(chat_reply([{"type": "text", "text": CALL_SOMAR}]), chat_reply("5"))
        result = await run_tool_chat(model, registry(), "?")
        self.assertEqual((result.data.answer, len(result.data.calls)), ("5", 1))


class NativeModeTest(unittest.IsolatedAsyncioTestCase):
    async def test_native_cycle_uses_tools_field_and_tool_messages(self):
        model = ScriptedModel(native_tool_reply(("call_1", "somar", '{"a": 2, "b": 3}')), chat_reply("5"))
        result = await run_tool_chat(model, registry(), "2+3?", system_prompt="Seja breve.", mode=ToolMode.NATIVE)
        self.assertEqual((result.data.answer, result.data.mode), ("5", ToolMode.NATIVE))
        expected_tools = registry().native_definitions(NativeToolFormat.CHAT_COMPLETIONS)
        self.assertEqual(model.tools[0], expected_tools, "sem formato informado, usa o de chat completions")
        system, user, assistant, tool, final = result.data.messages
        self.assertEqual(text_of(system), "Seja breve.", "sem instruções de <tool_call> no modo nativo")
        self.assertEqual(text_of(user), "2+3?")
        self.assertEqual((assistant["content"], assistant["tool_calls"][0]["id"]), (None, "call_1"))
        self.assertEqual(tool, {"role": "tool", "tool_call_id": "call_1", "content": "5"})
        self.assertEqual(final["content"], "5")
        self.assertEqual([(c.name, c.call_id, c.ok) for c in result.data.calls], [("somar", "call_1", True)])

    async def test_native_format_is_passed_to_the_tools_field(self):
        model = ScriptedModel(chat_reply("ok"))
        await run_tool_chat(model, registry(), "?", mode=ToolMode.NATIVE, native_format=NativeToolFormat.RESPONSES)
        self.assertEqual(model.tools[0][0]["name"], "somar")

    async def test_without_system_prompt_starts_with_user_message(self):
        model = ScriptedModel(chat_reply("oi"))
        result = await run_tool_chat(model, registry(), "olá", mode=ToolMode.NATIVE)
        self.assertEqual([m["role"] for m in result.data.messages], ["user", "assistant"])

    async def test_bad_arguments_and_unknown_tool_go_back_as_errors(self):
        reply = native_tool_reply(("c1", "somar", "{nao json"), ("c2", "somar", "[1]"), ("c3", "dividir", "{}"))
        model = ScriptedModel(reply, chat_reply("ok"))
        result = await run_tool_chat(model, registry(), "?", mode=ToolMode.NATIVE)
        tool_messages = [m for m in result.data.messages if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["c1", "c2", "c3"])
        self.assertEqual(tool_messages[0]["content"], "erro: argumentos não são JSON válido")
        self.assertEqual(tool_messages[1]["content"], "erro: argumentos precisam ser um objeto JSON")
        self.assertTrue(tool_messages[2]["content"].startswith("erro: tool desconhecida"))

    async def test_empty_native_reply_is_an_error(self):
        # Comportamento real do Gemini pelo SAI: 200 com content "" e sem tool_calls.
        result = await run_tool_chat(ScriptedModel(chat_reply("")), registry(), "?", mode=ToolMode.NATIVE)
        self.assertIn("sem conteúdo de texto nem pedido de tool", result.error_message)

    async def test_prompt_mode_sends_no_tools_field(self):
        model = ScriptedModel(chat_reply("5"))
        await run_tool_chat(model, registry(), "?")
        self.assertEqual(model.tools, [None])

    async def test_auto_must_be_resolved_by_the_library(self):
        model, tools = ScriptedModel(), registry()
        with self.assertRaisesRegex(ValueError, "resolvido"):
            await run_tool_chat(model, tools, "?", mode=ToolMode.AUTO)


class ChatWithToolsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http = FakeHttp(Result.ok([{"name": "gpt", "type": 0}], status=200))
        self.sai = SAILibrary(SaiSettings("https://sai.test", "k"), self.http)

    async def test_requires_selected_model(self):
        result = await self.sai.chat_with_tools("?", registry())
        self.assertIn("Nenhum modelo selecionado", result.error_message)
        self.assertEqual(self.http.requests, [])

    async def test_uses_chat_endpoint_with_selected_model(self):
        await self.sai.refresh_models()
        self.sai.set_model("gpt")
        self.http.responses = [chat_reply(CALL_SOMAR), chat_reply("5")]
        result = await self.sai.chat_with_tools("2+3?", registry(), max_rounds=2)
        self.assertEqual(result.data.answer, "5")
        chat_requests = self.http.requests[1:]
        self.assertEqual([r.url for r in chat_requests], ["https://sai.test/api/prompt/v1/chat/completions"] * 2)
        self.assertEqual({r.json_body["model"] for r in chat_requests}, {"gpt"})

    async def test_auto_mode_and_tool_format_follow_the_provider(self):
        self.http.responses = [Result.ok([{"name": "gpt", "type": "LLM", "provider": "OPENAI"},
                                          {"name": "emea", "type": "LLM", "provider": "EMEA"},
                                          {"name": "gemini", "type": "LLM", "provider": "GOOGLE"},
                                          {"name": "sem-provider", "type": "LLM"}], status=200)]
        await self.sai.refresh_models()
        cases = {
            "gpt": (ToolMode.NATIVE, NativeToolFormat.RESPONSES),
            "emea": (ToolMode.NATIVE, NativeToolFormat.CHAT_COMPLETIONS),
            "gemini": (ToolMode.PROMPT, NativeToolFormat.CHAT_COMPLETIONS),
            "sem-provider": (ToolMode.PROMPT, NativeToolFormat.CHAT_COMPLETIONS),
            "desconhecido": (ToolMode.PROMPT, NativeToolFormat.CHAT_COMPLETIONS),
        }
        for name, expected in cases.items():
            with self.subTest(name):
                actual = (self.sai.tool_mode_for(name), self.sai.native_tool_format_for(name))
                self.assertEqual(actual, expected)
        tool_name_in = {"gpt": lambda tool: tool["name"], "emea": lambda tool: tool["function"]["name"]}
        for name, read_name in tool_name_in.items():
            with self.subTest(f"auto {name}"):
                self.sai.set_model(name)
                self.http.responses = [chat_reply("5")]
                result = await self.sai.chat_with_tools("?", registry(), mode=ToolMode.AUTO)
                self.assertEqual(result.data.mode, ToolMode.NATIVE)
                self.assertEqual(read_name(self.http.requests[-1].json_body["tools"][0]), "somar")


if __name__ == "__main__":
    unittest.main()
