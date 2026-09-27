from __future__ import annotations

import json
import ipaddress
import re
import socket
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, build_opener, urlopen
from xml.etree import ElementTree

import yaml

SCANNABLE_EXTENSIONS = {".robot", ".resource", ".txt", ".md", ".docx", ".xlsx", ".xlsm"}
_GHERKIN_PREFIXES = ("Given ", "When ", "Then ", "And ", "But ")
_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")


def _split_words(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)


def slugify(value: str) -> str:
    separated = _split_words(value)
    slug = re.sub(r"[^a-z0-9]+", "-", separated.lower()).strip("-")
    return slug or "generated"


def titleize(value: str) -> str:
    separated = _split_words(value)
    return " ".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", separated) if part)


def _normalise_inline_arguments(step: str) -> str:
    return re.sub(r"<([A-Za-z0-9_]+)>", r"${\1}", step)


def normalise_gherkin_step(step: str) -> str:
    cleaned = _normalise_inline_arguments(step.strip())
    if not cleaned:
        raise ValueError("Steps must not be empty")
    if cleaned.startswith(_GHERKIN_PREFIXES):
        return cleaned
    return f"When {cleaned[0].lower()}{cleaned[1:]}" if len(cleaned) > 1 else f"When {cleaned}"


def _example_step(step: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"sample_{match.group(1)}"

    return re.sub(r"\$\{([A-Za-z0-9_]+)\}", replace, step)


def _robotise_path(path: str) -> str:
    return re.sub(r"\{([A-Za-z0-9_]+)\}", r"${\1}", path)


def _locator_name(page_name: str, step: str, index: int) -> str:
    remainder = re.sub(r"^(Given|When|Then|And|But)\s+", "", step).strip()
    patterns = [
        r"into (?:the )?(.+?)(?: field| input| textbox| area|$)",
        r"clicks? (?:the )?(.+?)(?: button| link| icon|$)",
        r"opens? (?:the )?(.+?)(?: page| screen|$)",
        r"sees? (?:the )?(.+?)(?: message| text| banner|$)",
    ]
    target = "element"
    for pattern in patterns:
        match = re.search(pattern, remainder, re.IGNORECASE)
        if match:
            target = match.group(1)
            break
    target_slug = slugify(target).replace("-", "_").upper()
    page_slug = slugify(page_name).replace("-", "_").upper()
    return f"${{{page_slug}_{target_slug or f'ELEMENT_{index}'}_LOCATOR}}"


def _implementation_lines(page_name: str, step: str, locator_name: str) -> list[str]:
    lowered = step.lower()
    page_slug = slugify(page_name).replace("-", "_").upper()
    inline_arguments = re.findall(r"\$\{([A-Za-z0-9_]+)\}", step)
    if "open" in lowered and "page" in lowered:
        return [f"    Go To    ${{{page_slug}_URL}}"]
    if any(token in lowered for token in ("enter", "type", "fill", "input")):
        argument = inline_arguments[0] if inline_arguments else "value"
        return [f"    Input Text    {locator_name}    ${{{argument}}}"]
    if any(token in lowered for token in ("click", "submit", "tap", "press")):
        return [f"    Click Element    {locator_name}"]
    if any(token in lowered for token in ("see", "verify", "should", "assert")):
        argument = inline_arguments[0] if inline_arguments else "expected_text"
        return [f"    Element Should Contain    {locator_name}    ${{{argument}}}"]
    return [f"    Log    TODO: Implement {step}"]


def reworktooling(feature_name: str, page_name: str, steps: list[str], base_url: str = "https://example.test") -> dict[str, Any]:
    """Generate Robot Framework scaffolding using Gherkin steps and inline arguments."""
    if not steps:
        raise ValueError("At least one step is required")

    normalised_steps = [normalise_gherkin_step(step) for step in steps]
    feature_slug = slugify(feature_name)
    page_stub = titleize(page_name).replace(" ", "") or "Page"

    suite_lines = [
        "*** Settings ***",
        f"Resource    ../resources/pages/{page_stub}.resource",
        "",
        "*** Test Cases ***",
        f"Scenario: {feature_name}",
    ]
    suite_lines.extend(f"    {_example_step(step)}" for step in normalised_steps)

    page_lines = [
        "*** Settings ***",
        "Library    SeleniumLibrary",
        f"Resource    ../locators/{page_stub}Locators.resource",
        "",
        "*** Keywords ***",
    ]
    locator_lines = [
        "*** Variables ***",
        f"${{{slugify(page_name).replace('-', '_').upper()}_URL}}    {base_url.rstrip('/')}/{slugify(page_name)}",
    ]

    generated_keywords: list[str] = []
    locator_declarations: set[str] = set()
    for index, step in enumerate(normalised_steps, start=1):
        locator_name = _locator_name(page_name, step, index)
        implementation = _implementation_lines(page_name, step, locator_name)
        page_lines.append(step)
        page_lines.extend(implementation)
        page_lines.append("")
        if locator_name not in locator_declarations:
            locator_lines.append(f"{locator_name}    css=[data-testid=\"{slugify(page_name)}-{index}\"]")
            locator_declarations.add(locator_name)
        generated_keywords.append(step)

    return {
        "feature": feature_name,
        "files": {
            f"tests/{feature_slug}.robot": "\n".join(suite_lines).strip() + "\n",
            f"resources/pages/{page_stub}.resource": "\n".join(page_lines).strip() + "\n",
            f"resources/locators/{page_stub}Locators.resource": "\n".join(locator_lines).strip() + "\n",
        },
        "keywords": generated_keywords,
    }


def _extract_robot_keywords(lines: list[str]) -> list[str]:
    keywords: list[str] = []
    in_keywords = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("***"):
            in_keywords = stripped.lower() == "*** keywords ***"
            continue
        if not in_keywords or not stripped or line.startswith((" ", "\t")) or stripped.startswith("["):
            continue
        keywords.append(stripped)
    return keywords


def _extract_text_keywords(lines: list[str]) -> list[str]:
    extracted: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[#>*\-\d.\s]+", "", stripped)
        stripped = re.sub(r"^Keyword\s*:\s*", "", stripped, flags=re.IGNORECASE)
        if len(stripped) < 3 or len(stripped) > 120:
            continue
        if not re.search(r"[A-Za-z]", stripped):
            continue
        if stripped.startswith(_GHERKIN_PREFIXES) or len(stripped.split()) > 1:
            extracted.append(stripped)
    return extracted


def _read_docx_lines(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        content = archive.read("word/document.xml")
    tree = ElementTree.fromstring(content)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return ["".join(node.itertext()).strip() for node in tree.findall(".//w:p", namespace)]


def _read_xlsx_lines(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_tree = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            shared_strings = ["".join(node.itertext()) for node in shared_tree.findall(".//s:si", namespace)]
        lines: list[str] = []
        sheet_names = [name for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml")]
        namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for sheet_name in sheet_names:
            tree = ElementTree.fromstring(archive.read(sheet_name))
            for row in tree.findall(".//s:row", namespace):
                values: list[str] = []
                for cell in row.findall("s:c", namespace):
                    text = ""
                    value_node = cell.find("s:v", namespace)
                    if value_node is None or value_node.text is None:
                        continue
                    if cell.attrib.get("t") == "s":
                        text = shared_strings[int(value_node.text)]
                    else:
                        text = value_node.text
                    if text:
                        values.append(text)
                if values:
                    lines.append(" ".join(values))
        return lines


def analyse_project(project_path: str) -> dict[str, Any]:
    """Analyse Robot Framework related assets and discover available keywords."""
    root = Path(project_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project path does not exist: {root}")

    keyword_index: dict[str, list[str]] = {}
    discovered: set[str] = set()
    warnings: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SCANNABLE_EXTENSIONS | {".xls"}:
            continue
        if path.suffix.lower() == ".xls":
            warnings.append(f"Skipped legacy Excel file without parser support: {path}")
            continue
        if path.suffix.lower() in {".robot", ".resource"}:
            keywords = _extract_robot_keywords(path.read_text(encoding="utf-8").splitlines())
        elif path.suffix.lower() in {".txt", ".md"}:
            keywords = _extract_text_keywords(path.read_text(encoding="utf-8").splitlines())
        elif path.suffix.lower() == ".docx":
            keywords = _extract_text_keywords(_read_docx_lines(path))
        else:
            keywords = _extract_text_keywords(_read_xlsx_lines(path))
        if keywords:
            relative = str(path.relative_to(root))
            unique_keywords = sorted(dict.fromkeys(keywords))
            keyword_index[relative] = unique_keywords
            discovered.update(unique_keywords)

    return {
        "project_path": str(root),
        "files_analyzed": len(keyword_index),
        "keywords": sorted(discovered),
        "keywords_by_file": keyword_index,
        "warnings": warnings,
    }


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError("Redirects are not allowed when fetching Swagger definitions")


def _assert_safe_swagger_url(swagger_url: str, allow_private_urls: bool) -> None:
    parsed = urlparse(swagger_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Swagger URL must use http or https with an explicit host")
    if allow_private_urls:
        return

    try:
        resolved = {
            entry[4][0]
            for entry in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                proto=socket.IPPROTO_TCP,
            )
        }
    except socket.gaierror as error:
        raise ValueError(f"Unable to resolve Swagger URL host: {parsed.hostname}") from error

    for address_text in resolved:
        address = ipaddress.ip_address(address_text)
        if any(
            (
                address.is_private,
                address.is_loopback,
                address.is_link_local,
                address.is_multicast,
                address.is_reserved,
                address.is_unspecified,
            )
        ):
            raise ValueError("Swagger URL host must not resolve to a private or local address")


def _read_swagger_document(swagger_url: str, allow_private_urls: bool = False, timeout: float = 15.0) -> dict[str, Any]:
    _assert_safe_swagger_url(swagger_url, allow_private_urls=allow_private_urls)
    opener = build_opener(_NoRedirectHandler())
    with opener.open(swagger_url, timeout=timeout) as response:  # noqa: S310 - validated URL with explicit timeout and redirects disabled.
        payload = response.read().decode("utf-8")
        content_type = response.headers.get("Content-Type", "")
    if "json" in content_type:
        document = json.loads(payload)
    else:
        try:
            document = json.loads(payload)
        except json.JSONDecodeError:
            document = yaml.safe_load(payload)
    if not isinstance(document, dict):
        raise ValueError("Swagger document must be a JSON or YAML object")
    return document


def _resolve_reference(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ValueError(f"Only local schema references are supported: {reference}")
    value: Any = document
    for fragment in reference[2:].split("/"):
        value = value[fragment.replace("~1", "/").replace("~0", "~")]
    return value


def _dereference_schema(document: dict[str, Any], schema: Any) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema:
            return _dereference_schema(document, _resolve_reference(document, schema["$ref"]))
        return {key: _dereference_schema(document, value) for key, value in schema.items()}
    if isinstance(schema, list):
        return [_dereference_schema(document, item) for item in schema]
    return schema


def _operation_name(method: str, path: str, operation: dict[str, Any]) -> str:
    return operation.get("operationId") or f"{method}_{slugify(path.replace('{', '').replace('}', ''))}"


def _response_schema(document: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    responses = operation.get("responses") or {}
    preferred_codes = ("200", "201", "202", "203", "204", "205", "206")
    ordered_status_codes = [
        status_code for status_code in preferred_codes if status_code in responses
    ] + [
        status_code
        for status_code in responses
        if str(status_code).startswith("2") and status_code not in preferred_codes
    ]
    for status_code in ordered_status_codes:
        if str(status_code).startswith("2"):
            response = responses[status_code]
            content = response.get("content") or {}
            if "application/json" in content:
                schema = content["application/json"].get("schema")
                if schema:
                    return _dereference_schema(document, schema)
            if "schema" in response:
                return _dereference_schema(document, response["schema"])
    return {"type": "object"}


def generate_from_swagger_url(
    swagger_url: str,
    suite_name: str = "Generated API Suite",
    allow_private_urls: bool = False,
) -> dict[str, Any]:
    """Generate Robot Framework API scaffolding from a Swagger or OpenAPI URL."""
    document = _read_swagger_document(swagger_url, allow_private_urls=allow_private_urls)
    if not (document.get("swagger") or document.get("openapi")):
        raise ValueError("Document is not a Swagger or OpenAPI definition")
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("Swagger or OpenAPI definition does not contain any paths")

    parsed_url = urlparse(swagger_url)
    origin = f"{parsed_url.scheme}://{parsed_url.netloc}" if parsed_url.scheme and parsed_url.netloc else "https://example.test"
    suite_slug = slugify(suite_name)
    suite_stub = titleize(suite_name).replace(" ", "") or "GeneratedApiSuite"

    suite_lines = [
        "*** Settings ***",
        f"Resource    ../resources/{suite_stub}.resource",
        "",
        "*** Test Cases ***",
    ]
    settings_lines = [
        "*** Settings ***",
        "Library    RequestsLibrary",
        "Library    robotframework_mcp_server.schema_validation.SchemaValidationLibrary",
    ]
    variable_lines = [
        "*** Variables ***",
        f"${{BASE_URL}}    {origin}",
    ]
    keyword_lines = [
        "*** Keywords ***",
        "Given API session ${session_alias} is available",
        "    Create Session    ${session_alias}    ${BASE_URL}",
        "",
    ]

    schema_files: dict[str, str] = {}
    generated_operations: list[str] = []

    for path, path_item in paths.items():
        robot_path = _robotise_path(path)
        for method in _HTTP_METHODS:
            operation = (path_item or {}).get(method)
            if not isinstance(operation, dict):
                continue
            operation_name = _operation_name(method, path, operation)
            operation_slug = slugify(operation_name)
            operation_title = titleize(operation_name)
            schema_path = f"schemas/{operation_slug}.schema.json"
            schema_var = f"${{{operation_slug.replace('-', '_').upper()}_SCHEMA_PATH}}"
            schema = _response_schema(document, operation)
            schema_files[schema_path] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
            variable_lines.append(f"{schema_var}    ${{CURDIR}}${{/}}..${{/}}..${{/}}{schema_path.replace('/', '${/}')}")
            keyword_lines.append(f"When client sends {method.upper()} request to {robot_path} using ${{session_alias}}")
            keyword_lines.append(f"    ${{response}}=    {method.upper()} On Session    ${{session_alias}}    {robot_path}")
            keyword_lines.append("    RETURN    ${response}")
            keyword_lines.append("")
            keyword_lines.append(f"Then response for {operation_title} matches schema ${{response}}")
            keyword_lines.append("    ${payload}=    Evaluate    $response.json()")
            keyword_lines.append(f"    Response Should Match Schema File    ${{payload}}    {schema_var}")
            keyword_lines.append("")
            suite_lines.append(f"Scenario: {operation_title}")
            suite_lines.append("    Given API session api is available")
            suite_lines.append(f"    ${{response}}=    {_example_step(f'When client sends {method.upper()} request to {robot_path} using api')}")
            suite_lines.append(f"    Then response for {operation_title} matches schema ${{response}}")
            suite_lines.append("")
            generated_operations.append(operation_name)

    if not generated_operations:
        raise ValueError("Swagger or OpenAPI definition does not contain supported HTTP operations")

    resource_content = "\n".join(settings_lines + [""] + variable_lines + [""] + keyword_lines).strip() + "\n"
    files = {
        f"tests/{suite_slug}.robot": "\n".join(suite_lines).strip() + "\n",
        f"resources/{suite_stub}.resource": resource_content,
    }
    files.update(schema_files)
    return {
        "swagger_url": swagger_url,
        "operations": generated_operations,
        "files": files,
    }
