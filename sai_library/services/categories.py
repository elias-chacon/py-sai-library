"""`/api/category`: categorias de templates."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService, compact
from sai_library.uri import path_segment


class CategoryService(BaseService):
    """Categorias de templates."""

    async def get_categories(
        self,
        types: Sequence[int] | None = None,
        parent_category_key_name: str | None = None,
        name: str | None = None,
    ) -> Result[Any]:
        """Filtros opcionais; `types` repete a chave na query."""
        query = compact(types=list(types or ()), parentCategoryKeyName=parent_category_key_name, name=name)
        return await self._get("/api/category", query)

    async def get_category_types(self) -> Result[Any]:
        return await self._get("/api/category/types")

    async def get_category(self, category_id: str) -> Result[Any]:
        return await self._get(f"/api/category/{path_segment(category_id)}")
