"""
JSON Serialization Utilities for WorkFlowOS.
Guarantees all data structures sent over the API or converted to JSON are 100% valid JSON-safe primitives.
"""

from pathlib import Path
from datetime import datetime, date, time
from typing import Any, Dict, List, Union


def make_json_safe(obj: Any) -> Any:
    """
    Recursively converts any object into pure JSON-serializable Python data structures:
    dicts, lists, strings, numbers, booleans, and None.
    """
    if obj is None:
        return None
    if isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, str):
        # Return string and string subclasses (like StatusString) as-is
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, (set, tuple)):
        return [make_json_safe(item) for item in obj]
    if isinstance(obj, list):
        return [make_json_safe(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, BaseException):
        return {
            "type": obj.__class__.__name__,
            "message": str(obj)
        }

    # Custom objects with to_dict method
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        try:
            return make_json_safe(obj.to_dict())
        except Exception:
            pass

    # Custom objects with __dict__
    if hasattr(obj, "__dict__"):
        try:
            return make_json_safe(vars(obj))
        except Exception:
            pass

    # Fallback to string representation
    return str(obj)
