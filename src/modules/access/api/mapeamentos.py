"""Rotas de mapeamento de grupo do diretório para papel (spec 003, R3; design § Rotas)."""

from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.core.ids import uuid7
from src.core.paginacao import TAMANHO_PADRAO, NumeroDaPagina, PaginaOut, TamanhoDaPagina
from src.core.problem import problema
from src.modules.access.api.deps import (
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.access.api.schemas import EscopoIn, EscopoOut
from src.modules.access.application.mapeamentos import (
    PERMISSAO,
    MapeamentoDeGrupo,
    PedidoDeMapeamento,
    criar_mapeamento,
    listar_mapeamentos,
    remover_mapeamento,
)

router = APIRouter(prefix="/api/v1/admin", tags=["administração de acesso"])


class MapeamentoCreate(BaseModel):
    """003/R3.1: o grupo do diretório, o papel e o escopo exigido pelo papel."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    grupo_id: UUID = Field(description="Id do grupo do diretório (spec 004).")
    papel: str = Field(
        min_length=1, max_length=50, pattern=r"^[A-Z_]+$", description="Código do papel."
    )
    escopo: EscopoIn


class MapeamentoOut(BaseModel):
    id: UUID
    grupo_id: UUID
    papel: str = Field(description="Código do papel.")
    escopo: EscopoOut
    criado_por: UUID

    @classmethod
    def de(cls, mapeamento: MapeamentoDeGrupo) -> Self:
        return cls(
            id=mapeamento.id,
            grupo_id=mapeamento.grupo_id,
            papel=mapeamento.papel,
            escopo=EscopoOut.de(mapeamento.escopo),
            criado_por=mapeamento.criado_por,
        )


@router.get(
    "/mapeamentos-grupo",
    summary="Listar mapeamentos grupo→papel",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `papel:assign`"),
        422: problema("Parâmetro inválido"),
    },
)
async def listar(
    request: Request,
    usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[MapeamentoOut]:
    """003/R3: os mapeamentos, na ordem de criação."""
    async with request.app.state.sessoes() as sessao:
        resultado = await listar_mapeamentos(
            pagina=pagina,
            tamanho=tamanho,
            mapeamentos=request.app.state.repositorio_de_mapeamentos(sessao),
        )
    return PaginaOut(
        itens=[MapeamentoOut.de(mapeamento) for mapeamento in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.post(
    "/mapeamentos-grupo",
    status_code=201,
    summary="Mapear grupo do diretório para papel",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `papel:assign`, ou mapeamento de grupo de que se é membro"),
        409: problema("O grupo já está mapeado para este papel neste escopo"),
        422: problema(
            "Campos inválidos, papel inexistente, escopo de nível diferente do exigido pelo "
            "papel ou inexistente"
        ),
    },
)
async def criar(
    request: Request,
    response: Response,
    corpo: MapeamentoCreate,
    usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
    sessao: SessaoDeNegocio,
) -> MapeamentoOut:
    """003/R3.1: os membros ativos do grupo recebem o papel, que vale na próxima requisição
    deles (R4.5)."""
    estado = request.app.state
    mapeamento = await criar_mapeamento(
        PedidoDeMapeamento(
            grupo_id=corpo.grupo_id,
            papel=corpo.papel,
            nivel=corpo.escopo.tipo,
            id_do_escopo=corpo.escopo.id,
        ),
        novo_id=uuid7(),
        usuario=usuario,
        ator=ator_da_requisicao(request, usuario),
        mapeamentos=estado.repositorio_de_mapeamentos(sessao),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        membros=estado.membros_de_grupo(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
        gerar_id=uuid7,
    )
    response.headers["Location"] = f"/api/v1/admin/mapeamentos-grupo/{mapeamento.id}"
    return MapeamentoOut.de(mapeamento)


@router.delete(
    "/mapeamentos-grupo/{id}",
    status_code=204,
    summary="Remover mapeamento grupo→papel",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `papel:assign`"),
        404: problema("O mapeamento não existe"),
        422: problema("Id inválido"),
    },
)
async def remover(
    request: Request,
    id: UUID,
    usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
    sessao: SessaoDeNegocio,
) -> Response:
    """003/R3.2, R3.3: saem as atribuições derivadas do mapeamento; as diretas ficam."""
    estado = request.app.state
    await remover_mapeamento(
        id,
        ator=ator_da_requisicao(request, usuario),
        mapeamentos=estado.repositorio_de_mapeamentos(sessao),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
    )
    return Response(status_code=204)
