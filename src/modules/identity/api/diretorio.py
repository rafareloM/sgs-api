"""Rotas do diretório para o Admin TI (spec 004, T4; design § Rotas).

- `POST /admin/diretorio/sincronizar` grava a execução numa transação própria, confirmada antes
  da resposta, e agenda a sincronização em segundo plano (R1.1, R1.11).
- `GET /admin/diretorio/execucoes` e `/{id}`: o histórico das execuções (R1.9, R1.10, R4.2).
- `GET /admin/diretorio/grupos`: os grupos espelhados, para o mapeamento da 003 (R1.14).
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import BaseModel

from src.core.errors import Conflict, ServiceUnavailable
from src.core.ids import uuid7
from src.core.paginacao import TAMANHO_PADRAO, NumeroDaPagina, PaginaOut, TamanhoDaPagina
from src.core.problem import PROBLEM_JSON
from src.modules.access.api.deps import (
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.identity.api.sincronizacao import transacoes_da_sincronizacao
from src.modules.identity.application import diretorio as consultas
from src.modules.identity.application.sincronizacao import iniciar_sincronizacao, sincronizar
from src.modules.identity.domain.espelho_diretorio import GroupListing, SyncRun

router = APIRouter(prefix="/api/v1/admin/diretorio", tags=["diretório"])


def _problema(descricao: str) -> dict[str, Any]:
    return {"description": descricao, "content": {PROBLEM_JSON: {}}}


_401 = _problema("Sem access token válido")
QuemSincroniza = Annotated[UsuarioAtual, Depends(require("diretorio:sync"))]
QuemMapeia = Annotated[UsuarioAtual, Depends(require("papel:assign"))]


class ExecucaoIniciadaOut(BaseModel):
    execucao_id: UUID
    status: Literal["em_andamento"] = "em_andamento"


class ContagensOut(BaseModel):
    criados: int
    atualizados: int
    desativados: int


class ConflitoOut(BaseModel):
    """Sem e-mail nem nome: o Admin TI chega à conta pelo id (LGPD)."""

    tipo: Literal["email", "username"]
    external_id: str
    usuario_existente_id: UUID | None


class ExecucaoOut(BaseModel):
    id: UUID
    tipo: Literal["ldap"]
    status: Literal["em_andamento", "concluida", "falhou"]
    iniciada_em: datetime
    concluida_em: datetime | None
    disparada_por: UUID | None
    usuarios: ContagensOut
    grupos: ContagensOut
    conflitos: list[ConflitoOut]
    erro: str | None

    @classmethod
    def de(cls, e: SyncRun) -> Self:
        c = e.counts
        return cls(
            id=e.id,
            tipo=e.kind,
            status=e.status,
            iniciada_em=e.started_at,
            concluida_em=e.finished_at,
            disparada_por=e.triggered_by,
            usuarios=ContagensOut(
                criados=c.users_created,
                atualizados=c.users_updated,
                desativados=c.users_deactivated,
            ),
            grupos=ContagensOut(
                criados=c.groups_created,
                atualizados=c.groups_updated,
                desativados=c.groups_deactivated,
            ),
            conflitos=[
                ConflitoOut(
                    tipo=x.tipo,
                    external_id=x.external_id,
                    usuario_existente_id=x.usuario_existente_id,
                )
                for x in e.conflicts
            ],
            erro=e.error,
        )


class GrupoOut(BaseModel):
    id: UUID
    origem: Literal["ldap", "oidc"]
    nome: str
    membros_ativos: int
    ativo: bool

    @classmethod
    def de(cls, g: GroupListing) -> Self:
        return cls(
            id=g.id,
            origem=g.source,
            nome=g.name,
            membros_ativos=g.active_members,
            ativo=g.is_active,
        )


def _agora() -> datetime:
    return datetime.now(UTC)


@router.post(
    "/sincronizar",
    status_code=202,
    summary="Disparar a sincronização do diretório LDAP",
    responses={
        401: _401,
        403: _problema("Sem `diretorio:sync`"),
        409: _problema("Já há uma sincronização em andamento"),
        503: _problema("LDAP não configurado"),
    },
)
async def disparar(
    request: Request,
    tarefas: BackgroundTasks,
    usuario: QuemSincroniza,
    _sessao: SessaoDeNegocio,  # só para o 409 virar `operacao.falhou` (013/R4.3)
) -> ExecucaoIniciadaOut:
    """R1.1, R1.11: 202 com o id; a execução segue em segundo plano e é consultada nas
    execuções. Audita `diretorio.sincronizado` ao terminar, com quem disparou como ator."""
    estado = request.app.state
    porta = estado.diretorio
    if porta is None:
        raise ServiceUnavailable("Sincronização do diretório não configurada.")
    transacoes = transacoes_da_sincronizacao(estado)
    execucao_id = uuid7()
    # Transação própria, confirmada antes da resposta: a tarefa em segundo plano acha a linha.
    if not await iniciar_sincronizacao(
        execucao_id, triggered_by=usuario.id, transacoes=transacoes, agora=_agora
    ):
        raise Conflict("Já há uma sincronização do diretório em andamento.")
    tarefas.add_task(
        sincronizar,
        execucao_id,
        diretorio=porta,
        transacoes=transacoes,
        ator=ator_da_requisicao(request, usuario),
        gerar_id=estado.gerar_id,
        agora=_agora,
    )
    return ExecucaoIniciadaOut(execucao_id=execucao_id)


@router.get(
    "/execucoes",
    summary="Execuções da sincronização",
    responses={401: _401, 403: _problema("Sem `diretorio:sync`")},
)
async def execucoes(
    request: Request,
    usuario: QuemSincroniza,
    sessao: SessaoDeNegocio,
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[ExecucaoOut]:
    """R1.9: da mais recente para a mais antiga."""
    resultado = await consultas.listar_execucoes(
        limite=tamanho,
        deslocamento=(pagina - 1) * tamanho,
        repositorio=request.app.state.repositorio_do_diretorio(sessao),
    )
    return PaginaOut(
        itens=[ExecucaoOut.de(e) for e in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get(
    "/execucoes/{id_}",
    summary="Uma execução da sincronização",
    responses={
        401: _401,
        403: _problema("Sem `diretorio:sync`"),
        404: _problema("Execução inexistente"),
    },
)
async def execucao(
    request: Request, id_: UUID, usuario: QuemSincroniza, sessao: SessaoDeNegocio
) -> ExecucaoOut:
    """R1.9, R1.10, R4.2: contagens, conflitos e o erro genérico."""
    return ExecucaoOut.de(
        await consultas.obter_execucao(
            id_, repositorio=request.app.state.repositorio_do_diretorio(sessao)
        )
    )


@router.get(
    "/grupos",
    summary="Grupos espelhados do diretório",
    responses={401: _401, 403: _problema("Sem `papel:assign`")},
)
async def grupos(
    request: Request,
    usuario: QuemMapeia,
    sessao: SessaoDeNegocio,
    origem: Literal["ldap", "oidc"] | None = None,
    ativo: bool = True,
    busca: Annotated[
        str | None, Query(min_length=1, max_length=100, description="Trecho do nome.")
    ] = None,
    pagina: NumeroDaPagina = 1,
    tamanho: TamanhoDaPagina = TAMANHO_PADRAO,
) -> PaginaOut[GrupoOut]:
    """R1.14: id, origem, nome e membros com conta ativa, para o mapeamento da 003 (R3.1)."""
    resultado = await consultas.listar_grupos(
        origem=origem,
        ativo=ativo,
        busca=busca,
        limite=tamanho,
        deslocamento=(pagina - 1) * tamanho,
        repositorio=request.app.state.repositorio_do_diretorio(sessao),
    )
    return PaginaOut(
        itens=[GrupoOut.de(g) for g in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )
