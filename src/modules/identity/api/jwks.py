"""`GET /.well-known/jwks.json` (spec 002, R3.2).

Rota pública (design da 002, Decisões: lista de rotas públicas): só publica chaves públicas, para
quem precisa conferir a assinatura de um access token. Fica fora de /api/v1, no caminho padrão.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from src.modules.identity.application.jwks import TokenService, chaves_publicas

router = APIRouter(tags=["autenticação"])


class Jwk(BaseModel):
    """Chave pública EC P-256 no formato JWK (RFC 7517 e 7518)."""

    model_config = ConfigDict(from_attributes=True)

    kty: str
    crv: str
    alg: str
    use: str
    kid: str
    x: str
    y: str


class Jwks(BaseModel):
    keys: list[Jwk]


@router.get("/.well-known/jwks.json", summary="Chaves públicas de verificação dos access tokens")
async def jwks(request: Request) -> Jwks:
    tokens: TokenService = request.app.state.token_service
    return Jwks(keys=[Jwk.model_validate(chave) for chave in chaves_publicas(tokens)])
