"""Cada método dos 12 serviços: método HTTP, rota, query e corpo, comparados com o ts-sai-library."""
# pylint: disable=missing-class-docstring,missing-function-docstring
import contextlib
import tempfile
import unittest
from pathlib import Path

from sai_library.config import SaiSettings
from sai_library.library import SAILibrary
from sai_library.models import ChatOptions, ModelType, TemplateExecuteOptions
from sai_library.services.base import BaseService, compact
from sai_library.services.models import ModelService
from tests.support import FakeHttp

BASE = "https://sai.test"
MESSAGE = {"role": "user", "content": [{"type": "text", "text": "oi"}]}
NO_BODY = None

# (serviço, método, args, kwargs, método HTTP, rota + query, corpo JSON)
CASES = [
    ("health", "check_health", (), {}, "GET", "/api/hc", NO_BODY),
    ("profile", "get_config", (), {}, "GET", "/api/profile/config", NO_BODY),
    ("profile", "get_language", (), {}, "GET", "/api/profile/language", NO_BODY),
    ("profile", "set_language", ("pt BR",), {}, "PUT", "/api/profile/language/pt%20BR", NO_BODY),
    ("profile", "get_name", (), {}, "GET", "/api/profile/name", NO_BODY),
    ("profile", "get_email", (), {}, "GET", "/api/profile/email", NO_BODY),
    ("profile", "is_developer", (), {}, "GET", "/api/profile/developer", NO_BODY),
    ("profile", "is_admin", (), {}, "GET", "/api/profile/admin", NO_BODY),
    ("models", "get_models", (), {}, "GET", "/api/models", NO_BODY),
    ("models", "get_realtime_models", (), {}, "GET", "/api/models/realtime", NO_BODY),
    ("chat", "send_completion", ([MESSAGE], "gpt"), {}, "POST", "/api/prompt/v1/chat/completions",
     {"messages": [MESSAGE], "model": "gpt", "temperature": 0.7, "max_tokens": 1000}),
    ("chat", "send_completion", ([MESSAGE], "gpt", ChatOptions(0.2, 50, seed=0)), {}, "POST",
     "/api/prompt/v1/chat/completions",
     {"messages": [MESSAGE], "model": "gpt", "temperature": 0.2, "max_tokens": 50, "seed": 0}),
    ("chat", "send_completion", ([MESSAGE], "gpt"), {"tools": [{"type": "function", "name": "f"}]}, "POST",
     "/api/prompt/v1/chat/completions",
     {"messages": [MESSAGE], "model": "gpt", "temperature": 0.7, "max_tokens": 1000,
      "tools": [{"type": "function", "name": "f"}]}),
    ("templates", "get_templates", ({"page": 1, "active": True},), {}, "GET", "/api/templates/list?page=1&active=true",
     NO_BODY),
    ("templates", "get_template", ("a/b",), {}, "GET", "/api/templates/a%2Fb", NO_BODY),
    ("templates", "get_template_view", ("t1",), {}, "GET", "/api/templates/t1/view", NO_BODY),
    ("templates", "execute_template", ("t1",), {}, "POST", "/api/templates/t1/execute", {"inputs": {}}),
    ("templates", "execute_template",
     ("t1", {"x": 1}, TemplateExecuteOptions("w", 0, "m", [MESSAGE], {"k": "v"})), {}, "POST",
     "/api/templates/t1/execute?workspaceId=w&seed=0&modelOverride=m",
     {"inputs": {"x": 1}, "chatMessages": [MESSAGE], "secrets": {"k": "v"}}),
    ("templates", "execute_chat_template", ("t1", [MESSAGE], "w"), {}, "POST",
     "/api/templates/t1/chatexecute?workspaceId=w", {"messages": [MESSAGE]}),
    ("templates", "get_subscribed_templates", (), {}, "GET", "/api/templates/subscribed", NO_BODY),
    ("templates", "get_owned_templates", (), {}, "GET", "/api/templates/owned", NO_BODY),
    ("templates", "subscribe_to_template", ("t1",), {}, "PUT", "/api/templates/subscribe/t1", NO_BODY),
    ("templates", "unsubscribe_from_template", ("t1",), {}, "PUT", "/api/templates/unsubscribe/t1", NO_BODY),
    ("conversations", "create_conversation", ("T",), {"template_id": "t", "workspace_id": ""}, "POST",
     "/api/conversations", {"title": "T", "templateId": "t"}),
    ("conversations", "get_conversations", (), {"workspace_id": "w"}, "GET", "/api/conversations?workspaceId=w",
     NO_BODY),
    ("conversations", "get_conversation", ("c1", "w"), {}, "GET", "/api/conversations/c1?workspaceId=w", NO_BODY),
    ("conversations", "delete_conversation", ("c1",), {}, "DELETE", "/api/conversations/c1", NO_BODY),
    ("conversations", "update_conversation_title", ("c1", "Novo"), {}, "PUT", "/api/conversations/c1/title",
     {"title": "Novo"}),
    ("workspaces", "get_workspaces", (10, 2), {}, "GET", "/api/workspaces?ResultSize=10&Page=2", NO_BODY),
    ("workspaces", "get_workspace", ("w1",), {}, "GET", "/api/workspaces/w1", NO_BODY),
    ("workspaces", "add_template_to_workspace", ("w1", "t1"), {}, "POST", "/api/workspaces/w1/templates/t1", NO_BODY),
    ("workspaces", "remove_template_from_workspace", ("w1", "t1"), {}, "DELETE", "/api/workspaces/w1/templates/t1",
     NO_BODY),
    ("tool_history", "get_tool_history", (), {}, "GET", "/api/tool-history", NO_BODY),
    ("tool_history", "get_tool_history", (), {"template_ids": ["a", "b"], "workspace_id": "w"}, "GET",
     "/api/tool-history?templateIds=a&templateIds=b&workspaceId=w", NO_BODY),
    ("tool_history", "create_tool_history", ("t1", {"x": 1}), {}, "POST", "/api/tool-history",
     {"templateId": "t1", "inputs": {"x": 1}, "chatMessages": []}),
    ("tool_history", "get_tool_history_item", ("h1", "w"), {}, "GET", "/api/tool-history/h1?workspaceId=w", NO_BODY),
    ("tool_history", "delete_tool_history_item", ("h1",), {}, "DELETE", "/api/tool-history/h1", NO_BODY),
    ("tool_history", "search_tool_history", ("busca x", "w", 5), {}, "GET",
     "/api/tool-history/search?query=busca%20x&WorkspaceId=w&ResultSize=5", NO_BODY),
    ("tool_history", "restore_tool_history", ("h1",), {}, "POST", "/api/tool-history/h1/restore", {}),
    ("categories", "get_categories", (), {"types": [1, 2], "name": "N"}, "GET", "/api/category?types=1&types=2&name=N",
     NO_BODY),
    ("categories", "get_category_types", (), {}, "GET", "/api/category/types", NO_BODY),
    ("categories", "get_category", ("c1",), {}, "GET", "/api/category/c1", NO_BODY),
    ("files", "get_upload_token", (), {}, "GET", "/api/storage/uploadtoken?folder=useruploads", NO_BODY),
    ("files", "get_upload_token", ("cont", "f.txt", "pasta"), {}, "GET",
     "/api/storage/uploadtoken?folder=pasta&containerName=cont&filename=f.txt", NO_BODY),
    ("files", "download_file", ("m", "f1"), {}, "GET", "/api/provider-files/download?model=m&fileId=f1", NO_BODY),
    ("user_secrets", "get_secrets", (), {}, "GET", "/api/secrets", NO_BODY),
    ("user_secrets", "create_secret", ("V", "s"), {}, "POST", "/api/secrets", {"variable": "V", "secret": "s"}),
    ("user_secrets", "update_secret", ("s1", "V", "s"), {}, "PUT", "/api/secrets/s1", {"variable": "V", "secret": "s"}),
    ("user_secrets", "delete_secret", ("s1",), {}, "DELETE", "/api/secrets/s1", NO_BODY),
    ("notifications", "get_notifications", (), {}, "GET", "/api/notifications", NO_BODY),
    ("notifications", "mark_notification_as_read", ("n1",), {}, "PATCH", "/api/notifications/n1/read", NO_BODY),
    ("notifications", "mark_all_notifications_as_read", (), {}, "PATCH", "/api/notifications/mark-all-read", NO_BODY),
    ("notifications", "dismiss_notification", ("n1",), {}, "PATCH", "/api/notifications/n1/dismiss", NO_BODY),
    ("notifications", "get_unread_count", (), {}, "GET", "/api/notifications/count/unread", NO_BODY),
]


class ServiceEndpointsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http = FakeHttp()
        self.sai = SAILibrary(SaiSettings(BASE, "segredo"), self.http)

    async def test_every_endpoint(self):
        for service, method, args, kwargs, http_method, path, body in CASES:
            with self.subTest(f"{service}.{method}{args}"):
                self.http.requests.clear()
                await getattr(getattr(self.sai, service), method)(*args, **kwargs)
                request = self.http.requests[0]
                self.assertEqual((request.method, request.url, request.json_body), (http_method, BASE + path, body))
                self.assertEqual(request.headers, {"X-Api-Key": "segredo"})

    def test_cases_cover_every_public_service_method(self):
        covered = {case[:2] for case in CASES} | {("files", "upload_file")}
        for name in ("health", "profile", "models", "chat", "templates", "conversations", "workspaces",
                     "tool_history", "categories", "files", "user_secrets", "notifications"):
            service = getattr(self.sai, name)
            public = {attr for attr in dir(type(service)) if not attr.startswith("_")} - {"filter_models_by_type"}
            with self.subTest(name):
                self.assertEqual({(name, attr) for attr in public} - covered, set())

    async def test_upload_file_sends_content_as_multipart(self):
        path = self.enterContext(_temp_file(b"dados"))
        await self.sai.files.upload_file(path, model="m")
        request = self.http.requests[0]
        self.assertEqual((request.method, request.url), ("POST", BASE + "/api/provider-files/upload?model=m"))
        self.assertEqual((request.file.filename, request.file.content), (path.name, b"dados"))

    async def test_upload_missing_file_fails_without_request(self):
        result = await self.sai.files.upload_file("nao-existe.bin")
        self.assertFalse(result.success)
        self.assertIn("nao-existe.bin", result.error_message)
        self.assertEqual(self.http.requests, [])


