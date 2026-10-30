"""Authenticated batch ingestion endpoint (collector -> backend)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.schemas.normalized import IngestReport
from backend.app.schemas.source import EventBatch
from backend.app.services.ingest import IngestionService
from backend.app.security import require_ingest_token, validate_browser_origin

logger = logging.getLogger("observatory.ingest")

router = APIRouter()


@router.post("/events/batch")
async def ingest_batch(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    # The collector is not a browser and sends no Origin; a browser page from a
    # foreign origin (even with a stolen token) is refused.
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        return JSONResponse(status_code=403, content={"detail": "origin not allowed"})
    require_ingest_token(request, request.app.state.ingest_token)

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.batch_max_body_bytes:
        return JSONResponse(status_code=413, content={"detail": "batch too large"})

    raw_body = await request.body()
    if len(raw_body) > settings.batch_max_body_bytes:
        return JSONResponse(status_code=413, content={"detail": "batch too large"})

    try:
        parsed = EventBatch.model_validate(json.loads(raw_body))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.info("ingest rejected: invalid batch (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=422,
            content={"detail": "invalid batch; no events persisted"},
        )

    ingestion: IngestionService = request.app.state.ingestion
    result = await ingestion.ingest_batch(parsed)

    report = IngestReport(accepted=result.accepted, duplicates=result.duplicates)
    return JSONResponse(
        status_code=200,
        content=report.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )
