"""Dashboard session/auth endpoints and session-scoped read APIs."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select

from backend.app.database.models import Event, utc_now_iso
from backend.app.database.models import Session as SessionRow
from backend.app.schemas.normalized import EventsPage, SnapshotResponse
from backend.app.security import DASHBOARD_COOKIE_NAME, BrowserSessions, validate_browser_origin
from backend.app.services.views import to_normalized_event, to_session_view

router = APIRouter()

SNAPSHOT_WINDOW = 200
EVENTS_PAGE_MAX = 500
EVENTS_PAGE_DEFAULT = 200


# ---------------------------------------------------------------------------
# Browser session (access code -> HttpOnly cookie)
# ---------------------------------------------------------------------------


@router.post("/auth/browser-session")
async def create_browser_session(request: Request, response: Response) -> dict:
    """Exchange the local dashboard access code for a session cookie.

    The code is submitted in the JSON body (never the URL). Origin-validated.
    """
    settings = request.app.state.settings
    validate_browser_origin(request, settings, write=True)
    try:
        body = await request.json()
    except Exception:
        body = {}
    code = body.get("code") if isinstance(body, dict) else None
    throttle = request.app.state.auth_throttle
    throttle.check()  # closed guard refuses even correct codes until it lapses
    code_ok = isinstance(code, str) and hmac.compare_digest(code, request.app.state.dashboard_code)
    if not code_ok:
        throttle.record_failure()
        raise HTTPException(status_code=403, detail="invalid access code")
    throttle.reset()
    sessions: BrowserSessions = request.app.state.browser_sessions
    sessions.issue(response)
    return {"authenticated": True, "expires_in": settings.dashboard_session_ttl_seconds}


@router.get("/auth/status")
async def auth_status(request: Request) -> dict:
    validate_browser_origin(request, request.app.state.settings, write=False)
    sessions: BrowserSessions = request.app.state.browser_sessions
    if not sessions.validate(request):
        raise HTTPException(status_code=401, detail="dashboard session required")
    return {"authenticated": True}


@router.post("/auth/end-session", status_code=204)
async def end_browser_session(request: Request, response: Response) -> None:
    validate_browser_origin(request, request.app.state.settings, write=True)
    sessions: BrowserSessions = request.app.state.browser_sessions
    if request.cookies.get(DASHBOARD_COOKIE_NAME):
        sessions.revoke(request)
    response.delete_cookie(DASHBOARD_COOKIE_NAME, path="/")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def require_dashboard(request: Request) -> None:
    validate_browser_origin(request, request.app.state.settings, write=False)
    sessions: BrowserSessions = request.app.state.browser_sessions
    sessions.require(request)


async def _get_session_or_404(db, session_id: str) -> SessionRow:
    row = (await db.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return row


@router.get("/sessions")
async def list_sessions(request: Request, limit: int = Query(default=50, ge=1, le=50)) -> dict:
    require_dashboard(request)
    async with request.app.state.sessions() as db:
        rows = (
            (
                await db.execute(
                    select(SessionRow)
                    .order_by(
                        SessionRow.last_activity_at.desc().nullslast(),
                        SessionRow.created_at.desc(),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return {
        "sessions": [to_session_view(row).model_dump(mode="json") for row in rows],
        "generated_at": utc_now_iso(),
    }


@router.get("/sessions/{session_id}/snapshot")
async def session_snapshot(request: Request, session_id: str) -> dict:
    require_dashboard(request)
    db_factory = request.app.state.sessions
    async with db_factory() as db:
        row = await _get_session_or_404(db, session_id)
        events = (
            (
                await db.execute(
                    select(Event)
                    .where(Event.session_id == session_id)
                    .order_by(Event.cursor.desc())
                    .limit(SNAPSHOT_WINDOW)
                )
            )
            .scalars()
            .all()
        )
    ordered = sorted(events, key=lambda item: item.cursor)
    first_loaded = ordered[0].cursor if ordered else None
    return SnapshotResponse(
        session=to_session_view(row),
        events=[to_normalized_event(event) for event in ordered],
        latest_cursor=row.latest_cursor,
        first_loaded_cursor=first_loaded,
        has_older_events=(first_loaded is not None and row.event_count > len(ordered)),
    ).model_dump(mode="json")


@router.get("/sessions/{session_id}/events")
async def session_events(
    request: Request,
    session_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=EVENTS_PAGE_DEFAULT, ge=1, le=EVENTS_PAGE_MAX),
) -> dict:
    require_dashboard(request)
    db_factory = request.app.state.sessions
    async with db_factory() as db:
        await _get_session_or_404(db, session_id)
        rows = (
            (
                await db.execute(
                    select(Event)
                    .where(Event.session_id == session_id, Event.cursor > after)
                    .order_by(Event.cursor.asc())
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
    has_more = len(rows) > limit
    page = rows[:limit]
    return EventsPage(
        events=[to_normalized_event(event) for event in page],
        has_more=has_more,
        next_after=page[-1].cursor if page else after,
    ).model_dump(mode="json")
