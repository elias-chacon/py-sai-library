"""`/api/profile`: dados e preferências do usuário dono da chave."""
from __future__ import annotations

from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService
from sai_library.uri import path_segment


class ProfileService(BaseService):
    """Perfil do usuário dono da chave."""

    async def get_config(self) -> Result[Any]:
        return await self._get("/api/profile/config")

    async def get_language(self) -> Result[Any]:
        return await self._get("/api/profile/language")

    async def set_language(self, language: str) -> Result[Any]:
        return await self._put(f"/api/profile/language/{path_segment(language)}")

    async def get_name(self) -> Result[Any]:
        return await self._get("/api/profile/name")

    async def get_email(self) -> Result[Any]:
        return await self._get("/api/profile/email")

    async def is_developer(self) -> Result[Any]:
        return await self._get("/api/profile/developer")

    async def is_admin(self) -> Result[Any]:
        return await self._get("/api/profile/admin")
