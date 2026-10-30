"""`/api/hc`: verificação de disponibilidade da API."""
from __future__ import annotations

from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService


class HealthService(BaseService):
    async def check_health(self) -> Result[Any]:
        return await self._get("/api/hc")
