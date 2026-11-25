
"""
FinGuard MCP Client.

Provides a shared client for ADK and CrewAI agents.
Communicates with the FinGuard MCP server using JSON-RPC 2.0.
"""

import json
import itertools
import logging
import threading

from typing import Dict, Any, List, Optional

from mcp_service.server import mcp_server_instance


logger = logging.getLogger("FinGuard_MCP_Client")


class MCPProtocolError(RuntimeError):
    """Raised when an MCP or JSON-RPC operation fails."""


class MCPClient:
    """Client for the FinGuard in-process MCP server."""

    def __init__(self, server=None):
        self.server = (
            server if server is not None
            else mcp_server_instance
        )

        self.initialized = False
        self.protocol_version = None

        self._cached_tools: Dict[str, Dict[str, Any]] = {}
        self._request_counter = itertools.count(1)
        self._lock = threading.RLock()

        self.initialize()

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}_{next(self._request_counter)}"

    def _send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request and validate its response."""

        request_id = self._next_id("finguard")

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        try:
            raw_response = self.server.handle_request(
                json.dumps(request, allow_nan=False)
            )

        except Exception as exc:
            raise MCPProtocolError(
                f"MCP transport failed during '{method}': {exc}"
            ) from exc

        if not raw_response:
            raise MCPProtocolError(
                f"MCP server returned an empty response for '{method}'."
            )

        try:
            response = json.loads(raw_response)

        except (json.JSONDecodeError, TypeError) as exc:
            raise MCPProtocolError(
                f"MCP server returned invalid JSON for '{method}'."
            ) from exc

        if not isinstance(response, dict):
            raise MCPProtocolError(
                "MCP response must be a JSON object."
            )

        if response.get("jsonrpc") != "2.0":
            raise MCPProtocolError(
                "MCP response has an invalid JSON-RPC version."
            )

        if response.get("id") != request_id:
            raise MCPProtocolError(
                "MCP response ID does not match the request ID."
            )

        if "error" in response:
            error = response["error"]

            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message", "Unknown MCP error")
                details = error.get("data")

                raise MCPProtocolError(
                    f"MCP error {code}: {message}"
                    + (f" Details: {details}" if details else "")
                )

            raise MCPProtocolError(
                f"MCP returned an invalid error response: {error}"
            )

        if "result" not in response:
            raise MCPProtocolError(
                "MCP response is missing the result field."
            )

        return response["result"]

    def initialize(self):
        """Perform and validate the MCP initialization handshake."""

        with self._lock:
            result = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "FinGuard-Agent-Client",
                        "version": "1.1.0",
                    },
                },
            )

            if not isinstance(result, dict):
                raise MCPProtocolError(
                    "MCP initialization result must be an object."
                )

            server_info = result.get("serverInfo")
            capabilities = result.get("capabilities")
            protocol_version = result.get("protocolVersion")

            if not isinstance(server_info, dict):
                raise MCPProtocolError(
                    "MCP server did not provide server information."
                )

            if not isinstance(capabilities, dict):
                raise MCPProtocolError(
                    "MCP server did not provide capabilities."
                )

            if not isinstance(capabilities.get("tools"), dict):
                raise MCPProtocolError(
                    "MCP server does not advertise tool capability."
                )

            if not protocol_version:
                raise MCPProtocolError(
                    "MCP server did not provide a protocol version."
                )

            self.protocol_version = protocol_version
            self.initialized = True

            logger.info(
                "Connected to MCP server %s version %s using protocol %s",
                server_info.get("name"),
                server_info.get("version"),
                protocol_version,
            )

            self.refresh_tools()

    def refresh_tools(self) -> List[Dict[str, Any]]:
        """Retrieve and validate the server's available tool definitions."""

        if not self.initialized:
            raise MCPProtocolError(
                "MCP client must be initialized before tool discovery."
            )

        result = self._send_request("tools/list")

        if not isinstance(result, dict):
            raise MCPProtocolError(
                "MCP tools/list result must be an object."
            )

        tools = result.get("tools")

        if not isinstance(tools, list):
            raise MCPProtocolError(
                "MCP tools/list response is missing its tools array."
            )

        validated_tools = {}

        for tool in tools:
            if not isinstance(tool, dict):
                raise MCPProtocolError(
                    "MCP tool definition must be an object."
                )

            name = tool.get("name")
            input_schema = tool.get("inputSchema")

            if not isinstance(name, str) or not name:
                raise MCPProtocolError(
                    "MCP tool definition has an invalid name."
                )

            if not isinstance(input_schema, dict):
                raise MCPProtocolError(
                    f"Tool '{name}' has an invalid input schema."
                )

            if name in validated_tools:
                raise MCPProtocolError(
                    f"Duplicate MCP tool definition: {name}"
                )

            validated_tools[name] = tool

        with self._lock:
            self._cached_tools = validated_tools

        logger.info(
            "Discovered %d MCP tools: %s",
            len(validated_tools),
            ", ".join(validated_tools),
        )

        return list(validated_tools.values())

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return cached tool definitions."""

        if not self.initialized:
            self.initialize()

        if not self._cached_tools:
            self.refresh_tools()

        return list(self._cached_tools.values())

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an MCP tool and return its parsed JSON object."""

        if not self.initialized:
            self.initialize()

        if not isinstance(name, str) or not name:
            raise ValueError("MCP tool name must be a non-empty string.")

        if arguments is None:
            arguments = {}

        if not isinstance(arguments, dict):
            raise TypeError("MCP tool arguments must be a dictionary.")

        if name not in self._cached_tools:
            raise MCPProtocolError(
                f"Tool '{name}' is not available on the MCP server."
            )

        result = self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

        if not isinstance(result, dict):
            raise MCPProtocolError(
                f"Tool '{name}' returned an invalid MCP result."
            )

        if result.get("isError") is True:
            raise MCPProtocolError(
                f"MCP tool '{name}' reported an execution error."
            )

        content = result.get("content")

        if not isinstance(content, list):
            raise MCPProtocolError(
                f"MCP tool '{name}' returned no content array."
            )

        text_parts = []

        for item in content:
            if not isinstance(item, dict):
                continue

            if item.get("type") == "text":
                text_value = item.get("text")

                if isinstance(text_value, str):
                    text_parts.append(text_value)

        if not text_parts:
            raise MCPProtocolError(
                f"MCP tool '{name}' returned no text content."
            )

        raw_text = "\n".join(text_parts)

        try:
            parsed = json.loads(raw_text)

        except json.JSONDecodeError as exc:
            raise MCPProtocolError(
                f"MCP tool '{name}' returned invalid JSON content."
            ) from exc

        if not isinstance(parsed, dict):
            raise MCPProtocolError(
                f"MCP tool '{name}' must return a JSON object."
            )

        if "error" in parsed:
            raise MCPProtocolError(
                f"MCP tool '{name}' failed: {parsed['error']}"
            )

        logger.info(
            "MCP tool '%s' executed successfully.",
            name,
        )

        return parsed


default_mcp_client = MCPClient()
