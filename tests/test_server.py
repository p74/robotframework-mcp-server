from __future__ import annotations

import json
from decimal import Decimal
import sys
import tempfile
import threading
import unittest
import zipfile
from functools import partial
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from robotframework_mcp_server import SchemaValidationLibrary, analyse_project, create_server, generate_from_swagger_url, reworktooling


class ReworkToolingTests(unittest.TestCase):
    def test_reworktooling_uses_gherkin_inline_args_and_separate_locators(self) -> None:
        result = reworktooling(
            feature_name="Login flow",
            page_name="Login Page",
            steps=[
                "Given user opens the login page",
                "When user enters <username> into the username field",
                "And user enters <password> into the password field",
                "Then user sees <message> message",
            ],
            base_url="https://app.example.test",
        )

        suite = result["files"]["tests/login-flow.robot"]
        page_resource = result["files"]["resources/pages/LoginPage.resource"]
        locator_resource = result["files"]["resources/locators/LoginPageLocators.resource"]

        self.assertIn("Scenario: Login flow", suite)
        self.assertIn("When user enters sample_username into the username field", suite)
        self.assertIn("When user enters ${username} into the username field", page_resource)
        self.assertIn("And user enters ${password} into the password field", page_resource)
        self.assertIn("Resource    ../locators/LoginPageLocators.resource", page_resource)
        self.assertIn("${LOGIN_PAGE_USERNAME_LOCATOR}", locator_resource)
        self.assertIn("${LOGIN_PAGE_PASSWORD_LOCATOR}", locator_resource)


class AnalyseProjectTests(unittest.TestCase):
    def test_analyse_project_reads_robot_markdown_docx_and_xlsx_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "keywords.robot").write_text(
                "*** Keywords ***\nLogin With Valid Credentials\n    No Operation\n",
                encoding="utf-8",
            )
            (root / "notes.md").write_text("# Reset Password\n- Given account exists\n", encoding="utf-8")
            self._create_docx(root / "guide.docx", ["Keyword: Export Report"])
            self._create_xlsx(root / "matrix.xlsx", ["Approve Invoice"])

            result = analyse_project(str(root))

        self.assertIn("Login With Valid Credentials", result["keywords"])
        self.assertIn("Reset Password", result["keywords"])
        self.assertIn("Given account exists", result["keywords"])
        self.assertIn("Export Report", result["keywords"])
        self.assertIn("Approve Invoice", result["keywords"])
        self.assertEqual(result["files_analyzed"], 4)

    @staticmethod
    def _create_docx(path: Path, paragraphs: list[str]) -> None:
        document_xml = "".join(
            f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"></Types>",
            )
            archive.writestr(
                "word/document.xml",
                f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>{document_xml}</w:body></w:document>",
            )

    @staticmethod
    def _create_xlsx(path: Path, values: list[str]) -> None:
        shared_strings = "".join(f"<si><t>{value}</t></si>" for value in values)
        sheet_rows = "".join(
            f"<row r=\"{index}\"><c r=\"A{index}\" t=\"s\"><v>{index - 1}</v></c></row>" for index, _ in enumerate(values, start=1)
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"></Types>",
            )
            archive.writestr(
                "xl/sharedStrings.xml",
                f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">{shared_strings}</sst>",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>{sheet_rows}</sheetData></worksheet>",
            )


