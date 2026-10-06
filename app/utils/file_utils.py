from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote


def safe_filename(filename: str) -> str:
    name = unicodedata.normalize("NFKC", filename or "file")
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    name = re.sub(r"[^\w.() \-]+", "_", name, flags=re.UNICODE)
    return (name[:180] or "file")


def content_type(filename: str, supplied: str | None) -> str:
    allowed = {"application/pdf", "image/png", "image/jpeg", "image/gif", "text/plain", "application/zip", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    value = (supplied or "application/octet-stream").split(";")[0].lower()
    return value if value in allowed else "application/octet-stream"


def attachment_header(filename: str) -> str:
    safe = safe_filename(filename)
    fallback = safe.encode("ascii", "ignore").decode("ascii").replace('"', "").replace("\\", "_") or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"
