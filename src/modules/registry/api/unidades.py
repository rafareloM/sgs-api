"""Rotas da unidade de saúde (design da 006 § Rotas)."""

import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from src.core.errors import PreconditionFailed, PreconditionRequired
from src.core.ids import uuid7
from src.core.paginacao import (
    TAMANHO_PADRAO,
    NumeroDaPagina,
    PaginaOut,
    TamanhoDaPagina,
)
from src.core.problem import problema
from src.modules.access.api.deps import (
    ResourceRef,
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.registry.api.schemas import (
    StatusDaUnidade,
    UnidadeCreate,
    UnidadeDesativacao,
    UnidadeDetalheOut,
    UnidadeNaListaOut,
    UnidadeOut,
    UnidadeUpdate,
)
from src.modules.registry.application.unidades import (
    FiltrosDeUnidades,
    PaginaPedida,
    atualizar_unidade,
    buscar_unidades,
    criar_unidade,
    desativar_unidade,
    detalhar_unidade,
)

router = APIRouter(prefix="/api/v1", tags=["unidades"])

# O `ETag` da unidade é a versão entre aspas, como a rota de cadastro o devolve (`"1"`).
_ETAG = re.compile(r'"([1-9][0-9]{0,9})"')


# Ids das referências são `smallint` no banco.
_IdDeReferencia = Annotated[int | None, Query(ge=1, le=32767)]

OrdemPedida = Literal["nome", "distrito", "atualizacao"]


@router.get(
    "/unidades",
    summary="Listar e buscar unidades de saúde",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `unidade:read`"),
        422: problema("Parâmetro de busca, filtro, ordenação ou paginação inválido"),
    },
)
async def listar(
    request: Request,
    usuario: Annotated[UsuarioAtual, Depends(require("unidade:read"))],
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Trecho do nome (sem diferença de acento, caixa e espaços) ou do CNES.",
        ),
    ] = None,
    tipo: Annotated[_IdDeReferencia, Query(description="Id do tipo de unidade.")] = None,
    area: Annotated[_IdDeReferencia, Query(description="Id da área técnica.")] = None,
    distrito: Annotated[_IdDeReferencia, Query(description="Id do distrito sanitário.")] = None,
    status: StatusDaUnidade | None = None,
    com_pendencias: Annotated[
        bool | None,
        Query(description="`true`: só as com pendências de validação; `false`: só as sem."),
    ] = None,
    ordenar: Annotated[
        OrdemPedida | None,
        Query(
            description=(
                "`nome` (padrão), `distrito` ou `atualizacao` (mais recente primeiro). Sem ele e "
                "com `q`, a mais parecida com o texto vem primeiro."
            )
        ),
    ] = None,
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[UnidadeNaListaOut]:
    """006/R2.1 a R2.4, R2.6: uma página das unidades no escopo de leitura do usuário, com o total
    da listagem. Os filtros se combinam. O item é o resumo, sem os dados de contato do gestor."""
    texto = None if q is None else (q.strip() or None)
    filtros = FiltrosDeUnidades(
        texto=texto,
        tipo=tipo,
        area=area,
        distrito=distrito,
        status=status,
        com_pendencias=com_pendencias,
    )
    async with request.app.state.sessoes() as sessao:
        resultado = await buscar_unidades(
            filtros,
            ordenar,
            PaginaPedida(numero=pagina, tamanho=tamanho),
            usuario=usuario,
            unidades=request.app.state.repositorio_de_unidades(sessao),
        )
    return PaginaOut(
        itens=[UnidadeNaListaOut.de(unidade) for unidade in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get(
    "/unidades/{id}",
    summary="Detalhar unidade de saúde",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `unidade:read` no escopo da unidade"),
        404: problema("A unidade não existe"),
        422: problema("Id inválido"),
    },
)
async def detalhar(
    request: Request,
    response: Response,
    id: UUID,
    usuario: Annotated[UsuarioAtual, Depends(require("unidade:read", ResourceRef("unidade")))],
) -> UnidadeDetalheOut:
    """006/R2.5, R2.6: a unidade com os equipamentos e serviços vinculados e o `ETag` da versão,
    o mesmo que o `PATCH` espera em `If-Match`."""
    async with request.app.state.sessoes() as sessao:
        detalhe = await detalhar_unidade(
            id, unidades=request.app.state.repositorio_de_unidades(sessao)
        )
    response.headers["ETag"] = f'"{detalhe.unidade.version}"'
    return UnidadeDetalheOut.do_detalhe(detalhe)


@router.post(
    "/unidades",
    status_code=201,
    summary="Cadastrar unidade de saúde",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `unidade:create` na área técnica do tipo informado"),
        409: problema("Já existe unidade com o mesmo CNES ou o mesmo nome no distrito"),
        422: problema("Campos inválidos, ou tipo de unidade ou distrito inexistente"),
    },
)
async def criar(
    request: Request,
    response: Response,
    corpo: UnidadeCreate,
    usuario: Annotated[UsuarioAtual, Depends(require("unidade:create"))],
    sessao: SessaoDeNegocio,
) -> UnidadeOut:
    """006/R1. Responde com a unidade criada, o `Location` dela e o `ETag` da versão."""
    estado = request.app.state
    unidade = await criar_unidade(
        corpo.dados(),
        novo_id=uuid7(),
        usuario=usuario,
        ator=ator_da_requisicao(request, usuario),
        unidades=estado.repositorio_de_unidades(sessao),
        auditoria=estado.auditoria(sessao),
    )
    response.headers["Location"] = f"/api/v1/unidades/{unidade.id}"
    response.headers["ETag"] = f'"{unidade.version}"'
    return UnidadeOut.de(unidade)


