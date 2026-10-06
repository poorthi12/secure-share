from __future__ import annotations

import re


def valid_password(password: str) -> bool:
    return len(password) >= 10 and bool(re.search(r"[A-Za-z]", password)) and bool(re.search(r"\d", password))
