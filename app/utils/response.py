from fastapi.responses import RedirectResponse


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)