@router.patch(
    "/unidades/{id}",
    summary="Atualizar unidade de saúde",
    responses={
        401: problema("Sem access token válido"),
        403: problema(
            "Sem `unidade:update` no escopo da unidade, ou alteração de distrito, tipo ou CNES "
            "sem escopo global ou na área técnica (os campos vêm em `campos`)"
        ),
        404: problema("A unidade não existe"),
        409: problema("Já existe unidade com o mesmo CNES ou o mesmo nome no distrito"),
        412: problema("A unidade mudou depois da versão informada em `If-Match`"),
        422: problema("Campos inválidos, ou tipo de unidade ou distrito inexistente"),
        428: problema("Falta o cabeçalho `If-Match`"),
    },
)
async def atualizar(
    request: Request,
    response: Response,
    id: UUID,
    corpo: UnidadeUpdate,
    usuario: Annotated[UsuarioAtual, Depends(require("unidade:update", ResourceRef("unidade")))],
    sessao: SessaoDeNegocio,
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            description='A versão em mãos, como veio no `ETag` (ex.: `"3"`). Sem ele, 428.',
        ),
    ] = None,
) -> UnidadeOut:
    """006/R3, 011/R8.3. Aplica só os campos enviados e responde com a unidade e o `ETag` da
    versão nova, que o banco incrementa. Sem mudança, responde igual, sem alterar nem auditar."""
    estado = request.app.state
    unidade = await atualizar_unidade(
        id,
        corpo.alteracoes(),
        versao_esperada=_versao_esperada(if_match),
        usuario=usuario,
        ator=ator_da_requisicao(request, usuario),
        unidades=estado.repositorio_de_unidades(sessao),
        auditoria=estado.auditoria(sessao),
    )
    response.headers["ETag"] = f'"{unidade.version}"'
    return UnidadeOut.de(unidade)


def _versao_esperada(if_match: str | None) -> int:
    """A versão do `If-Match` (006/R3.2). Sem o cabeçalho, 428; com um valor que não é o `ETag`
    de uma versão (`*`, lista, `W/`), 412: ele não casa com a versão atual."""
    if if_match is None:
        raise PreconditionRequired("Envie If-Match com o ETag da versão que você leu.")
    casou = _ETAG.fullmatch(if_match.strip())
    if casou is None:
        raise PreconditionFailed("If-Match não corresponde a uma versão da unidade.")
    return int(casou.group(1))


@router.post(
    "/unidades/{id}/desativar",
    summary="Desativar unidade de saúde",
    responses={
        401: problema("Sem access token válido"),
        403: problema("Sem `unidade:deactivate` no escopo da unidade"),
        404: problema("A unidade não existe"),
        422: problema("Motivo ausente ou inválido"),
    },
)
async def desativar(
    request: Request,
    response: Response,
    id: UUID,
    corpo: UnidadeDesativacao,
    usuario: Annotated[
        UsuarioAtual, Depends(require("unidade:deactivate", ResourceRef("unidade")))
    ],
    sessao: SessaoDeNegocio,
) -> UnidadeOut:
    """006/R4, 011/R6.1 a R6.4. Responde com a unidade inativa e o `ETag` da versão. Já inativa,
    responde igual, sem alterar nada nem auditar."""
    estado = request.app.state
    unidade = await desativar_unidade(
        id,
        motivo=corpo.motivo,
        ator=ator_da_requisicao(request, usuario),
        unidades=estado.repositorio_de_unidades(sessao),
        auditoria=estado.auditoria(sessao),
    )
    response.headers["ETag"] = f'"{unidade.version}"'
    return UnidadeOut.de(unidade)
