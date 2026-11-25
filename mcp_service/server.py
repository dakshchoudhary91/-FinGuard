
"""
FinGuard MCP Server.

In-process JSON-RPC 2.0 server exposing:
- plaid_db_lookup
- financial_calculator
- market_data_parser

Supports initialization, tool discovery and tool execution.
"""

import json
import logging
import math
from typing import Any, Dict

from mcp_service.tools import (
    tool_plaid_db_lookup,
    tool_financial_calculator,
    tool_market_data_parser,
)

logger = logging.getLogger("FinGuard_MCP_Server")


MCP_PROTOCOL_VERSION = "2024-11-05"

MCP_TOOLS_MANIFEST = [
    {
        "name": "plaid_db_lookup",
        "description": (
            "Look up simulated banking balances and transactions "
            "for checking, credit card, savings and investment accounts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_type": {
                    "type": "string",
                    "enum": [
                        "checking",
                        "credit_card",
                        "savings",
                        "investment",
                        "all",
                    ],
                },
                "include_transactions": {
                    "type": "boolean",
                    "default": True,
                },
            },
            "required": ["account_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "financial_calculator",
        "description": (
            "Calculate affordability, financial runway, "
            "debt-to-income ratio and emergency buffer impact."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "calc_type": {
                    "type": "string",
                    "enum": [
                        "affordability_ratio",
                        "runway_days",
                        "dti_ratio",
                        "buffer_impact",
                    ],
                },
                "liquid_cash": {"type": "number", "default": 0.0},
                "purchase_amount": {"type": "number", "default": 0.0},
                "monthly_expenses": {"type": "number", "default": 0.0},
                "total_debt": {"type": "number", "default": 0.0},
                "monthly_income": {"type": "number", "default": 0.0},
                "emergency_target": {"type": "number", "default": 5000.0},
            },
            "required": ["calc_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "market_data_parser",
        "description": (
            "Analyze historical stock and ETF prices, volatility "
            "and market anomalies."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "default": "ALL",
                },
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 5,
                },
            },
            "additionalProperties": False,
        },
    },
]


