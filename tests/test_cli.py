"""Linha de comando com a conexão simulada."""
# pylint: disable=missing-class-docstring,missing-function-docstring
import contextlib
import io
import unittest
from unittest.mock import patch

from sai_library import cli
from sai_library.config import ConfigError, SaiSettings
from sai_library.library import SAILibrary
from sai_library.result import Result
from tests.support import FakeHttp, chat_reply

MODELS = [{"name": "gpt", "type": 0}, {"name": "whisper", "type": 1}]


class CliTest(unittest.TestCase):
    def run_cli(self, argv, *responses):
        http = FakeHttp(Result.ok(MODELS, status=200), *responses)

        @contextlib.asynccontextmanager
        async def connect():
            sai = SAILibrary(SaiSettings("https://sai.test", "k"), http)
            await sai.refresh_models()
            yield sai

        out, err = io.StringIO(), io.StringIO()
        with patch.object(cli.SAILibrary, "connect", connect), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue(), http

    def test_health(self):
        code, out, _, http = self.run_cli(["health"], Result.ok({"status": "Healthy"}))
        self.assertEqual((code, http.requests[1].url), (0, "https://sai.test/api/hc"))
        self.assertIn('"status": "Healthy"', out)

    def test_api_error_goes_to_stderr(self):
        code, out, err, _ = self.run_cli(["health"], Result.error("HTTP 401: chave inválida", status=401))
        self.assertEqual((code, out, err.strip()), (1, "", "HTTP 401: chave inválida"))

    def test_models_all_and_filtered(self):
        _, out_all, _, _ = self.run_cli(["models"], Result.ok(MODELS))
        self.assertIn("whisper", out_all)
        _, out_chat, _, http = self.run_cli(["models", "--type", "chat"])
        self.assertIn('"gpt"', out_chat)
        self.assertNotIn("whisper", out_chat)
        self.assertEqual(len(http.requests), 1, "filtrar usa os modelos já carregados")

    def test_chat(self):
        code, out, _, http = self.run_cli(["chat", "oi", "--model", "gpt", "--system", "breve"], chat_reply("olá"))
        self.assertEqual((code, out.strip()), (0, "olá"))
        self.assertEqual([m["role"] for m in http.requests[1].json_body["messages"]], ["system", "user"])

    def test_chat_unknown_model(self):
        code, _, err, http = self.run_cli(["chat", "oi", "--model", "nao-existe"])
        self.assertEqual(code, 1)
        self.assertIn("Modelo 'nao-existe' não encontrado", err)
        self.assertEqual(len(http.requests), 1)

    def test_configuration_error(self):
        err = io.StringIO()
        with patch.object(cli, "_run", side_effect=ConfigError("Configuração ausente: SAI_API_KEY")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["health"]), 1)
        self.assertIn("SAI_API_KEY", err.getvalue())


if __name__ == "__main__":
    unittest.main()
