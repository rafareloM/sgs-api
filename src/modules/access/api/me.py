"""`GET /api/v1/me`: perfil do usuário logado (spec 003, R5.1; design § Rotas).

Rota só autenticada, sem permissão (`ROTAS_SO_AUTENTICADAS` em
`tests/architecture/test_rotas_protegidas.py`): qualquer usuário logado vê o próprio perfil.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.core.problem import PROBLEM_JSON
from src.modules.access.api.schemas import EscopoOut
from src.modules.access.application.perfil import Perfil, perfil_do_usuario
from src.modules.access.domain.authorization import PapelAtribuido
from src.modules.identity.api.deps import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["perfil"])

_Origem = Literal["direta", "grupo"]
_ORIGENS: dict[str, _Origem] = {"direct": "direta", "group": "grupo"}


class PapelOut(BaseModel):
    codigo: str
    nome: str
    escopo: EscopoOut
    origem: _Origem = Field(description="Atribuição direta ou derivada de grupo do diretório.")
    valido_ate: datetime | None

    @classmethod
    def de(cls, papel: PapelAtribuido) -> Self:
        return cls(
            codigo=papel.codigo,
            nome=papel.nome,
            escopo=EscopoOut.de(papel.escopo),
            origem=_ORIGENS[papel.origem],
            valido_ate=papel.valido_ate,
        )


class PerfilOut(BaseModel):
    """003/R5.1: dados básicos, papéis com escopos e permissões efetivas."""

    id: UUID
    username: str
    nome: str
    email: str | None
    papeis: Sequence[PapelOut]
    permissoes: Mapping[str, Sequence[EscopoOut]] = Field(
        description="Código da permissão (`recurso:acao`) → escopos em que o usuário a tem."
    )

    @classmethod
    def de(cls, perfil: Perfil) -> Self:
        return cls(
            id=perfil.id,
            username=perfil.username,
            nome=perfil.nome,
            email=perfil.email,
            papeis=[PapelOut.de(papel) for papel in perfil.papeis],
            permissoes={
                codigo: [EscopoOut.de(escopo) for escopo in escopos]
                for codigo, escopos in sorted(perfil.permissoes.items())
            },
        )


@router.get(
    "/me",
    summary="Perfil do usuário logado",
    responses={401: {"description": "Sem access token válido", "content": {PROBLEM_JSON: {}}}},
)
async def me(request: Request, usuario: CurrentUser) -> PerfilOut:
    """003/R5.1. Os papéis e as permissões são os vigentes agora, como o `require()` os vê."""
    estado = request.app.state
    async with estado.sessoes() as sessao:
        perfil = await perfil_do_usuario(
            usuario.id,
            usuarios=estado.repositorio_de_usuarios(sessao),
            papeis=estado.repositorio_de_permissoes(sessao),
            permissoes=estado.repositorio_de_permissoes(sessao),
            resolvedor=estado.resolvedor_de_permissoes,
        )
    return PerfilOut.de(perfil)
