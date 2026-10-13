"""Small student-authored MCP server: a safe calculator and a time-zone clock.

Runs over stdio like the other servers. The LLM is unreliable at arithmetic and has no clock
for other time zones, so these two tools give it exact answers.
"""

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("utilities")

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_EXPONENT = 1000  # keeps `9 ** 9 ** 9` from hanging the server


def _evaluate(node: ast.AST) -> float:
    """Evaluate only numbers and arithmetic operators; anything else is rejected."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ValueError(f"exponent too large (limit is {_MAX_EXPONENT})")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))
    raise ValueError("only numbers and + - * / // % ** ( ) are allowed")


@mcp.tool()
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression exactly, e.g. '(17 * 23) / 4 + 2 ** 10'.

    Supports numbers, + - * / // % ** and parentheses. Use this instead of doing math in your head.
    """
    try:
        result = _evaluate(ast.parse(expression.strip(), mode="eval").body)
    except SyntaxError as error:
        raise ValueError(f"not a valid arithmetic expression: {error.msg}") from error
    except ZeroDivisionError as error:
        raise ValueError("division by zero") from error
    return str(result)


@mcp.tool()
def current_time(timezone: str = "UTC") -> str:
    """Get the current date and time in an IANA time zone, e.g. 'America/Los_Angeles' or 'Asia/Kolkata'."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"unknown time zone '{timezone}'; use an IANA name like 'Europe/Paris'") from error
    return now.strftime(f"%A, %B %d, %Y %H:%M:%S ({timezone}, UTC%z)")


if __name__ == "__main__":
    mcp.run(transport="stdio")
