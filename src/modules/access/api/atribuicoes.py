"""Rotas de administração de atribuições de papel (spec 003, R2; design § Rotas)."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

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
from src.modules.access.application.atribuicoes import (
    PERMISSAO,
    Atribuicao,
    PedidoDeAtribuicao,
    atribuir_papel,
    listar_atribuicoes,
    remover_atribuicao,
)

router = APIRouter(prefix="/api/v1/admin", tags=["administração de acesso"])

_ORIGENS: dict[str, Literal["direta", "grupo"]] = {"direct": "direta", "group": "grupo"}


class AtribuicaoCreate(BaseModel):
    """003/R2.1, R2.3: o papel, o usuário, o escopo exigido pelo papel e a expiração opcional."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    usuario_id: UUID
    papel: str = Field(
        min_length=1, max_length=50, pattern=r"^[A-Z_]+$", description="Código do papel."
    )
    escopo: EscopoIn
    valido_ate: AwareDatetime | None = Field(
        default=None, description="Expiração da atribuição, com fuso; sem ela, não expira."
    )


class AtribuicaoOut(BaseModel):
    id: UUID
    usuario_id: UUID
    papel: str = Field(description="Código do papel.")
    escopo: EscopoOut
    origem: Literal["direta", "grupo"] = Field(
        description="Atribuição direta ou derivada de grupo do diretório."
    )
    concedida_por: UUID | None = Field(description="Quem atribuiu; nulo se derivada de grupo.")
    valido_ate: datetime | None

    @classmethod
    def de(cls, atribuicao: Atribuicao) -> Self:
        return cls(
            id=atribuicao.id,
            usuario_id=atribuicao.usuario_id,
            papel=atribuicao.papel,
            escopo=EscopoOut.de(atribuicao.escopo),
            origem=_ORIGENS[atribuicao.origem],
            concedida_por=atribuicao.concedida_por,
            valido_ate=atribuicao.valido_ate,
        )


@router.get(
    "/atribuicoes",
    summary="Listar atribuições de papel vigentes",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `papel:assign`"),
        422: problema("Parâmetro inválido"),
    },
)
async def listar(
    request: Request,
    usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
    usuario_id: Annotated[UUID | None, Query(description="Só as deste usuário.")] = None,
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[AtribuicaoOut]:
    """003/R2, R2.3: as atribuições diretas e de grupo não expiradas, na ordem de criação."""
    async with request.app.state.sessoes() as sessao:
        resultado = await listar_atribuicoes(
            usuario_id,
            pagina=pagina,
            tamanho=tamanho,
            atribuicoes=request.app.state.repositorio_de_atribuicoes(sessao),
        )
    return PaginaOut(
        itens=[AtribuicaoOut.de(atribuicao) for atribuicao in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.post(
    "/atribuicoes",
    status_code=201,
    summary="Atribuir papel a um usuário",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `papel:assign`, ou atribuição a si mesmo (segregação de funções)"),
        409: problema("O usuário já tem este papel neste escopo"),
        422: problema(
            "Campos inválidos, usuário ou papel inexistente, expiração no passado, escopo de "
            "nível diferente do exigido pelo papel ou inexistente"
        ),
    },
)
async def atribuir(
    request: Request,
    response: Response,
    corpo: AtribuicaoCreate,
    usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
    sessao: SessaoDeNegocio,
) -> AtribuicaoOut:
    """003/R2.1 a R2.5. O papel vale para o usuário já na próxima requisição (R4.5)."""
    estado = request.app.state
    atribuicao = await atribuir_papel(
        PedidoDeAtribuicao(
            usuario_id=corpo.usuario_id,
            papel=corpo.papel,
            nivel=corpo.escopo.tipo,
            id_do_escopo=corpo.escopo.id,
            valido_ate=corpo.valido_ate,
        ),
        novo_id=uuid7(),
        usuario=usuario,
        ator=ator_da_requisicao(request, usuario),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        usuarios=estado.repositorio_de_usuarios(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
    )
    response.headers["Location"] = f"/api/v1/admin/atribuicoes/{atribuicao.id}"
    return AtribuicaoOut.de(atribuicao)


@router.delete(
    "/atribuicoes/{id}",
    status_code=204,
    summary="Remover atribuição de papel",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `papel:assign`"),
        404: problema("A atribuição não existe"),
        409: problema("A atribuição é derivada de grupo do diretório"),
        422: problema("Id inválido"),
    },
)
async def remover(
    request: Request,
    id: UUID,
    usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
    sessao: SessaoDeNegocio,
) -> Response:
    """003/R2.4, R4.5: a permissão some na próxima requisição do usuário."""
    estado = request.app.state
    await remover_atribuicao(
        id,
        ator=ator_da_requisicao(request, usuario),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
        auditoria=estado.auditoria(sessao),
    )
    return Response(status_code=204)
