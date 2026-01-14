from __future__ import annotations

import os
from datetime import datetime
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import redirect, request, session, url_for

ALLOWED_ROLES = {"student", "teacher", "head", "admin"}

F = TypeVar("F", bound=Callable[..., Any])


def normalize_role(role: str) -> str:
    return role if role in ALLOWED_ROLES else "student"


def get_academic_year() -> int:
    value = os.getenv("ACADEMIC_YEAR")
    if value:
        try:
            return int(value)
        except ValueError:
            pass
    return datetime.now().year


def require_login(role_for_login: str):
    """
    Requires the current session to be logged in; otherwise redirects to `/login?role=...`.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            if session.get("role") is None:
                return redirect(url_for("login", role=role_for_login))
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def require_role(required_role: str):
    """
    Requires the current session role to match; otherwise redirects to `/login?role=...`.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            if session.get("role") != required_role:
                return redirect(url_for("login", role=required_role))
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator

