"""Escopo de leitura no SQL das listagens (spec 003, design § Verificação; R4.4).

O `EscopoLeitura` sai do módulo de acesso (`access.application.autorizacao.escopo_de_leitura`)
e chega aos repositórios, que montam a consulta. Fica aqui, e não no `access`, porque é a
`infrastructure` dos módulos que consulta, e ela só importa o próprio domínio, o `core` e
bibliotecas (contratos do import-linter no pyproject.toml).

Duas formas, para as duas maneiras de escrever SQL do projeto (ADR-0009):
- `scope_filter(escopo, model)`: expressão do SQLAlchemy Core para o `.where()`;
- `parametros_de_escopo(escopo)`: parâmetros do fragmento fixo das consultas escritas à mão
  (design da 011 § Escopo em SQL explícito):

      (:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))
       OR district_id = ANY(CAST(:scope_districts AS smallint[]))
       OR unit_id = ANY(CAST(:scope_units AS uuid[])))

Nos dois casos a tabela ou view filtrada expõe `unit_id`, `district_id` e `technical_area_id`,
como as views da 011, e nenhum valor entra no texto do SQL.
"""

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, FromClause, false, or_, true


class EscopoDeLeitura(Protocol):
    """O que se lê de `access.domain.authorization.EscopoLeitura`."""

    @property
    def global_(self) -> bool: ...

    @property
    def areas(self) -> Sequence[int]: ...

    @property
    def distritos(self) -> Sequence[int]: ...

    @property
    def unidades(self) -> Sequence[UUID]: ...


COLUNAS_DE_ESCOPO = ("unit_id", "district_id", "technical_area_id")


def scope_filter(escopo: EscopoDeLeitura, model: FromClause) -> ColumnElement[bool]:
    """Condição que deixa passar só as linhas de `model` dentro do escopo (`or_(...)`)."""
    faltando = [nome for nome in COLUNAS_DE_ESCOPO if nome not in model.c]
    if faltando:
        raise ValueError(f"{model} não expõe as colunas de escopo {faltando}")
    if escopo.global_:
        return true()
    condicoes = [
        coluna.in_(ids)
        for coluna, ids in (
            (model.c.technical_area_id, escopo.areas),
            (model.c.district_id, escopo.distritos),
            (model.c.unit_id, escopo.unidades),
        )
        if ids
    ]
    return or_(false(), *condicoes)


def parametros_de_escopo(escopo: EscopoDeLeitura) -> dict[str, Any]:
    """Valores dos parâmetros `:scope_*` do fragmento fixo. Listas, que o asyncpg manda como
    arrays."""
    return {
        "scope_global": escopo.global_,
        "scope_areas": list(escopo.areas),
        "scope_districts": list(escopo.distritos),
        "scope_units": list(escopo.unidades),
    }
