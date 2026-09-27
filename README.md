# robotframework-mcp-server

Minimal MCP server for Robot Framework scaffolding and analysis.

## Tools

- `reworktooling`: generates Gherkin-style Robot Framework scaffolding with inline arguments, page-object resources, and separate locator resources.
- `analyse`: scans `.robot`, `.resource`, `.txt`, `.md`, `.docx`, `.xlsx`, and `.xlsm` files to discover available keywords.
- `generate_from_swagger_url`: fetches a Swagger/OpenAPI URL and generates Robot Framework API source plus JSON schema files for response validation.

## Local usage

```bash
python -m pip install -e .
robotframework-mcp-server --describe-tools
```
