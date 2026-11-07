"""Verificação de acesso de uma requisição (spec 003, design § Verificação; R4.2, R4.3 e R4.6).

A dependência `require()` (access.api.deps) chama `verificar` com as permissões efetivas do
usuário e, se ele for barrado, `auditar_negacao` numa transação própria: o 403 desfaz a
requisição, mas não o registro da negação.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.core.errors import Forbidden, NotFound
from src.modules.access.application.permissoes import ResolvedorDePermissoes
from src.modules.access.domain import authorization
from src.modules.access.domain.authorization import Alvo, EscopoLeitura, PermissoesEfetivas, pode
from src.modules.access.domain.ports import RepositorioDePermissoes, ResolvedorDeAlvo
from src.modules.audit.application.registrar import Ator, AuditStore, Entidade, registrar

# Tamanho de `audit_log.entity_id`: o id vem do caminho, sem validação, e não pode derrubar o
# registro da negação.
_ID_AUDITADO_MAX = 100

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "AcessoNegado",
    "Alvo",
    "Ator",
    "AuditStore",
    "EscopoLeitura",
    "Recurso",
    "RepositorioDePermissoes",
    "ResolvedorDeAlvo",
    "ResolvedorDePermissoes",
    "UsuarioAtual",
    "auditar_negacao",
    "escopo_de_leitura",
    "exigir_no_escopo",
    "verificar",
]


@dataclass(frozen=True)
class UsuarioAtual:
    """O usuário autenticado e autorizado da requisição, com as permissões efetivas dele."""

    id: UUID
    sessao_id: UUID
    permissoes: PermissoesEfetivas


@dataclass(frozen=True)
class Recurso:
    """O recurso pedido na rota: o tipo (`unidade`) e o id, em texto, como veio no caminho."""

    tipo: str
    id: str


class AcessoNegado(Forbidden):
    """403 (R4.2, R4.3). Leva a permissão exigida e o recurso para a auditoria (R4.6).

    `auditada` diz se o `acesso.negado` já foi gravado, para quem o grava não repetir.
    """

    def __init__(self, permissao: str, recurso: Recurso | None = None) -> None:
        super().__init__("Você não tem permissão para esta ação.")
        self.permissao = permissao
        self.recurso = recurso
        self.auditada = False


async def verificar(
    resolvedor: ResolvedorDePermissoes,
    repositorio: RepositorioDePermissoes,
    *,
    usuario_id: UUID,
    sessao_id: UUID,
    permissao: str,
    recurso: Recurso | None = None,
    alvos: ResolvedorDeAlvo | None = None,
) -> UsuarioAtual:
    """Levanta `AcessoNegado` se o usuário não tem `permissao` em escopo nenhum (R4.2) ou, havendo
    recurso, se nenhum escopo dele cobre o recurso (R4.3). Recurso que não existe dá 404, mas só
    a quem tem a permissão em algum escopo: aos demais, o 403 não diz se ele existe."""
    permissoes = await resolvedor.permissoes_de(repositorio, usuario_id)
    if not pode(permissoes, permissao):
        raise AcessoNegado(permissao, recurso)
    if recurso is not None:
        if alvos is None:
            raise TypeError("informe o resolvedor do tipo do recurso")
        alvo = await alvos.alvo(recurso.id)
        if alvo is None:
            raise NotFound("O recurso pedido não existe.")
        if not pode(permissoes, permissao, alvo):
            raise AcessoNegado(permissao, recurso)
    return UsuarioAtual(id=usuario_id, sessao_id=sessao_id, permissoes=permissoes)


def exigir_no_escopo(usuario: UsuarioAtual, permissao: str, alvo: Alvo) -> None:
    """Levanta `AcessoNegado` se nenhum escopo de `permissao` do usuário cobre `alvo` (R4.3).

    Para o caso de uso que só conhece os atributos de escopo depois de ler o corpo ou o banco,
    como a unidade nova, que fica na área técnica do tipo informado (006/R1.1). A negação sai sem
    recurso (`entity_type` nulo na auditoria) e é auditada pela `SessaoDeNegocio` da camada api.
    """
    if not pode(usuario.permissoes, permissao, alvo):
        raise AcessoNegado(permissao)


def escopo_de_leitura(usuario: UsuarioAtual, permissao: str) -> EscopoLeitura:
    """Até onde a listagem vai para `usuario` com `permissao` (R4.4; design § Verificação).

    Para o SQL escrito à mão (ADR-0009), os parâmetros do fragmento fixo saem de
    `src.core.escopo.parametros_de_escopo`; para o SQLAlchemy Core, de `scope_filter`.
    """
    return authorization.escopo_de_leitura(usuario.permissoes, permissao)


async def auditar_negacao(
    store: AuditStore, negacao: AcessoNegado, *, ator: Ator, rota: str
) -> None:
    """Grava `acesso.negado` com a permissão, a rota e o recurso, se houver (R4.6)."""
    recurso = negacao.recurso
    metadados: Mapping[str, Any] = {"permissao": negacao.permissao, "rota": rota}
    await registrar(
        store,
        acao="acesso.negado",
        ator=ator,
        entidade=(
            None
            if recurso is None
            else Entidade(tipo=recurso.tipo, id=recurso.id[:_ID_AUDITADO_MAX])
        ),
        metadados=metadados,
    )
