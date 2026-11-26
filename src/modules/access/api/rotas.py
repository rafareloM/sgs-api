"""`GET /me` e administração de papéis, atribuições e mapeamentos grupo→papel (spec 003, design
§ Rotas; T6, T7 e T8)."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.core.ids import uuid7
from src.core.problem import PROBLEM_JSON
from src.modules.access.api.deps import (
    Autenticado,
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.access.application import atribuicoes as casos
from src.modules.access.application import mapeamentos as casos_de_mapeamento

router = APIRouter(prefix="/api/v1", tags=["acesso"])


def _problema(descricao: str) -> dict[str, Any]:
    return {"description": descricao, "content": {PROBLEM_JSON: {}}}


_ERROS: dict[int | str, dict[str, Any]] = {
    401: _problema("Sem access token válido"),
    403: _problema("Sem `papel:assign`, ou atribuição a si mesmo (segregação de funções)"),
}

Administrador = Annotated[UsuarioAtual, Depends(require(casos.PERMISSAO))]


class EscopoOut(BaseModel):
    tipo: str
    id: str | None


class AtribuicaoOut(BaseModel):
    id: UUID
    usuario_id: UUID
    papel: str
    escopo_tipo: str
    escopo_id: str | None
    origem: str
    valido_ate: datetime | None

    @classmethod
    def de(cls, a: casos.Atribuicao) -> Self:
        return cls(
            id=a.id,
            usuario_id=a.user_id,
            papel=a.papel,
            escopo_tipo=a.scope_type,
            escopo_id=a.scope_id,
            origem=a.origin,
            valido_ate=a.valid_until,
        )


class MeOut(BaseModel):
    """003/R5.1: para o front montar a tela inicial coerente com o perfil."""

    id: UUID
    username: str
    nome: str
    email: str | None
    origem: str
    papeis: list[AtribuicaoOut]
    permissoes: dict[str, list[EscopoOut]]


class PapelOut(BaseModel):
    codigo: str
    nome: str
    descricao: str
    escopo_exigido: str


class AtribuicaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usuario_id: UUID
    papel: str = Field(min_length=1, max_length=50)
    escopo_tipo: Literal["global", "area", "distrito", "unidade"]
    escopo_id: str | None = Field(default=None, max_length=36)
    valido_ate: datetime | None = None


class MapeamentoIn(BaseModel):
    """003/R3.1: o grupo do diretório, o papel e o escopo exigido pelo papel (R2.1)."""

    model_config = ConfigDict(extra="forbid")

    grupo_id: UUID = Field(description="Id do grupo do diretório (spec 004).")
    papel: str = Field(min_length=1, max_length=50)
    escopo_tipo: Literal["global", "area", "distrito", "unidade"]
    escopo_id: str | None = Field(default=None, max_length=36)


class MapeamentoOut(BaseModel):
    id: UUID
    grupo_id: UUID
    papel: str
    escopo_tipo: str
    escopo_id: str | None
    criado_por: UUID

    @classmethod
    def de(cls, m: casos_de_mapeamento.MapeamentoDeGrupo) -> Self:
        return cls(
            id=m.id,
            grupo_id=m.grupo_id,
            papel=m.papel,
            escopo_tipo=m.scope_type,
            escopo_id=m.scope_id,
            criado_por=m.criado_por,
        )


@router.get("/me", summary="Perfil do usuário logado", responses={401: _ERROS[401]})
async def me(request: Request, usuario: Autenticado, sessao: SessaoDeNegocio) -> MeOut:
    """003/R5.1: só exige estar autenticado."""
    perfil = await casos.perfil(
        usuario,
        atribuicoes=request.app.state.repositorio_de_atribuicoes(sessao),
        agora=datetime.now(UTC),
    )
    return MeOut(
        id=perfil.usuario.id,
        username=perfil.usuario.username,
        nome=perfil.usuario.display_name,
        email=perfil.usuario.email,
        origem=perfil.usuario.source,
        papeis=[AtribuicaoOut.de(a) for a in perfil.atribuicoes],
        permissoes={
            codigo: [EscopoOut(tipo=str(e["tipo"]), id=e["id"]) for e in escopos]
            for codigo, escopos in perfil.permissoes.items()
        },
    )


@router.get("/admin/papeis", summary="Papéis e o escopo que cada um exige", responses=_ERROS)
async def papeis(
    request: Request, usuario: Administrador, sessao: SessaoDeNegocio
) -> list[PapelOut]:
    """003/R1, R2.1."""
    itens = await casos.listar_papeis(
        atribuicoes=request.app.state.repositorio_de_atribuicoes(sessao)
    )
    return [
        PapelOut(
            codigo=p.codigo, nome=p.nome, descricao=p.descricao, escopo_exigido=p.escopo_exigido
        )
        for p in itens
    ]


@router.get("/admin/atribuicoes", summary="Atribuições vigentes", responses=_ERROS)
async def listar(
    request: Request,
    usuario: Administrador,
    sessao: SessaoDeNegocio,
    usuario_id: Annotated[UUID | None, Query(description="Só deste usuário.")] = None,
) -> list[AtribuicaoOut]:
    itens = await casos.listar_atribuicoes(
        usuario_id,
        atribuicoes=request.app.state.repositorio_de_atribuicoes(sessao),
        agora=datetime.now(UTC),
    )
    return [AtribuicaoOut.de(a) for a in itens]


@router.post(
    "/admin/atribuicoes",
    status_code=201,
    summary="Atribuir papel",
    responses={**_ERROS, 422: _problema("Usuário, papel, escopo ou validade inválidos")},
)
async def atribuir(
    request: Request, corpo: AtribuicaoIn, usuario: Administrador, sessao: SessaoDeNegocio
) -> AtribuicaoOut:
    """003/R2.1 a R2.5: audita `papel.atribuido`; vale na próxima requisição (R4.5)."""
    estado = request.app.state
    atribuicao = await casos.atribuir(
        usuario_id=corpo.usuario_id,
        papel=corpo.papel,
        escopo_tipo=corpo.escopo_tipo,
        escopo_id=corpo.escopo_id,
        valido_ate=corpo.valido_ate,
        quem=usuario,
        ator=ator_da_requisicao(request, usuario),
        novo_id=uuid7(),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
    )
    return AtribuicaoOut.de(atribuicao)


@router.delete(
    "/admin/atribuicoes/{id_}",
    status_code=204,
    summary="Remover atribuição",
    responses={**_ERROS, 404: _problema("Atribuição inexistente")},
)
async def remover(
    request: Request, id_: UUID, usuario: Administrador, sessao: SessaoDeNegocio
) -> Response:
    """003/R2.4: audita `papel.removido`."""
    estado = request.app.state
    await casos.remover(
        id_,
        quem=usuario,
        ator=ator_da_requisicao(request, usuario),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
    )
    return Response(status_code=204)


@router.get("/admin/mapeamentos-grupo", summary="Mapeamentos grupo→papel", responses=_ERROS)
async def listar_mapeamentos(
    request: Request, usuario: Administrador, sessao: SessaoDeNegocio
) -> list[MapeamentoOut]:
    """003/R3: os mapeamentos, na ordem de criação."""
    itens = await casos_de_mapeamento.listar_mapeamentos(
        mapeamentos=request.app.state.repositorio_de_mapeamentos(sessao)
    )
    return [MapeamentoOut.de(m) for m in itens]


@router.post(
    "/admin/mapeamentos-grupo",
    status_code=201,
    summary="Mapear grupo do diretório para papel",
    responses={
        401: _ERROS[401],
        403: _problema(
            "Sem `papel:assign`, ou mapeamento de grupo de que se é membro (segregação de funções)"
        ),
        409: _problema("O grupo já está mapeado para este papel neste escopo"),
        422: _problema("Papel ou escopo inválidos"),
    },
)
async def mapear(
    request: Request, corpo: MapeamentoIn, usuario: Administrador, sessao: SessaoDeNegocio
) -> MapeamentoOut:
    """003/R3.1: os membros ativos do grupo recebem o papel (origem `group`), que vale na
    próxima requisição deles (R4.5); audita `mapeamento.criado` e cada `papel.atribuido`."""
    estado = request.app.state
    mapeamento = await casos_de_mapeamento.criar_mapeamento(
        grupo_id=corpo.grupo_id,
        papel=corpo.papel,
        escopo_tipo=corpo.escopo_tipo,
        escopo_id=corpo.escopo_id,
        quem=usuario,
        ator=ator_da_requisicao(request, usuario),
        novo_id=uuid7(),
        mapeamentos=estado.repositorio_de_mapeamentos(sessao),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        membros=estado.membros_de_grupo(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
        gerar_id=uuid7,
    )
    return MapeamentoOut.de(mapeamento)


@router.delete(
    "/admin/mapeamentos-grupo/{id_}",
    status_code=204,
    summary="Remover mapeamento grupo→papel",
    responses={**_ERROS, 404: _problema("Mapeamento inexistente")},
)
async def remover_mapeamento(
    request: Request, id_: UUID, usuario: Administrador, sessao: SessaoDeNegocio
) -> Response:
    """003/R3.2, R3.3: saem as atribuições derivadas do mapeamento (cada uma auditada como
    `papel.removido`); as diretas ficam. Audita `mapeamento.removido`."""
    estado = request.app.state
    await casos_de_mapeamento.remover_mapeamento(
        id_,
        quem=usuario,
        ator=ator_da_requisicao(request, usuario),
        mapeamentos=estado.repositorio_de_mapeamentos(sessao),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
    )
    return Response(status_code=204)
