"""`/api/secrets`: segredos do usuário usados pelos templates."""
from __future__ import annotations

from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService
from sai_library.uri import path_segment


class UserSecretsService(BaseService):
    """Segredos do usuário."""

    async def get_secrets(self) -> Result[Any]:
        return await self._get("/api/secrets")

    async def create_secret(self, variable: str, secret: str) -> Result[Any]:
        return await self._post("/api/secrets", {"variable": variable, "secret": secret})

    async def update_secret(self, secret_id: str, variable: str, secret: str) -> Result[Any]:
        return await self._put(f"/api/secrets/{path_segment(secret_id)}", {"variable": variable, "secret": secret})

    async def delete_secret(self, secret_id: str) -> Result[Any]:
        return await self._delete(f"/api/secrets/{path_segment(secret_id)}")