class SwaggerGenerationTests(unittest.TestCase):
    def test_generate_from_swagger_url_creates_schema_validated_robot_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            spec_path = root / "swagger.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.0",
                        "paths": {
                            "/pets": {
                                "get": {
                                    "operationId": "listPets",
                                    "responses": {
                                        "200": {
                                            "description": "ok",
                                            "content": {
                                                "application/json": {
                                                    "schema": {
                                                        "type": "array",
                                                        "items": {
                                                            "type": "object",
                                                            "required": ["id", "name"],
                                                            "properties": {
                                                                "id": {"type": "integer"},
                                                                "name": {"type": "string"},
                                                            },
                                                        },
                                                    }
                                                }
                                            },
                                        }
                                    },
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(ValueError):
                    generate_from_swagger_url(f"http://127.0.0.1:{server.server_port}/swagger.json", suite_name="Pet API")
                result = generate_from_swagger_url(
                    f"http://127.0.0.1:{server.server_port}/swagger.json",
                    suite_name="Pet API",
                    allow_private_urls=True,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

        resource = result["files"]["resources/PetApi.resource"]
        suite = result["files"]["tests/pet-api.robot"]
        schema_text = result["files"]["schemas/list-pets.schema.json"]

        self.assertIn("*** Settings ***", resource)
        self.assertIn("Library    RequestsLibrary", resource)
        self.assertIn("${LIST_PETS_SCHEMA_PATH}    ${CURDIR}${/}..${/}schemas${/}list-pets.schema.json", resource)
        self.assertIn("When client sends GET request to /pets using ${session_alias}", resource)
        self.assertIn("Then response for List Pets matches schema ${response}", resource)
        self.assertIn("    ${payload}=    Evaluate    ${response}.json()", resource)
        self.assertIn("Response Should Match Schema File", resource)
        self.assertIn("Scenario: List Pets", suite)
        self.assertIn("${response}=    When client sends GET request to /pets using api", suite)
        self.assertIn('"type": "array"', schema_text)

    def test_schema_validation_library_validates_generated_schema(self) -> None:
        validator = SchemaValidationLibrary()
        validator.response_should_match_schema(
            [{"id": 1, "name": "Fido"}],
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    },
                },
            },
        )
        with self.assertRaises(AssertionError):
            validator.response_should_match_schema(
                [{"id": "wrong"}],
                {"type": "array", "items": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}},
            )
        with self.assertRaises(AssertionError):
            validator.response_should_match_schema(True, {"type": "integer"})
        with self.assertRaises(AssertionError):
            validator.response_should_match_schema(None, {"type": "integer"})
        with self.assertRaises(AssertionError):
            validator.response_should_match_schema([], {"type": "object"})
        validator.response_should_match_schema("ok", {"type": "string"})
        validator.response_should_match_schema(Decimal("1.5"), {"type": "number"})

    def test_generate_from_swagger_url_rejects_redirects(self) -> None:
        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(302)
                self.send_header("Location", "/swagger.json")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(ValueError):
                generate_from_swagger_url(
                    f"http://127.0.0.1:{server.server_port}/redirect",
                    suite_name="Redirect API",
                    allow_private_urls=True,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_generate_from_swagger_url_skips_non_object_path_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            spec_path = root / "swagger.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.0",
                        "paths": {
                            "/broken": "invalid",
                            "/pets": {
                                "get": {
                                    "operationId": "listPets",
                                    "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}}},
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = generate_from_swagger_url(
                    f"http://127.0.0.1:{server.server_port}/swagger.json",
                    suite_name="Pet API",
                    allow_private_urls=True,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

        self.assertEqual(result["operations"], ["listPets"])

    def test_generate_from_swagger_url_rejects_cyclic_schema_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            spec_path = root / "swagger.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "openapi": "3.0.0",
                        "components": {"schemas": {"Node": {"$ref": "#/components/schemas/Node"}}},
                        "paths": {
                            "/nodes": {
                                "get": {
                                    "operationId": "listNodes",
                                    "responses": {
                                        "200": {
                                            "description": "ok",
                                            "content": {
                                                "application/json": {"schema": {"$ref": "#/components/schemas/Node"}}
                                            },
                                        }
                                    },
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(ValueError):
                    generate_from_swagger_url(
                        f"http://127.0.0.1:{server.server_port}/swagger.json",
                        suite_name="Node API",
                        allow_private_urls=True,
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class ServerRegistrationTests(unittest.TestCase):
    def test_server_registers_expected_tools(self) -> None:
        import asyncio

        server = create_server()
        tools = asyncio.run(server.list_tools())
        names = {tool.name for tool in tools}
        self.assertEqual(names, {"reworktooling", "analyse", "generate_from_swagger_url"})


if __name__ == "__main__":
    unittest.main()
