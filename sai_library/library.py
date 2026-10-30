"""Fachada `SAILibrary`: serviços da API, modelo selecionado e conversa com tools."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sai_library.config import DEFAULT_ENV_FILES, SaiSettings
from sai_library.http import HttpClient, HttpxClient, LoggingHttpClient, RetryHttpClient
from sai_library.models import ChatMessage, ChatOptions, Json, ModelType
from sai_library.result import Result
from sai_library.services import (
    CategoryService, ChatService, ConversationService, FileService, HealthService, ModelService, NotificationService,
    ProfileService, TemplateService, ToolHistoryService, UserSecretsService, WorkspaceService,
)
from sai_library.tool_chat import DEFAULT_MAX_ROUNDS, ToolConversation, ToolMode, run_tool_chat
from sai_library.tools import NativeToolFormat, ToolRegistry

LOG = logging.getLogger(__name__)
_NO_MODEL = "Nenhum modelo selecionado. Use set_model() antes de conversar."
# Provedores em que o ciclo nativo (tools → tool_calls → role "tool") foi verificado pelo SAI, e o formato de
# `tools` que cada um aceita (2026-10-30). Gemini aceita o campo, mas o SAI descarta a chamada: fica no prompt.
NATIVE_TOOL_FORMATS: Mapping[str, NativeToolFormat] = MappingProxyType({
    "OPENAI": NativeToolFormat.RESPONSES,
    "EMEA": NativeToolFormat.CHAT_COMPLETIONS,
})


class SAILibrary:  # pylint: disable=too-many-instance-attributes  # um atributo por serviço da API, como no original
    """Abra com `async with SAILibrary.connect() as sai:` (ou pelo `builder()`), que fecha o cliente HTTP ao sair."""

    def __init__(self, settings: SaiSettings, http: HttpClient) -> None:
        args = (http, settings.base_url, {"X-Api-Key": settings.api_key})
        self.health = HealthService(*args)
        self.profile = ProfileService(*args)
        self.models = ModelService(*args)
        self.chat = ChatService(*args)
        self.templates = TemplateService(*args)
        self.conversations = ConversationService(*args)
        self.workspaces = WorkspaceService(*args)
        self.tool_history = ToolHistoryService(*args)
        self.categories = CategoryService(*args)
        self.files = FileService(*args)
        self.user_secrets = UserSecretsService(*args)
        self.notifications = NotificationService(*args)
        self._http = http
        self._available_models: list[Mapping[str, Any]] = []
        self._selected_model: str | None = None

    @staticmethod
    def builder() -> SAILibraryBuilder:
        return SAILibraryBuilder()

    @staticmethod
    def connect(api_key: str | None = None, base_url: str | None = None) -> AbstractAsyncContextManager[SAILibrary]:
        """Atalho para `builder()` com os padrões; valores ausentes vêm de SAI_API_KEY e SAI_API_BASE_URL."""
        return SAILibraryBuilder().with_api_key(api_key).with_base_url(base_url).connect()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def test_connection(self) -> Result[Any]:
        return await self.health.check_health()

    async def refresh_models(self) -> Result[Any]:
        """Recarrega os modelos disponíveis. Em falha, a lista fica vazia e o erro é devolvido."""
        result = await self.models.get_models()
        self._available_models = list(result.data) if result.success and isinstance(result.data, list) else []
        if result.success:
            LOG.info("%d modelos carregados", len(self._available_models))
        else:
            LOG.warning("Falha ao carregar modelos: %s", result.error_message)
        return result

    @property
    def selected_model(self) -> str | None:
        return self._selected_model

    def set_model(self, model_name: str) -> None:
        """ValueError se o modelo não estiver entre os carregados (a mensagem lista os disponíveis)."""
        names = [model.get("name") for model in self._available_models]
        if model_name not in names:
            available = ", ".join(str(name) for name in names) or "nenhum (veja refresh_models())"
            raise ValueError(f"Modelo '{model_name}' não encontrado. Disponíveis: {available}")
        self._selected_model = model_name
        LOG.info("Modelo selecionado: %s", model_name)

    def models_of_type(self, model_type: ModelType) -> list[Mapping[str, Any]]:
        return ModelService.filter_models_by_type(self._available_models, model_type)

    async def send_message(
        self, message: str, system_prompt: str | None = None, options: ChatOptions | None = None
    ) -> Result[Any]:
        """Mensagem única ao modelo selecionado, com prompt de sistema opcional."""
        messages = [ChatMessage.text("user", message).to_dict()]
        if system_prompt and system_prompt.strip():
            messages.insert(0, ChatMessage.text("system", system_prompt).to_dict())
        return await self.send_chat(messages, options)

    async def send_chat(self, messages: Sequence[Json], options: ChatOptions | None = None) -> Result[Any]:
        """Envia um histórico completo de mensagens ao modelo selecionado."""
        if not self._selected_model:
            return Result.error(_NO_MODEL)
        return await self.chat.send_completion(messages, self._selected_model, options)

    async def chat_with_tools(  # pylint: disable=too-many-arguments  # opcionais só por nome (após *)
        self,
        message: str,
        tools: ToolRegistry,
        *,
        system_prompt: str | None = None,
        options: ChatOptions | None = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        mode: ToolMode = ToolMode.PROMPT,
    ) -> Result[ToolConversation]:
        """Conversa em que o modelo pode acionar as tools de `tools`. Ver `sai_library.tool_chat`.

        `mode`: PROMPT (padrão, qualquer modelo), NATIVE (function calling da API) ou AUTO (`tool_mode_for`).
        """
        if not self._selected_model:
            return Result.error(_NO_MODEL)
        model = self._selected_model

        async def complete(messages: Sequence[Json], native_tools: Sequence[Json] | None) -> Result[Any]:
            return await self.chat.send_completion(messages, model, options, tools=native_tools)

        resolved = self.tool_mode_for(model) if mode is ToolMode.AUTO else mode
        return await run_tool_chat(
            complete, tools, message, system_prompt=system_prompt, max_rounds=max_rounds, mode=resolved,
            native_format=self.native_tool_format_for(model),
        )

    def tool_mode_for(self, model_name: str) -> ToolMode:
        """NATIVE para modelos de provedor verificado com function calling nativo pelo SAI; senão PROMPT."""
        return ToolMode.NATIVE if self._provider(model_name) in NATIVE_TOOL_FORMATS else ToolMode.PROMPT

    def native_tool_format_for(self, model_name: str) -> NativeToolFormat:
        """Formato de `tools` do provedor do modelo; para provedor não verificado, o de chat completions."""
        return NATIVE_TOOL_FORMATS.get(self._provider(model_name), NativeToolFormat.CHAT_COMPLETIONS)

    def _provider(self, model_name: str) -> str:
        model = next((m for m in self._available_models if m.get("name") == model_name), {})
        return str(model.get("provider", "")).upper()

    def api_info(self) -> dict[str, Any]:
        return {
            "selected_model": self._selected_model,
            "available_models_count": len(self._available_models),
            **{f"{kind.name.lower()}_models_count": len(self.models_of_type(kind)) for kind in ModelType},
        }


class SAILibraryBuilder:
    """Configuração do transporte: timeout, retry de falhas transitórias, log e cliente HTTP próprio."""

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._base_url: str | None = None
        self._env_files: tuple[Path, ...] = DEFAULT_ENV_FILES
        self._timeout_seconds = 30.0
        self._max_attempts = 1
        self._logging = False
        self._http: HttpClient | None = None

    def with_api_key(self, api_key: str | None) -> SAILibraryBuilder:
        self._api_key = api_key
        return self

    def with_base_url(self, base_url: str | None) -> SAILibraryBuilder:
        self._base_url = base_url
        return self

    def with_env_files(self, *env_files: Path) -> SAILibraryBuilder:
        self._env_files = env_files
        return self

    def with_timeout(self, seconds: float) -> SAILibraryBuilder:
        self._timeout_seconds = seconds
        return self

    def with_retry(self, max_attempts: int = 3) -> SAILibraryBuilder:
        self._max_attempts = max_attempts
        return self

    def with_request_logging(self) -> SAILibraryBuilder:
        self._logging = True
        return self

    def with_http_client(self, http: HttpClient) -> SAILibraryBuilder:
        """Cliente base próprio (ex.: testes); log e retry continuam sendo aplicados por cima dele."""
        self._http = http
        return self

    def build_http_client(self) -> HttpClient:
        """Cliente base, envolvido por log e depois por retry, quando ativados."""
        http: HttpClient = self._http or HttpxClient(self._timeout_seconds)
        if self._logging:
            http = LoggingHttpClient(http)
        if self._max_attempts > 1:
            http = RetryHttpClient(http, self._max_attempts)
        return http

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[SAILibrary]:
        """Valida a configuração, carrega os modelos e fecha o cliente HTTP ao sair do bloco."""
        settings = SaiSettings.resolve(self._api_key, self._base_url, self._env_files)
        library = SAILibrary(settings, self.build_http_client())
        try:
            await library.refresh_models()
            yield library
        finally:
            await library.aclose()