class MCPServer:
    """FinGuard JSON-RPC 2.0 tool server."""

    def __init__(
        self,
        server_name: str = "FinGuard-MCP-Server",
        version: str = "1.1.0",
    ):
        self.server_name = server_name
        self.version = version

    @staticmethod
    def _rpc_error(
        request_id: Any,
        code: int,
        message: str,
        data: Any = None,
    ) -> Dict[str, Any]:
        error = {
            "code": code,
            "message": message,
        }

        if data is not None:
            error["data"] = data

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        }

    @staticmethod
    def _valid_request_id(request_id: Any) -> bool:
        return (
            request_id is None
            or (
                isinstance(request_id, (str, int))
                and not isinstance(request_id, bool)
            )
        )

    def _validate_arguments(
        self,
        tool_name: str,
        arguments: Any,
    ) -> Dict[str, Any]:
        """Validate tool arguments against the published input schema."""

        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object.")

        manifest = next(
            (
                tool for tool in MCP_TOOLS_MANIFEST
                if tool["name"] == tool_name
            ),
            None,
        )

        if manifest is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        schema = manifest["inputSchema"]
        properties = schema["properties"]
        required = schema.get("required", [])

        unknown = set(arguments) - set(properties)

        if unknown:
            raise ValueError(
                f"Unsupported argument(s): {', '.join(sorted(unknown))}"
            )

        for field in required:
            if field not in arguments:
                raise ValueError(f"Missing required argument: {field}")

        validated = dict(arguments)

        for field, definition in properties.items():
            if field not in validated:
                if "default" in definition:
                    validated[field] = definition["default"]
                continue

            value = validated[field]
            expected_type = definition["type"]

            if expected_type == "string":
                valid_type = isinstance(value, str)

            elif expected_type == "boolean":
                valid_type = isinstance(value, bool)

            elif expected_type == "integer":
                valid_type = (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                )

            elif expected_type == "number":
                valid_type = (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                )

            else:
                raise ValueError(
                    f"Unsupported schema type for {field}: {expected_type}"
                )

            if not valid_type:
                raise ValueError(
                    f"Argument '{field}' must be of type {expected_type}."
                )

            if "enum" in definition and value not in definition["enum"]:
                raise ValueError(
                    f"Invalid value for '{field}'. "
                    f"Allowed values: {definition['enum']}."
                )

            if "minimum" in definition and value < definition["minimum"]:
                raise ValueError(
                    f"Argument '{field}' must be at least "
                    f"{definition['minimum']}."
                )

            if "maximum" in definition and value > definition["maximum"]:
                raise ValueError(
                    f"Argument '{field}' must be at most "
                    f"{definition['maximum']}."
                )

        return validated

    def handle_request(self, request_json: str) -> str:
        """Handle one JSON-RPC request or notification."""

        try:
            request = json.loads(request_json)
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps(
                self._rpc_error(
                    None,
                    -32700,
                    "Parse error",
                    str(exc),
                )
            )

        if not isinstance(request, dict):
            return json.dumps(
                self._rpc_error(None, -32600, "Invalid Request")
            )

        request_id = request.get("id")

        if request.get("jsonrpc") != "2.0":
            return json.dumps(
                self._rpc_error(
                    request_id,
                    -32600,
                    "Invalid Request: jsonrpc must be 2.0",
                )
            )

        method = request.get("method")

        if not isinstance(method, str):
            return json.dumps(
                self._rpc_error(
                    request_id,
                    -32600,
                    "Invalid Request: method is required",
                )
            )

        if "id" in request and not self._valid_request_id(request_id):
            return json.dumps(
                self._rpc_error(None, -32600, "Invalid Request: invalid id")
            )

        params = request.get("params", {})

        if not isinstance(params, dict):
            return json.dumps(
                self._rpc_error(
                    request_id,
                    -32602,
                    "Invalid params: expected an object",
                )
            )

        if method == "initialize":
            result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    }
                },
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.version,
                },
            }

            return json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            })

        if method == "notifications/initialized":
            # JSON-RPC notifications do not receive responses.
            return ""

        if method == "tools/list":
            return json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": MCP_TOOLS_MANIFEST,
                },
            })

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not isinstance(tool_name, str):
                return json.dumps(
                    self._rpc_error(
                        request_id,
                        -32602,
                        "Tool name must be a string",
                    )
                )

            try:
                result = self.execute_tool(
                    tool_name,
                    arguments,
                )

                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    result,
                                    allow_nan=False,
                                ),
                            }
                        ],
                        "isError": False,
                    },
                })

            except (ValueError, TypeError) as exc:
                return json.dumps(
                    self._rpc_error(
                        request_id,
                        -32602,
                        "Invalid tool arguments",
                        str(exc),
                    )
                )

            except Exception as exc:
                logger.exception(
                    "MCP execution failed for %s",
                    tool_name,
                )

                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps({
                                    "error": "Tool execution failed.",
                                    "tool": tool_name,
                                    "details": str(exc),
                                }),
                            }
                        ],
                        "isError": True,
                    },
                })

        return json.dumps(
            self._rpc_error(
                request_id,
                -32601,
                f"Method '{method}' not found",
            )
        )

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate and dispatch a tool call."""

        args = self._validate_arguments(
            tool_name,
            arguments,
        )

        if tool_name == "plaid_db_lookup":
            result = tool_plaid_db_lookup(
                account_type=args["account_type"],
                include_transactions=args["include_transactions"],
            )

        elif tool_name == "financial_calculator":
            result = tool_financial_calculator(
                calc_type=args["calc_type"],
                liquid_cash=args["liquid_cash"],
                purchase_amount=args["purchase_amount"],
                monthly_expenses=args["monthly_expenses"],
                total_debt=args["total_debt"],
                monthly_income=args["monthly_income"],
                emergency_target=args["emergency_target"],
            )

        elif tool_name == "market_data_parser":
            result = tool_market_data_parser(
                symbol=args["symbol"],
                days=args["days"],
            )

        else:
            raise ValueError(f"Unknown tool: {tool_name}")

        if not isinstance(result, dict):
            raise TypeError(
                f"Tool '{tool_name}' did not return a dictionary."
            )

        # FinGuard tools use an "error" key to represent failed
        # operations. Do not return those as successful tool results.
        if "error" in result:
            raise RuntimeError(str(result["error"]))

        return result


mcp_server_instance = MCPServer()