class HelpersTest(unittest.TestCase):
    def test_compact_drops_blank_but_keeps_zero_and_false(self):
        self.assertEqual(compact(a=None, b="", c=[], d=(), e=0, f=False, g="x"), {"e": 0, "f": False, "g": "x"})

    def test_base_url_is_required(self):
        http = FakeHttp()
        with self.assertRaises(ValueError):
            BaseService(http, "", {})

    def test_filter_models_by_type_ignores_bool_and_missing_type(self):
        models = [{"name": "a", "type": 0}, {"name": "b", "type": 1}, {"name": "c", "type": True}, {"name": "d"}]
        self.assertEqual([m["name"] for m in ModelService.filter_models_by_type(models, ModelType.AUDIO)], ["b"])
        self.assertEqual([m["name"] for m in ModelService.filter_models_by_type(models, ModelType.CHAT)], ["a"])

    def test_filter_models_by_type_accepts_text_types_returned_by_the_api(self):
        # Formato observado em /api/models em 2026-10-30.
        models = [{"name": "gpt", "type": "LLM"}, {"name": "img", "type": "Image"}, {"name": "x", "type": "Outro"},
                  {"name": "y", "type": 9}]
        self.assertEqual([m["name"] for m in ModelService.filter_models_by_type(models, ModelType.CHAT)], ["gpt"])
        self.assertEqual([m["name"] for m in ModelService.filter_models_by_type(models, ModelType.IMAGE)], ["img"])
        self.assertEqual(ModelService.filter_models_by_type(models, ModelType.AUDIO), [])


@contextlib.contextmanager
def _temp_file(content):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "arquivo.bin"
        path.write_bytes(content)
        yield path


if __name__ == "__main__":
    unittest.main()
