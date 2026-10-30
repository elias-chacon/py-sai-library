"""Montagem de URLs da API: segmentos de caminho e query string codificados como `encodeURIComponent`."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

Query = Mapping[str, Any]


def path_segment(value: object) -> str:
    """Codifica um id para uso no caminho; impede que `/`, `?` ou `#` alterem a rota."""
    return quote(str(value), safe="")


def build_uri(base_url: str, endpoint: str, query: Query | None = None) -> str:
    """Valores `None` são omitidos; listas repetem a chave; booleanos viram `true`/`false`."""
    uri = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    pairs = [pair for key, value in (query or {}).items() for pair in _query_pairs(key, value)]
    return f"{uri}?{'&'.join(pairs)}" if pairs else uri


def _query_pairs(key: str, value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    return [f"{quote(key, safe='')}={quote(_text(item), safe='')}" for item in values]


def _text(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)
