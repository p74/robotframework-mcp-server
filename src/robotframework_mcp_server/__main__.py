from __future__ import annotations

import argparse
import asyncio
import json

from .server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Robot Framework MCP server")
    parser.add_argument("--describe-tools", action="store_true", help="Print registered tool metadata and exit")
    args = parser.parse_args()

    server = create_server()
    if args.describe_tools:
        tools = asyncio.run(server.list_tools())
        print(json.dumps([{"name": tool.name, "description": tool.description} for tool in tools], indent=2))
        return
    server.run()


if __name__ == "__main__":
    main()
