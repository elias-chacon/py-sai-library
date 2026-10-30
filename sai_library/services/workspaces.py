"""`/api/workspaces`: workspaces e seus templates."""
from __future__ import annotations

from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService
from sai_library.uri import path_segment


class WorkspaceService(BaseService):
    """Workspaces e seus templates."""

    async def get_workspaces(self, result_size: int, page: int) -> Result[Any]:
        return await self._get("/api/workspaces", {"ResultSize": result_size, "Page": page})

    async def get_workspace(self, workspace_id: str) -> Result[Any]:
        return await self._get(f"/api/workspaces/{path_segment(workspace_id)}")

    async def add_template_to_workspace(self, workspace_id: str, template_id: str) -> Result[Any]:
        return await self._post(_template_path(workspace_id, template_id))

    async def remove_template_from_workspace(self, workspace_id: str, template_id: str) -> Result[Any]:
        return await self._delete(_template_path(workspace_id, template_id))


def _template_path(workspace_id: str, template_id: str) -> str:
    return f"/api/workspaces/{path_segment(workspace_id)}/templates/{path_segment(template_id)}"
