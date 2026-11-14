"""Schemas de saída da auditoria: histórico da unidade (design da 011 § Rotas; 008/R1.2) e log
do banco (011/R6.9, R7.7).

Lidos dos valores do domínio (`model_validate` com `from_attributes`), nunca de linhas do banco.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue


class MudancaOut(BaseModel):
    """Um campo alterado, com o valor de antes (`de`) e o de depois (`para`)."""

    model_config = ConfigDict(from_attributes=True)

    campo: str
    de: Any
    para: Any


class EventoHistoricoOut(BaseModel):
    """Um evento da unidade (ou de um equipamento ou serviço dela): data e hora, autor com os
    papéis no momento, ação e a lista {campo, de, para} (008/R1.2, 011/R4.4). Sem autor (tarefa
    do sistema), `autor_id` e `autor_nome` vêm nulos."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ocorrido_em: datetime
    acao: str
    autor_id: UUID | None
    autor_nome: str | None
    autor_papeis: list[str]
    mudancas: list[MudancaOut]
    metadados: dict[str, Any]


class DeParaOut(BaseModel):
    """Valor de uma coluna antes (`de`) e depois (`para`) da alteração; nulo do lado que não
    existe (inclusão ou exclusão). O nome do gestor vem mascarado (`"***"`, 011/R7.3)."""

    de: JsonValue = None
    para: JsonValue = None


class AlteracaoBancoOut(BaseModel):
    """Um registro do log do banco (011/R7.1, R7.7). `via_api` falso é alteração feita fora da
    API, por outro usuário de banco ou por superusuário (011/R7.2)."""

    model_config = ConfigDict(from_attributes=True)

    ocorrido_em: datetime
    tabela: str
    operacao: str
    linha_id: UUID
    colunas_alteradas: dict[str, DeParaOut]
    usuario_banco: str
    via_api: bool


class ParticaoOut(BaseModel):
    """Uma partição do log do banco (011/R6.9): nome, intervalo (`de` incluído, `ate` excluído)
    e quantidade de registros. A DEFAULT, que recebe o que não cai em mês nenhum, vem com `de` e
    `ate` nulos."""

    model_config = ConfigDict(from_attributes=True)

    nome: str
    de: datetime | None
    ate: datetime | None
    registros: int
