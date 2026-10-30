"""Um serviço por grupo de endpoints da API do SAI, como no ts-sai-library."""
from sai_library.services.categories import CategoryService
from sai_library.services.chat import ChatService
from sai_library.services.conversations import ConversationService
from sai_library.services.files import FileService
from sai_library.services.health import HealthService
from sai_library.services.models import ModelService
from sai_library.services.notifications import NotificationService
from sai_library.services.profile import ProfileService
from sai_library.services.templates import TemplateService
from sai_library.services.tool_history import ToolHistoryService
from sai_library.services.user_secrets import UserSecretsService
from sai_library.services.workspaces import WorkspaceService

__all__ = [
    "CategoryService", "ChatService", "ConversationService", "FileService", "HealthService", "ModelService",
    "NotificationService", "ProfileService", "TemplateService", "ToolHistoryService", "UserSecretsService",
    "WorkspaceService",
]
