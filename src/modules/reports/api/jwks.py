"""`GET /.well-known/relatorios-jwks.json` (spec 005, R5.4 e R5.5).

Rota pública (design da 005, § Rotas e § Segurança): só publica chaves públicas, para quem recebe
um relatório conferir a assinatura sem a API. Fica fora de /api/v1, como o JWKS da 002.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from src.modules.reports.application.assinatura import AssinadorDeRelatorio, chaves_publicas

router = APIRouter(tags=["relatórios"])


class JwkDeRelatorio(BaseModel):
    """Chave pública EC P-256 no formato JWK (RFC 7517 e 7518)."""

    model_config = ConfigDict(from_attributes=True)

    kty: str
    crv: str
    alg: str
    use: str
    kid: str
    x: str
    y: str


class JwksDeRelatorios(BaseModel):
    keys: list[JwkDeRelatorio]


@router.get(
    "/.well-known/relatorios-jwks.json",
    summary="Chaves públicas de verificação dos relatórios exportados",
)
async def relatorios_jwks(request: Request) -> JwksDeRelatorios:
    assinador: AssinadorDeRelatorio | None = request.app.state.assinador_de_relatorio
    return JwksDeRelatorios(
        keys=[JwkDeRelatorio.model_validate(chave) for chave in chaves_publicas(assinador)]
    )
