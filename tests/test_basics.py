"""Result, URLs, mensagens e extensões."""
# pylint: disable=missing-class-docstring,missing-function-docstring
import unittest

from sai_library.extensions import conversation_context, execute_with_retry, extract_text
from sai_library.models import ChatMessage, TemplateExecuteOptions
from sai_library.result import Result
from sai_library.uri import build_uri, path_segment
from tests.support import chat_reply


class ResultTest(unittest.TestCase):
    def test_factories(self):
        self.assertEqual(Result.ok([1], status=200), Result(True, [1], "", {"status": 200}))
        self.assertEqual(Result.error("falhou"), Result(False, None, "falhou", {}))


class UriTest(unittest.TestCase):
    def test_build_uri(self):
        cases = [
            ("https://sai/", "/api/x", None, "https://sai/api/x"),
            ("https://sai", "api/x", {}, "https://sai/api/x"),
            ("https://sai", "/api/x", {"a": None, "b": "c d&e"}, "https://sai/api/x?b=c%20d%26e"),
            ("https://sai", "/x", {"ids": [1, 2], "on": True, "off": False},
             "https://sai/x?ids=1&ids=2&on=true&off=false"),
            ("https://sai", "/x", {"vazio": []}, "https://sai/x"),
        ]
        for base, endpoint, query, expected in cases:
            with self.subTest(expected):
                self.assertEqual(build_uri(base, endpoint, query), expected)

    def test_path_segment_cannot_change_the_route(self):
        self.assertEqual(path_segment("../a/b?c#d"), "..%2Fa%2Fb%3Fc%23d")


class ChatMessageTest(unittest.TestCase):
    def test_text_and_image(self):
        self.assertEqual(ChatMessage.text("user", "oi").to_dict(),
                         {"role": "user", "content": [{"type": "text", "text": "oi"}]})
        self.assertEqual(ChatMessage.with_image("user", "veja", "https://img").to_dict()["content"][1],
                         {"type": "image_url", "image_url": {"url": "https://img", "detail": "auto"}})

    def test_role_is_required(self):
        with self.assertRaises(ValueError):
            ChatMessage.text("", "oi")

    def test_secrets_are_hidden_from_repr(self):
        self.assertNotIn("senha", repr(TemplateExecuteOptions(secrets={"k": "senha"})))


class ExtensionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_with_retry(self):
        delays = []

        async def sleep(seconds):
            delays.append(seconds)

        results = [Result.error("1"), Result.error("2"), Result.ok("ok")]

        async def operation():
            return results.pop(0)

        self.assertEqual((await execute_with_retry(operation, 5, sleep)).data, "ok")
        self.assertEqual(delays, [2.0, 4.0])
        failures = [Result.error("a"), Result.error("b")]

        async def failing():
            return failures.pop(0)

        self.assertEqual((await execute_with_retry(failing, 2, sleep)).error_message, "b")

    def test_extract_text(self):
        cases = (
            (Result.error("x"), []),
            (Result.ok("texto"), []),
            (Result.ok({"choices": "x"}), []),
            (chat_reply("a"), ["a"]),
            (chat_reply([{"type": "text", "text": "a"}, {"type": "image_url"}, {"type": "text", "text": "b"}]), ["ab"]),
            (Result.ok({"choices": [{"message": {"content": None}}, {"message": {"content": 3}}, "x"]}), ["3"]),
        )
        for result, expected in cases:
            with self.subTest(result=result):
                self.assertEqual(extract_text(result), expected)

    def test_conversation_context_counts_text_parts(self):
        messages = [ChatMessage.text("system", "abc").to_dict(), {"role": "user", "content": "de"},
                    {"role": "user", "content": ""}, {"content": "f"}]
        self.assertEqual(conversation_context(messages), {
            "message_count": 4, "roles": ["system", "user", "user"], "total_length": 6,
            "unique_roles": ["system", "user"],
        })


if __name__ == "__main__":
    unittest.main()
