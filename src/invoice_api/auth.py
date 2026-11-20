"""Sessions and roles.

The frontend sends its session token in the `X-SESSION` header, as the
contract says. Tokens are signed JWTs that carry a role:

- `viewer` can read everything;
- `accountant` can also create, change and delete invoices.

For the public demo, `POST /sessions` hands out a token for either role
without a password, so visitors can try both. Swapping in a real identity
provider (OpenID Connect) only changes `read_token`: the routes depend on
roles, not on how the user signed in.
"""

import datetime as dt
from typing import Annotated

import jwt
from fastapi import Depends, Header

from invoice_api.config import get_settings
from invoice_api.errors import ApiError
from invoice_api.schemas import Role, SessionOut

ALGORITHM = "HS256"
AUDIENCE = "invoice-api"


def issue_token(role: Role, now: dt.datetime | None = None) -> SessionOut:
    settings = get_settings()
    issued = now or dt.datetime.now(dt.UTC)
    expires = issued + dt.timedelta(hours=settings.session_hours)
    token = jwt.encode(
        {
            "sub": f"demo-{role.value}",
            "role": role.value,
            "aud": AUDIENCE,
            "iat": issued,
            "exp": expires,
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    return SessionOut(token=token, role=role, expires_at=expires)


def read_token(token: str) -> Role:
    try:
        claims = jwt.decode(
            token, get_settings().secret_key, algorithms=[ALGORITHM], audience=AUDIENCE
        )
        return Role(claims["role"])
    except jwt.ExpiredSignatureError as error:
        raise ApiError(401, "Your session has expired. Sign in again.") from error
    except (jwt.InvalidTokenError, KeyError, ValueError) as error:
        raise ApiError(401, "Invalid session") from error


def current_role(x_session: Annotated[str | None, Header()] = None) -> Role:
    if not x_session:
        raise ApiError(401, "Sign in first: send a session token in the X-SESSION header")
    return read_token(x_session)


def require_accountant(role: Annotated[Role, Depends(current_role)]) -> Role:
    if role is not Role.ACCOUNTANT:
        raise ApiError(403, "Only an accountant can change invoices")
    return role


CanRead = Annotated[Role, Depends(current_role)]
CanWrite = Annotated[Role, Depends(require_accountant)]
