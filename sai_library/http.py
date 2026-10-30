"""Transporte HTTP assíncrono: cliente httpx e decoradores de log e de retry."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import httpx

from sai_library.result import Result

LOG = logging.getLogger(__name__)
_ERROR_BODY_LIMIT = 1000


class RequestMethod(StrEnum):
    """Métodos HTTP usados pela API."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


@dataclass(frozen=True)
class FileUpload:
    """Arquivo enviado como campo `file` de um formulário multipart."""

    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


class HttpClient(Protocol):
    """Transporte usado pelos serviços; `HttpxClient` é a implementação padrão."""

    async def request(
        self,
        method: RequestMethod,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: Any = None,
        file: FileUpload | None = None,
    ) -> Result[Any]:
        """Executa a requisição; falhas viram `Result.error` com `status` quando houver resposta."""

    async def aclose(self) -> None: ...


class HttpxClient:
    """Implementação com `httpx.AsyncClient`. `transport` permite simular respostas nos testes."""

    def __init__(self, timeout_seconds: float = 30.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def request(
        self,
        method: RequestMethod,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: Any = None,
        file: FileUpload | None = None,
    ) -> Result[Any]:
        """Falhas de rede e timeout viram `Result.error` sem `status`."""
        files = {"file": (file.filename, file.content, file.content_type)} if file else None
        try:
            response = await self._client.request(method, url, headers=dict(headers), json=json_body, files=files)
        except httpx.TimeoutException:
            return Result.error(f"Requisição excedeu o tempo limite de {self.timeout_seconds}s")
        except httpx.HTTPError as exc:
            return Result.error(f"Falha na requisição HTTP: {exc}")
        if response.is_success:
            return Result.ok(_parse_body(response.text), status=response.status_code)
        return Result.error(
            f"HTTP {response.status_code}: {response.text[:_ERROR_BODY_LIMIT]}", status=response.status_code
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _parse_body(text: str) -> Any:
    """JSON quando possível; corpo vazio vira `{}`; texto não JSON é devolvido como está."""
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


class _HttpClientDecorator:
    def __init__(self, inner: HttpClient) -> None:
        self.inner = inner

    async def aclose(self) -> None:
        await self.inner.aclose()


class LoggingHttpClient(_HttpClientDecorator):
    """Registra método, URL, duração e resultado. Nunca registra cabeçalhos (a chave de API está neles)."""

    async def request(
        self,
        method: RequestMethod,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: Any = None,
        file: FileUpload | None = None,
    ) -> Result[Any]:
        """Repassa ao cliente interno e registra o resultado."""
        started = time.perf_counter()
        result = await self.inner.request(method, url, headers, json_body=json_body, file=file)
        elapsed_ms = (time.perf_counter() - started) * 1000
        outcome = "ok" if result.success else f"erro: {result.error_message}"
        LOG.info("%s %s em %.0f ms (%s)", method, url, elapsed_ms, outcome)
        return result


class RetryHttpClient(_HttpClientDecorator):
    """Repete falhas transitórias (rede, timeout, HTTP 5xx e 429) com espera exponencial de 2ⁿ segundos."""

    def __init__(
        self,
        inner: HttpClient,
        max_attempts: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(inner)
        self.max_attempts = max(1, max_attempts)
        self._sleep = sleep

    async def request(
        self,
        method: RequestMethod,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: Any = None,
        file: FileUpload | None = None,
    ) -> Result[Any]:
        """Repete enquanto a falha for transitória e houver tentativas."""
        attempt = 1
        while True:
            result = await self.inner.request(method, url, headers, json_body=json_body, file=file)
            if result.success or not is_transient(result) or attempt >= self.max_attempts:
                return result
            delay = 2.0**attempt
            LOG.info("Tentativa %d/%d falhou (%s); nova tentativa em %.0fs",
                     attempt, self.max_attempts, result.error_message, delay)
            await self._sleep(delay)
            attempt += 1


def is_transient(result: Result[Any]) -> bool:
    """Sem `status` (rede/timeout), 5xx ou 429. Erros 4xx de requisição se repetiriam igual."""
    status = result.metadata.get("status")
    return status is None or status >= 500 or status == 429
