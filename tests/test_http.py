"""Transporte httpx (respostas simuladas por MockTransport) e decoradores de log e retry."""
# pylint: disable=missing-class-docstring,missing-function-docstring
import json
import unittest

import httpx

from sai_library.http import FileUpload, HttpxClient, LoggingHttpClient, RequestMethod, RetryHttpClient, is_transient
from sai_library.result import Result
from tests.support import FakeHttp

HEADERS = {"X-Api-Key": "segredo"}


class HttpxClientTest(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        http = HttpxClient(timeout_seconds=5, transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(http.aclose)
        return http

    async def test_success_parses_json_and_sends_headers_and_body(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(method=request.method, key=request.headers["X-Api-Key"], body=json.loads(request.content),
                        content_type=request.headers["Content-Type"])
            return httpx.Response(201, json={"id": 7})

        result = await self.client(handler).request(RequestMethod.POST, "https://sai/x", HEADERS, json_body={"a": 1})
        self.assertEqual((result.success, result.data, result.metadata), (True, {"id": 7}, {"status": 201}))
        expected = {"method": "POST", "key": "segredo", "body": {"a": 1}, "content_type": "application/json"}
        self.assertEqual(seen, expected)

    async def test_empty_and_non_json_bodies(self):
        for body, expected in (("", {}), ("  ", {}), ("texto puro", "texto puro"), ('"nome"', "nome")):
            with self.subTest(body=body):
                http = self.client(lambda _request, text=body: httpx.Response(200, text=text))
                self.assertEqual((await http.request(RequestMethod.GET, "https://sai/x", HEADERS)).data, expected)

    async def test_http_error_keeps_status_and_truncates_body(self):
        http = self.client(lambda _request: httpx.Response(404, text="x" * 5000))
        result = await http.request(RequestMethod.GET, "https://sai/x", HEADERS)
        self.assertFalse(result.success)
        self.assertEqual(result.metadata, {"status": 404})
        self.assertTrue(result.error_message.startswith("HTTP 404: xxx"))
        self.assertLess(len(result.error_message), 1100)

    async def test_timeout_and_network_errors_become_results(self):
        for error, message in ((httpx.ReadTimeout("lento"), "tempo limite de 5s"),
                               (httpx.ConnectError("recusada"), "Falha na requisição HTTP: recusada")):
            with self.subTest(error=type(error).__name__):
                def handler(_request, exc=error):
                    raise exc
                result = await self.client(handler).request(RequestMethod.GET, "https://sai/x", HEADERS)
                self.assertEqual((result.success, result.metadata), (False, {}))
                self.assertIn(message, result.error_message)

    async def test_file_is_sent_as_multipart_field(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(content_type=request.headers["Content-Type"], body=request.read())
            return httpx.Response(200, json={})

        upload = FileUpload("nota.txt", b"conteudo")
        await self.client(handler).request(RequestMethod.POST, "https://sai/up", HEADERS, file=upload)
        self.assertTrue(seen["content_type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="file"; filename="nota.txt"', seen["body"])
        self.assertIn(b"conteudo", seen["body"])


class RetryHttpClientTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.delays = []

    async def sleep(self, seconds):
        self.delays.append(seconds)

    async def test_retries_transient_failures_with_exponential_delay(self):
        inner = FakeHttp(Result.error("rede"), Result.error("HTTP 503", status=503), Result.ok({"ok": True}))
        result = await RetryHttpClient(inner, 3, self.sleep).request(RequestMethod.GET, "u", HEADERS)
        self.assertTrue(result.success)
        self.assertEqual((len(inner.requests), self.delays), (3, [2.0, 4.0]))

    async def test_stops_at_max_attempts(self):
        inner = FakeHttp(default=Result.error("HTTP 500", status=500))
        result = await RetryHttpClient(inner, 2, self.sleep).request(RequestMethod.GET, "u", HEADERS)
        self.assertEqual((result.error_message, len(inner.requests)), ("HTTP 500", 2))

    async def test_client_errors_are_not_retried(self):
        inner = FakeHttp(default=Result.error("HTTP 400", status=400))
        await RetryHttpClient(inner, 5, self.sleep).request(RequestMethod.GET, "u", HEADERS)
        self.assertEqual((len(inner.requests), self.delays), (1, []))

    async def test_close_is_delegated(self):
        inner = FakeHttp()
        await RetryHttpClient(LoggingHttpClient(inner)).aclose()
        self.assertTrue(inner.closed)

    def test_transient_classification(self):
        cases = {None: True, 500: True, 503: True, 429: True, 400: False, 401: False, 404: False}
        for status, expected in cases.items():
            with self.subTest(status=status):
                metadata = {} if status is None else {"status": status}
                self.assertIs(is_transient(Result.error("x", **metadata)), expected)


class LoggingHttpClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_logs_outcome_without_headers(self):
        inner = FakeHttp(Result.ok({}), Result.error("HTTP 500: falhou", status=500))
        http = LoggingHttpClient(inner)
        with self.assertLogs("sai_library.http", "INFO") as logs:
            await http.request(RequestMethod.GET, "https://sai/a", HEADERS)
            await http.request(RequestMethod.POST, "https://sai/b", HEADERS, json_body={"x": 1})
        self.assertIn("GET https://sai/a", logs.output[0])
        self.assertIn("(ok)", logs.output[0])
        self.assertIn("erro: HTTP 500: falhou", logs.output[1])
        self.assertNotIn("segredo", "".join(logs.output))
        self.assertEqual(inner.requests[1].json_body, {"x": 1})


if __name__ == "__main__":
    unittest.main()
