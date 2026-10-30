"""`/api/templates`: templates do SAI e sua execução."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sai_library.models import TemplateExecuteOptions
from sai_library.result import Result
from sai_library.services.base import BaseService, compact
from sai_library.uri import Query, path_segment


class TemplateService(BaseService):
    """Templates do SAI."""

    async def get_templates(self, filters: Query | None = None) -> Result[Any]:
        return await self._get("/api/templates/list", filters)

    async def get_template(self, template_id: str) -> Result[Any]:
        return await self._get(f"/api/templates/{path_segment(template_id)}")

    async def get_template_view(self, template_id: str) -> Result[Any]:
        return await self._get(f"/api/templates/{path_segment(template_id)}/view")

    async def execute_template(
        self,
        template_id: str,
        inputs: Mapping[str, Any] | None = None,
        options: TemplateExecuteOptions | None = None,
    ) -> Result[Any]:
        """Executa com `inputs`; `options` vai parte na query, parte no corpo."""
        options = options or TemplateExecuteOptions()
        query = compact(workspaceId=options.workspace_id, seed=options.seed, modelOverride=options.model_override)
        data = {
            "inputs": dict(inputs or {}),
            **compact(
                chatMessages=list(options.chat_messages or ()),
                secrets=dict(options.secrets) if options.secrets else None,
            ),
        }
        return await self._post(f"/api/templates/{path_segment(template_id)}/execute", data, query)

    async def execute_chat_template(
        self, template_id: str, messages: Sequence[Mapping[str, Any]], workspace_id: str | None = None
    ) -> Result[Any]:
        return await self._post(
            f"/api/templates/{path_segment(template_id)}/chatexecute",
            {"messages": [dict(message) for message in messages]},
            compact(workspaceId=workspace_id),
        )

    async def get_subscribed_templates(self) -> Result[Any]:
        return await self._get("/api/templates/subscribed")

    async def get_owned_templates(self) -> Result[Any]:
        return await self._get("/api/templates/owned")

    async def subscribe_to_template(self, template_id: str) -> Result[Any]:
        return await self._put(f"/api/templates/subscribe/{path_segment(template_id)}")

    async def unsubscribe_from_template(self, template_id: str) -> Result[Any]:
        return await self._put(f"/api/templates/unsubscribe/{path_segment(template_id)}")
