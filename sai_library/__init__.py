"""Cliente Python assíncrono para a API do SAI, com tools acionadas pelo modelo.

Uso:
    async with SAILibrary.connect() as sai:
        sai.set_model("nome-do-modelo")
        result = await sai.send_message("Olá")
"""
from sai_library.config import ConfigError, SaiSettings
from sai_library.extensions import conversation_context, execute_with_retry, extract_text
from sai_library.http import (
    FileUpload, HttpClient, HttpxClient, LoggingHttpClient, RequestMethod, RetryHttpClient,
)
from sai_library.library import SAILibrary, SAILibraryBuilder
from sai_library.models import ChatMessage, ChatOptions, ModelType, TemplateExecuteOptions
from sai_library.result import Result
from sai_library.tool_chat import ToolConversation, ToolMode
from sai_library.tools import NativeToolFormat, Tool, ToolCallRecord, ToolRegistry

__all__ = [
    "ChatMessage", "ChatOptions", "ConfigError", "FileUpload", "HttpClient", "HttpxClient", "LoggingHttpClient",
    "ModelType", "NativeToolFormat", "RequestMethod", "Result", "RetryHttpClient", "SAILibrary", "SAILibraryBuilder",
    "SaiSettings", "TemplateExecuteOptions", "Tool", "ToolCallRecord", "ToolConversation", "ToolMode", "ToolRegistry",
    "conversation_context", "execute_with_retry", "extract_text",
]
