from __future__ import annotations

import secrets


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
