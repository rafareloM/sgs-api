"""Log do banco: o que o PostgreSQL registra das alterações do cadastro (spec 011, R6.9 e R7).

O log é gravado pelo trigger `trg_registry_change_log` (011/T7), venha a alteração de onde vier,
e só é lido pela aplicação. Aqui ficam os valores que entram e saem da porta `LogDoBanco`, sem
banco nem HTTP. A página pedida e o resultado paginado são os do histórico da unidade.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

type TabelaDoCadastro = Literal["health_units", "equipments", "services"]
"""As tabelas do cadastro que o log registra (CHECK de `db_change_log.table_name`)."""


@dataclass(frozen=True, slots=True)
class FiltrosDoLog:
    """Filtros opcionais do log (011/R7.7), que se somam: período com as duas pontas incluídas
    (`de`, `ate`, com fuso), tabela do cadastro e origem (`fora_da_api` verdadeiro traz só o que
    não veio da API; falso, só o que veio; nulo, tudo)."""

    de: datetime | None = None
    ate: datetime | None = None
    tabela: TabelaDoCadastro | None = None
    fora_da_api: bool | None = None


@dataclass(frozen=True, slots=True)
class AlteracaoBanco:
    """Um registro do log: quando, em que tabela, qual operação, em que linha, as colunas
    alteradas (`{coluna: {"de": v, "para": v}}`), o usuário de banco e se veio da API."""

    ocorrido_em: datetime
    tabela: str
    operacao: str
    linha_id: UUID
    colunas_alteradas: Mapping[str, Any]
    usuario_banco: str
    via_api: bool


@dataclass(frozen=True, slots=True)
class ParticaoDoLog:
    """Uma partição do log: nome, intervalo (`de` incluído, `ate` excluído; nulos na DEFAULT) e
    quantidade de registros (011/R6.9)."""

    nome: str
    de: datetime | None
    ate: datetime | None
    registros: int
