"""O que equipamentos e serviços têm em comum como itens vinculados a uma unidade (spec 006, R5 e
R6; design § Diff e auditoria).

Os dois casos de uso diferem só no substantivo (`equipamento`, `servico`), nos nomes da API das
colunas e em como um valor vai para a trilha; `Vinculado` guarda isso e faz o resto do mesmo
jeito: a auditoria no nível da unidade, a procura do item na unidade da rota (404 se não é dela)
e os 403 e 422 comuns.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from src.core.errors import DomainValidationError, FieldError, NotFound
from src.modules.access.application.autorizacao import (
    AcessoNegado,
    UsuarioAtual,
    escopo_de_leitura,
)
from src.modules.audit.application.registrar import (
    Ator,
    AuditStore,
    Entidade,
    Mudanca,
    registrar,
)

NAO_EXISTE = "O recurso pedido não existe."


class _Item(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def unit_id(self) -> UUID | None: ...


def _o_mesmo(valor: object) -> object:
    return valor


@dataclass(frozen=True)
class Vinculado:
    """`substantivo` dá a ação (`unidade.<substantivo>_<evento>`), o prefixo dos campos
    (`<substantivo>.nome`) e a chave do id nos metadados (`<substantivo>_id`); `campo_da_api` leva
    a coluna ao nome da API; `para_json`, o valor ao que a trilha (JSONB) guarda."""

    substantivo: str
    campo_da_api: Mapping[str, str]
    para_json: Callable[[object], object] = _o_mesmo

    def com_nomes_da_api(self, mudancas: list[Mudanca], prefixo: str = "") -> list[Mudanca]:
        return [
            Mudanca(
                campo=prefixo + self.campo_da_api[m.campo],
                de=self.para_json(m.de),
                para=self.para_json(m.para),
            )
            for m in mudancas
        ]

    async def auditar_na_unidade(
        self,
        auditoria: AuditStore,
        evento: str,
        ator: Ator,
        item: _Item,
        mudancas: list[Mudanca],
    ) -> None:
        """`unidade.<substantivo>_<evento>` no nível da unidade, com o id do item nos metadados
        (006/R5.3)."""
        await registrar(
            auditoria,
            acao=f"unidade.{self.substantivo}_{evento}",
            ator=ator,
            entidade=Entidade(tipo="unidade", id=str(item.unit_id)),
            mudancas=self.com_nomes_da_api(mudancas, f"{self.substantivo}."),
            metadados={f"{self.substantivo}_id": str(item.id)},
        )

    async def auditar_sem_unidade(
        self, auditoria: AuditStore, ator: Ator, item: _Item, mudancas: list[Mudanca]
    ) -> None:
        """`<substantivo>.criado`, com o próprio item como entidade: não há unidade para levar o
        evento (006/R5.2, R6.2)."""
        await registrar(
            auditoria,
            acao=f"{self.substantivo}.criado",
            ator=ator,
            entidade=Entidade(tipo=self.substantivo, id=str(item.id)),
            mudancas=self.com_nomes_da_api(mudancas),
        )


async def da_unidade[T: _Item](
    ler: Callable[[UUID], Awaitable[T | None]], unidade_id: UUID, item_id: UUID
) -> T:
    """O item, se é da unidade da rota; senão, 404, como se não existisse."""
    item = await ler(item_id)
    if item is None or item.unit_id != unidade_id:
        raise NotFound(NAO_EXISTE)
    return item


def exigir_global(usuario: UsuarioAtual, permissao: str) -> None:
    """403 se o usuário não tem `permissao` global (006/R5.2, R6.2: só o Gestor de Dados)."""
    if not escopo_de_leitura(usuario, permissao).global_:
        raise AcessoNegado(permissao)


def invalido(campo: str, mensagem: str) -> DomainValidationError:
    """O 422 de um campo da API."""
    return DomainValidationError(
        "A requisição tem campos inválidos.",
        errors=[FieldError(campo=campo, mensagem=mensagem)],
    )
