"""`/api/conversations`: conversas salvas."""
from __future__ import annotations

from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService, compact
from sai_library.uri import path_segment


class ConversationService(BaseService):
    """Conversas salvas."""

    async def create_conversation(
        self, title: str, template_id: str | None = None, workspace_id: str | None = None
    ) -> Result[Any]:
        data = {"title": title, **compact(templateId=template_id, workspaceId=workspace_id)}
        return await self._post("/api/conversations", data)

    async def get_conversations(self, template_id: str | None = None, workspace_id: str | None = None) -> Result[Any]:
        return await self._get("/api/conversations", compact(templateId=template_id, workspaceId=workspace_id))

    async def get_conversation(self, conversation_id: str, workspace_id: str | None = None) -> Result[Any]:
        return await self._get(f"/api/conversations/{path_segment(conversation_id)}", compact(workspaceId=workspace_id))

    async def delete_conversation(self, conversation_id: str) -> Result[Any]:
        return await self._delete(f"/api/conversations/{path_segment(conversation_id)}")

    async def update_conversation_title(self, conversation_id: str, title: str) -> Result[Any]:
        return await self._put(f"/api/conversations/{path_segment(conversation_id)}/title", {"title": title})
