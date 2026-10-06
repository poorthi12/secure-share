class SecureShareError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFound(SecureShareError):
    status_code = 404


class Forbidden(SecureShareError):
    status_code = 403


class Conflict(SecureShareError):
    status_code = 409


class RateLimited(SecureShareError):
    status_code = 429
