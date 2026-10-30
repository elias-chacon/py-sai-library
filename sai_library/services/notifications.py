"""`/api/notifications`: notificações do usuário."""
from __future__ import annotations

from typing import Any

from sai_library.result import Result
from sai_library.services.base import BaseService
from sai_library.uri import path_segment


class NotificationService(BaseService):
    """Notificações do usuário."""

    async def get_notifications(self) -> Result[Any]:
        return await self._get("/api/notifications")

    async def mark_notification_as_read(self, notification_id: str) -> Result[Any]:
        return await self._patch(f"/api/notifications/{path_segment(notification_id)}/read")

    async def mark_all_notifications_as_read(self) -> Result[Any]:
        return await self._patch("/api/notifications/mark-all-read")

    async def dismiss_notification(self, notification_id: str) -> Result[Any]:
        return await self._patch(f"/api/notifications/{path_segment(notification_id)}/dismiss")

    async def get_unread_count(self) -> Result[Any]:
        return await self._get("/api/notifications/count/unread")
