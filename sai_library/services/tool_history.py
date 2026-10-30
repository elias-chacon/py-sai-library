"""`/api/tool-history`: histórico de execuções de templates do SAI (não são as tools desta lib)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService, compact
from sai_library.uri import path_segment


class ToolHistoryService(BaseService):
    """Histórico de execuções de templates."""

    async def get_tool_history(
        self,
        template_id: str | None = None,
        template_ids: Sequence[str] | None = None,
        workspace_id: str | None = None,
    ) -> Result[Any]:
        """Filtros opcionais; `template_ids` repete a chave na query."""
        query = compact(templateId=template_id, templateIds=list(template_ids or ()), workspaceId=workspace_id)
        return await self._get("/api/tool-history", query)

    async def create_tool_history(
        self,
        template_id: str,
        inputs: Mapping[str, Any] | None = None,
        chat_messages: Sequence[Mapping[str, Any]] | None = None,
        workspace_id: str | None = None,
    ) -> Result[Any]:
        """Registra uma execução de template no histórico."""
        data = {
            "templateId": template_id,
            "inputs": dict(inputs or {}),
            "chatMessages": [dict(message) for message in chat_messages or ()],
            **compact(workspaceId=workspace_id),
        }
        return await self._post("/api/tool-history", data)

    async def get_tool_history_item(self, item_id: str, workspace_id: str | None = None) -> Result[Any]:
        return await self._get(f"/api/tool-history/{path_segment(item_id)}", compact(workspaceId=workspace_id))

    async def delete_tool_history_item(self, item_id: str) -> Result[Any]:
        return await self._delete(f"/api/tool-history/{path_segment(item_id)}")

    async def search_tool_history(self, query: str, workspace_id: str, result_size: int) -> Result[Any]:
        # Grafia das chaves igual à do original: "query" minúsculo, as demais em PascalCase.
        params = {"query": query, "WorkspaceId": workspace_id, "ResultSize": result_size}
        return await self._get("/api/tool-history/search", params)

    async def restore_tool_history(self, item_id: str, workspace_id: str | None = None) -> Result[Any]:
        return await self._post(f"/api/tool-history/{path_segment(item_id)}/restore", compact(workspaceId=workspace_id))
