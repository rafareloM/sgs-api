"""Usuários logados, com papéis, para os testes que chamam rotas protegidas pela API.

Os dados entram pelo login da API (papel `sgs_app`), como faria a aplicação; os ids de distrito,
área técnica e tipo de unidade vêm do código semeado pelas migrações, nunca do id gerado.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.ids import uuid7
from src.modules.identity.domain.sessions import AuthSession
from src.modules.identity.domain.tokens import TokenService
from src.modules.identity.infrastructure.repository import SqlSessionRepository, SqlUserRepository
from tests.factories import make_auth_session, make_user

type Sessoes = async_sessionmaker[AsyncSession]
type Atribuicao = tuple[str, tuple[str, str | None]]
"""Código do papel e escopo da atribuição: (`scope_type`, `scope_id`; nulo se global)."""

GLOBAL: tuple[str, str | None] = ("global", None)

_ID_PELO_CODIGO = {
    "distrito": text("SELECT id FROM districts WHERE code = :codigo"),
    "area": text("SELECT id FROM technical_areas WHERE code = :codigo"),
    "tipo_unidade": text("SELECT id FROM unit_types WHERE code = :codigo"),
}


async def id_pelo_codigo(sessoes: Sessoes, referencia: str, codigo: str) -> int:
    """Id de um distrito, área técnica ou tipo de unidade pelo código semeado."""
    async with sessoes() as sessao:
        id_ = await sessao.scalar(_ID_PELO_CODIGO[referencia], {"codigo": codigo})
    if id_ is None:
        raise LookupError(f"{referencia} {codigo!r} não semeado")
    return int(id_)


async def logado(sessoes: Sessoes, *atribuicoes: Atribuicao) -> AuthSession:
    """Usuário ativo com os papéis dados e uma sessão de login aberta."""
    usuario = uuid7()
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(
            make_user(id=usuario, username=f"u{usuario.hex}", email=None)
        )
        for papel, (nivel, id_do_escopo) in atribuicoes:
            await sessao.execute(
                text(
                    "INSERT INTO role_assignments"
                    " (id, user_id, role_id, scope_type, scope_id, origin)"
                    " SELECT :id, :usuario, id, :nivel, :id_do_escopo, 'direct'"
                    " FROM roles WHERE code = :papel"
                ),
                {
                    "id": uuid7(),
                    "usuario": usuario,
                    "nivel": nivel,
                    "id_do_escopo": id_do_escopo,
                    "papel": papel,
                },
            )
        sessao_de_login = make_auth_session(user_id=usuario, created_at=datetime.now(UTC))
        await SqlSessionRepository(sessao).add(sessao_de_login)
    return sessao_de_login


def bearer(app: FastAPI, sessao_de_login: AuthSession) -> dict[str, str]:
    """Cabeçalho `Authorization` com um access token da sessão de login."""
    tokens: TokenService = app.state.token_service
    return {"Authorization": f"Bearer {tokens.issue_access_token(sessao_de_login).token}"}


async def eventos(sessoes: Sessoes, acao: str) -> list[dict[str, Any]]:
    """Registros da trilha com a ação dada, na ordem de gravação."""
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text(
                "SELECT actor_user_id, session_id, entity_type, entity_id, changes, metadata"
                " FROM audit_log WHERE action = :acao ORDER BY id"
            ),
            {"acao": acao},
        )
        return [dict(linha) for linha in resultado.mappings()]
