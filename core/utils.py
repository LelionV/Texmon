"""Small shared helpers used across apps."""

from core.middleware import get_current_user  # re-exported for convenience

__all__ = ["get_current_user"]
