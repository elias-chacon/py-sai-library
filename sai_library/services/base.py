"""Base dos serviços: monta a URL e delega ao `HttpClient` com os cabeçalhos de autenticação."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sai_library.http import FileUpload, HttpClient, RequestMethod
from sai_library.result import Result
from sai_library.uri import Query, build_uri


class BaseService:
    """Serviço da API: monta URLs e envia com os cabeçalhos de autenticação."""

    def __init__(self, http: HttpClient, base_url: str, headers: Mapping[str, str]) -> None:
        if not base_url:
            raise ValueError("base_url é obrigatório")
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._headers = dict(headers)

    async def _get(self, endpoint: str, query: Query | None = None) -> Result[Any]:
        return await self._send(RequestMethod.GET, endpoint, query=query)

    async def _post(self, endpoint: str, data: Any = None, query: Query | None = None) -> Result[Any]:
        return await self._send(RequestMethod.POST, endpoint, data, query)

    async def _put(self, endpoint: str, data: Any = None) -> Result[Any]:
        return await self._send(RequestMethod.PUT, endpoint, data)

    async def _patch(self, endpoint: str) -> Result[Any]:
        return await self._send(RequestMethod.PATCH, endpoint)

    async def _delete(self, endpoint: str) -> Result[Any]:
        return await self._send(RequestMethod.DELETE, endpoint)

    async def _send(
        self,
        method: RequestMethod,
        endpoint: str,
        data: Any = None,
        query: Query | None = None,
        file: FileUpload | None = None,
    ) -> Result[Any]:
        url = build_uri(self._base_url, endpoint, query)
        return await self._http.request(method, url, self._headers, json_body=data, file=file)


def compact(**values: Any) -> dict[str, Any]:
    """Só os parâmetros informados: `None`, texto vazio e lista vazia ficam fora (como os `if (x)` do original).

    Zero e `False` são mantidos: `seed=0` é um valor válido.
    """
    return {key: value for key, value in values.items() if not _is_blank(value)}


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, tuple)) and len(value) == 0)
