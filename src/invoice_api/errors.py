"""Errors, all answered as `{"message": "..."}` as the API contract says."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class NotFoundError(ApiError):
    def __init__(self, message: str = "Not found") -> None:
        super().__init__(404, message)


class UnprocessableError(ApiError):
    """The request is well formed but breaks a business rule."""

    def __init__(self, message: str) -> None:
        super().__init__(422, message)


class BadRequestError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(400, message)


def _message(status: int, message: str) -> JSONResponse:
    return JSONResponse({"message": message}, status_code=status)


def _describe(error: RequestValidationError) -> str:
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"] if part != "body")
    return f"{where}: {first['msg']}" if where else str(first["msg"])


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return _message(error.status, error.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
        return _message(422, _describe(error))

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        return _message(error.status_code, str(error.detail))
