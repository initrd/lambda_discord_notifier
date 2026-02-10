"""Base utilities and registry for parsers."""

from __future__ import annotations
from typing import Callable, Any

# Registry for EventBridge Detail Parsers
# Maps 'detail-type' string -> parser function
_DETAIL_PARSERS: dict[str, Callable[[dict[str, Any]], str]] = {}


def register_parser(detail_type: str) -> Callable:
    """Decorator to register a custom formatter for a specific EventBridge detail-type."""
    def decorator(func: Callable[[dict[str, Any]], str]) -> Callable:
        _DETAIL_PARSERS[detail_type] = func
        return func
    return decorator


def get_detail_parser(detail_type: str) -> Callable[[dict[str, Any]], str] | None:
    """Retrieve a registered parser for the given detail-type."""
    return _DETAIL_PARSERS.get(detail_type)
