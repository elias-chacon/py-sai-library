"""Fachada SAILibrary, builder, configuração e conexão (sem rede)."""
# pylint: disable=missing-class-docstring,missing-function-docstring
import unittest
from unittest.mock import patch

from sai_library.config import ConfigError, SaiSettings
from sai_library.http import HttpxClient, LoggingHttpClient, RetryHttpClient
from sai_library.library import SAILibrary
from sai_library.models import ModelType
from sai_library.result import Result
from tests.support import FakeHttp, chat_reply

MODELS = [{"name": "gpt", "type": 0}, {"name": "whisper", "type": 1}, {"name": "dalle", "type": 2},
          {"name": "gpt-mini", "type": 0}]


def no_env():
    """Ambiente vazio, sem ler os .env da máquina."""
    return patch.dict("os.environ", {}, clear=True)


class SettingsTest(unittest.TestCase):
    def test_explicit_values_win_and_trailing_slash_is_removed(self):
        with patch.dict("os.environ", {"SAI_API_KEY": "env", "SAI_API_BASE_URL": "https://env"}, clear=True):
            self.assertEqual(SaiSettings.resolve(env_files=()), SaiSettings("https://env", "env"))
            explicit = SaiSettings.resolve("explicita", "https://sai.test/", env_files=())
        self.assertEqual((explicit.base_url, explicit.api_key), ("https://sai.test", "explicita"))
        self.assertNotIn("explicita", repr(explicit))

    def test_missing_values_are_listed(self):
        with no_env(), self.assertRaisesRegex(ConfigError, "SAI_API_BASE_URL, SAI_API_KEY"):
            SaiSettings.resolve(env_files=())
        with no_env(), self.assertRaisesRegex(ConfigError, "SAI_API_KEY"):
            SaiSettings.resolve(base_url="https://x", api_key="   ", env_files=())


class ConnectTest(unittest.IsolatedAsyncioTestCase):
    def builder(self, http):
        return SAILibrary.builder().with_api_key("k").with_base_url("https://sai.test").with_env_files() \
            .with_http_client(http)

    async def test_connect_loads_models_and_closes_client(self):
        http = FakeHttp(Result.ok(MODELS, status=200))
        async with self.builder(http).connect() as sai:
            self.assertEqual(http.requests[0].url, "https://sai.test/api/models")
            self.assertEqual(http.requests[0].headers, {"X-Api-Key": "k"})
            self.assertEqual(sai.api_info(), {"selected_model": None, "available_models_count": 4,
                                              "chat_models_count": 2, "audio_models_count": 1,
                                              "image_models_count": 1})
            self.assertFalse(http.closed)
        self.assertTrue(http.closed)

    async def test_failed_model_load_still_connects(self):
        http = FakeHttp(Result.error("HTTP 500", status=500))
        with self.assertLogs("sai_library.library", "WARNING"):
            async with self.builder(http).connect() as sai:
                self.assertEqual(sai.models_of_type(ModelType.CHAT), [])

    async def test_static_connect_reads_environment(self):
        http = FakeHttp(Result.ok([], status=200))
        env = {"SAI_API_KEY": "env-key", "SAI_API_BASE_URL": "https://env.test"}
        with patch.dict("os.environ", env, clear=True), patch("sai_library.config.load_env"), \
                patch("sai_library.library.HttpxClient", return_value=http):
            async with SAILibrary.connect() as sai:
                await sai.test_connection()
        self.assertEqual([r.url for r in http.requests], ["https://env.test/api/models", "https://env.test/api/hc"])
        self.assertEqual(http.requests[0].headers, {"X-Api-Key": "env-key"})

    async def test_configuration_error_happens_before_any_request(self):
        http = FakeHttp()
        connection = SAILibrary.builder().with_env_files().with_http_client(http).connect()
        with no_env(), self.assertRaises(ConfigError):
            async with connection:
                pass
        self.assertEqual(http.requests, [])


class BuilderTest(unittest.IsolatedAsyncioTestCase):
    async def test_decorators_wrap_in_order(self):
        http = SAILibrary.builder().with_timeout(5).with_request_logging().with_retry(4).build_http_client()
        self.assertIsInstance(http, RetryHttpClient)
        self.assertEqual(http.max_attempts, 4)
        self.assertIsInstance(http.inner, LoggingHttpClient)
        self.assertIsInstance(http.inner.inner, HttpxClient)
        self.assertEqual(http.inner.inner.timeout_seconds, 5)
        await http.aclose()

    async def test_default_is_plain_httpx_client(self):
        http = SAILibrary.builder().build_http_client()
        self.assertIsInstance(http, HttpxClient)
        await http.aclose()


class ChatTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.http = FakeHttp(Result.ok(MODELS, status=200))
        self.sai = SAILibrary(SaiSettings("https://sai.test", "k"), self.http)
        await self.sai.refresh_models()

    def test_set_model_validates_against_loaded_models(self):
        with self.assertRaisesRegex(ValueError, "Disponíveis: gpt, whisper, dalle, gpt-mini"):
            self.sai.set_model("inexistente")
        self.sai.set_model("gpt-mini")
        self.assertEqual(self.sai.selected_model, "gpt-mini")

    async def test_set_model_without_models_explains(self):
        sai = SAILibrary(SaiSettings("https://sai.test", "k"), FakeHttp())
        with self.assertRaisesRegex(ValueError, "nenhum"):
            sai.set_model("gpt")

    async def test_send_message_requires_model(self):
        for call in (self.sai.send_message("oi"), self.sai.send_chat([])):
            result = await call
            self.assertIn("Nenhum modelo selecionado", result.error_message)
        self.assertEqual(len(self.http.requests), 1)

    async def test_send_message_builds_system_and_user_messages(self):
        self.sai.set_model("gpt")
        self.http.responses = [chat_reply("olá")]
        result = await self.sai.send_message("oi", system_prompt="Seja breve.")
        body = self.http.requests[-1].json_body
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(body["messages"][0]["content"], [{"type": "text", "text": "Seja breve."}])
        self.assertEqual(body["model"], "gpt")
        self.assertTrue(result.success)

    async def test_blank_system_prompt_is_omitted(self):
        self.sai.set_model("gpt")
        await self.sai.send_message("oi", system_prompt="  ")
        self.assertEqual([m["role"] for m in self.http.requests[-1].json_body["messages"]], ["user"])


if __name__ == "__main__":
    unittest.main()
