from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .core import analyse_project, generate_from_swagger_url, reworktooling


def create_server() -> MCPServer:
    server = MCPServer(
        name="robotframework-mcp-server",
        title="Robot Framework MCP Server",
        description="Robot Framework scaffolding, project analysis, and Swagger-based API generation.",
    )

    @server.tool(name="reworktooling", description="Generate Robot Framework page-object scaffolding with Gherkin inline-argument keywords.")
    def rework_tooling(feature_name: str, page_name: str, steps: list[str], base_url: str = "https://example.test") -> dict:
        return reworktooling(feature_name=feature_name, page_name=page_name, steps=steps, base_url=base_url)

    @server.tool(name="analyse", description="Analyse Robot Framework projects, resources, docs, and spreadsheets to discover keywords.")
    def analyse(project_path: str) -> dict:
        return analyse_project(project_path=project_path)

    @server.tool(name="generate_from_swagger_url", description="Generate Robot Framework API suites and schema files from a Swagger or OpenAPI URL.")
    def swagger_generation(
        swagger_url: str,
        suite_name: str = "Generated API Suite",
        allow_private_urls: bool = False,
    ) -> dict:
        return generate_from_swagger_url(
            swagger_url=swagger_url,
            suite_name=suite_name,
            allow_private_urls=allow_private_urls,
        )

    return server
