"""Rotas de saúde (spec 001, R1.3 e R1.4). São públicas e ficam fora de /api/v1."""

import asyncio
import os
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.problem import PROBLEM_JSON, problem_response

router = APIRouter(prefix="/health", tags=["saúde"])

_READY_TIMEOUT_SECONDS = 2
_log = structlog.get_logger("sgs_api.saude")


class HealthStatus(BaseModel):
    status: Literal["ok"]


_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"description": "O banco de dados não respondeu", "content": {PROBLEM_JSON: {}}}
}


@router.get("/live", summary="O processo está no ar")
async def live() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get(
    "/ready",
    summary="A API está pronta: o banco responde",
    response_model=HealthStatus,
    responses=_UNAVAILABLE,
)
async def ready(request: Request) -> HealthStatus | JSONResponse:
    engine: AsyncEngine = request.app.state.engine
    try:
        async with asyncio.timeout(_READY_TIMEOUT_SECONDS), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as error:  # qualquer falha significa "não pronto"
        _log.warning("banco_indisponivel", erro=type(error).__name__)
        return problem_response(
            status=503,
            type_="urn:sgs:problema:indisponivel",
            title="Serviço indisponível",
            detail="O banco de dados não respondeu.",
            request_id=getattr(request.state, "request_id", None),
        )
    return HealthStatus(status="ok")
