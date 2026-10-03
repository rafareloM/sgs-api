"""Rotas de saúde do processo (spec 001, R1.3). São públicas e ficam fora de /api/v1."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["saúde"])


class HealthStatus(BaseModel):
    status: Literal["ok"]


@router.get("/live", summary="O processo está no ar")
async def live() -> HealthStatus:
    return HealthStatus(status="ok")
