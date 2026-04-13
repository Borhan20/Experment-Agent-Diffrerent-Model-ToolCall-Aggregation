"""Demo calculator tool handlers — safe AST evaluation and unit conversion."""

from __future__ import annotations

import ast
import operator
from typing import Any, Dict

# Safe operations allowed in math expressions
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Unit conversion factors — all relative to a common base
# Temperature is handled specially (offset conversions)
_CONVERSIONS = {
    # Distance: base = meters
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "km": 1000.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "miles": 1609.344,
    "mile": 1609.344,
    "feet": 0.3048,
    "foot": 0.3048,
    "inches": 0.0254,
    "inch": 0.0254,
    "cm": 0.01,
    # Weight: base = grams
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "lbs": 453.592,
    "lb": 453.592,
    "pounds": 453.592,
    "pound": 453.592,
    "oz": 28.3495,
    "ounce": 28.3495,
    "ounces": 28.3495,
    # Speed: base = m/s
    "m/s": 1.0,
    "kph": 0.277778,
    "mph": 0.44704,
}

_TEMPERATURE_UNITS = {"celsius", "fahrenheit", "kelvin", "c", "f", "k"}


def _safe_eval(node: ast.AST) -> float:
    """Recursively evaluate a safe math expression AST node."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if op_type == ast.Div and right == 0:
            raise ValueError("Division by zero")
        return _SAFE_OPS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return _SAFE_OPS[op_type](_safe_eval(node.operand))
    else:
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")


async def calculate(expression: str) -> Dict[str, Any]:
    """Evaluate a mathematical expression safely.

    Args:
        expression: A math expression string (e.g., "1500 / 12", "2 ** 10").

    Returns:
        Dict with expression, result (float), and formatted string.

    Raises:
        ValueError: For unsafe or malformed expressions.
    """
    expression = expression.strip()

    # Parse and validate AST — reject anything non-numeric
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid expression syntax: {e}") from e

    result = _safe_eval(tree)

    return {
        "expression": expression,
        "result": result,
        "formatted": str(result) if result != int(result) else str(int(result)),
    }


async def convert_units(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    """Convert a value between common units.

    Supports temperature (celsius/fahrenheit/kelvin),
    distance (km/miles/m/feet/inches/cm),
    weight (kg/lbs/g/oz), and speed (m/s/kph/mph).

    Args:
        value: Numeric value to convert.
        from_unit: Source unit name (case-insensitive).
        to_unit: Target unit name (case-insensitive).

    Returns:
        Dict with original and converted values and units.

    Raises:
        ValueError: If units are not recognized or conversion is not possible.
    """
    from_u = from_unit.lower().strip()
    to_u = to_unit.lower().strip()

    # Temperature conversions (offset-based — cannot use factor table)
    if from_u in _TEMPERATURE_UNITS or to_u in _TEMPERATURE_UNITS:
        converted = _convert_temperature(value, from_u, to_u)
        return {
            "original_value": value,
            "original_unit": from_unit,
            "converted_value": round(converted, 4),
            "converted_unit": to_unit,
        }

    # Factor-based conversions
    from_factor = _CONVERSIONS.get(from_u)
    to_factor = _CONVERSIONS.get(to_u)

    if from_factor is None:
        raise ValueError(f"Unknown source unit: '{from_unit}'")
    if to_factor is None:
        raise ValueError(f"Unknown target unit: '{to_unit}'")

    # Convert to base unit, then to target
    base_value = value * from_factor
    converted = base_value / to_factor

    return {
        "original_value": value,
        "original_unit": from_unit,
        "converted_value": round(converted, 6),
        "converted_unit": to_unit,
    }


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Handle temperature conversion between celsius/fahrenheit/kelvin."""
    # Normalize to Celsius first
    if from_unit in ("celsius", "c"):
        celsius = value
    elif from_unit in ("fahrenheit", "f"):
        celsius = (value - 32) * 5 / 9
    elif from_unit in ("kelvin", "k"):
        celsius = value - 273.15
    else:
        raise ValueError(f"Unknown temperature unit: '{from_unit}'")

    # Convert from Celsius to target
    if to_unit in ("celsius", "c"):
        return celsius
    elif to_unit in ("fahrenheit", "f"):
        return celsius * 9 / 5 + 32
    elif to_unit in ("kelvin", "k"):
        return celsius + 273.15
    else:
        raise ValueError(f"Unknown temperature unit: '{to_unit}'")
