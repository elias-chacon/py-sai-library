"""`/api/storage` e `/api/provider-files`: upload e download de arquivos."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sai_library.http import FileUpload, RequestMethod
from sai_library.result import Result
from sai_library.services.base import BaseService, compact


class FileService(BaseService):
    """Upload e download de arquivos."""

    async def get_upload_token(
        self, container_name: str | None = None, filename: str | None = None, folder: str | None = None
    ) -> Result[Any]:
        query = {"folder": folder or "useruploads", **compact(containerName=container_name, filename=filename)}
        return await self._get("/api/storage/uploadtoken", query)

    async def upload_file(self, file_path: str | Path, model: str | None = None) -> Result[Any]:
        """Envia como multipart pelo mesmo `HttpClient` dos demais serviços (com log e retry, se ativos)."""
        path = Path(file_path)
        if not path.is_file():
            return Result.error(f"Arquivo não encontrado: {path}")
        upload = FileUpload(path.name, await asyncio.to_thread(path.read_bytes))
        endpoint = "/api/provider-files/upload"
        return await self._send(RequestMethod.POST, endpoint, query=compact(model=model), file=upload)

    async def download_file(self, model: str | None = None, file_id: str | None = None) -> Result[Any]:
        return await self._get("/api/provider-files/download", compact(model=model, fileId=file_id))
