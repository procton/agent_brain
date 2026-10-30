"""Local security helpers.

- Ingestion (`POST /api/events/batch`) requires `Authorization: Bearer <token>`;
  the token lives in a 0600 file inside the data directory and is never sent to
  the browser or embedded in frontend assets.
- The dashboard uses a browser-session cookie issued after presenting the
  local access code (shown in the backend console / data directory). The code
  is submitted in a request body, never a URL, so it stays out of logs and
  browser history.
- Browser origins are validated against an explicit allowlist. Cross-origin
  requests are rejected; permissive CORS is never enabled. Same-origin GETs
  legitimately carry no `Origin` header, which is why absence is allowed for
  GET while state-changing requests and WebSocket handshakes require an
  allowlisted origin.

Loopback binding alone is not a complete security boundary; residual risks are
documented in docs/privacy.md.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response, status

from backend.app.config import Settings

DASHBOARD_COOKIE_NAME = "observatory_dashboard"


def bearer_token_from_request(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def require_ingest_token(request: Request, expected_token: str) -> None:
    token = bearer_token_from_request(request)
    if not hmac.compare_digest(token, expected_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid credential")


def origin_from_request(request: Request) -> str | None:
    return request.headers.get("origin")


def origin_allowed(origin: str | None, settings: Settings, *, require_for_write: bool) -> bool:
    allowed = settings.allowed_origins
    if origin is None:
        # Browsers omit Origin on same-origin GETs; never on POSTs.
        return not require_for_write
    return origin in allowed


def validate_browser_origin(request: Request, settings: Settings, *, write: bool) -> None:
    origin = origin_from_request(request)
    if not origin_allowed(origin, settings, require_for_write=write):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin not allowed")


@dataclass
class BrowserSessions:
    """In-memory dashboard cookie store. Residual limitation: a backend restart
    ends dashboard sessions and users re-enter the access code."""

    settings: Settings
    _sessions: dict[str, float]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions = {}

    def issue(self, response: Response) -> str:
        import secrets

        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.time() + self.settings.dashboard_session_ttl_seconds
        response.set_cookie(
            key=DASHBOARD_COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="strict",
            path="/",
            max_age=self.settings.dashboard_session_ttl_seconds,
            secure=False,  # loopback deployment, no TLS termination locally
        )
        return token

    def validate(self, request: Request) -> bool:
        token = request.cookies.get(DASHBOARD_COOKIE_NAME)
        return token is not None and self.validate_token(token)

    def validate_token(self, token: str | None) -> bool:
        if not token:
            return False
        expires = self._sessions.get(token)
        if expires is None:
            return False
        if expires < time.time():
            self._sessions.pop(token, None)
            return False
        return True

    def revoke(self, request: Request) -> None:
        token = request.cookies.get(DASHBOARD_COOKIE_NAME)
        if token:
            self._sessions.pop(token, None)

    def require(self, request: Request) -> None:
        if not self.validate(request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="dashboard session required",
                headers={"WWW-Authenticate": "Cookie"},
            )


def cookie_from_scope(scope) -> str | None:
    """Extract cookie from an ASGI websocket/HTTP scope without Starlette parsing."""
    for key, value in scope.get("headers") or []:
        if key == b"cookie":
            cookie_header = value.decode("latin-1")
            for chunk in cookie_header.split(";"):
                name, _, cookie_value = chunk.strip().partition("=")
                if name == DASHBOARD_COOKIE_NAME:
                    return cookie_value
    return None
