"""Itens das tabelas de referência do cadastro (spec 006, R7; spec 011, R9.2).

Distritos, áreas técnicas e tipos de unidade, equipamento e serviço: código, nome e exclusão
lógica (`ativo`, decisão U5 da 011). O tipo de unidade aponta também a área técnica, que é o
escopo do Coordenador Técnico (003).
"""

from dataclasses import dataclass
from enum import StrEnum


class TipoDeReferencia(StrEnum):
    """Qual tabela de referência. O valor é o `entity_type` da auditoria."""

    DISTRITO = "distrito"
    AREA_TECNICA = "area_tecnica"
    TIPO_UNIDADE = "tipo_unidade"
    TIPO_EQUIPAMENTO = "tipo_equipamento"
    TIPO_SERVICO = "tipo_servico"


@dataclass(frozen=True, slots=True)
class DadosDaReferencia:
    """Item novo. `area_tecnica_id` só existe (e é obrigatório) no tipo de unidade."""

    codigo: str
    nome: str
    area_tecnica_id: int | None = None


@dataclass(frozen=True, slots=True)
class Referencia:
    id: int
    codigo: str
    nome: str
    ativo: bool
    area_tecnica_id: int | None = None

    def campos(self, tipo: TipoDeReferencia) -> dict[str, object]:
        """Os campos editáveis, com os nomes da API (os da auditoria, design da 011 § Fluxos)."""
        campos: dict[str, object] = {"codigo": self.codigo, "nome": self.nome, "ativo": self.ativo}
        if tipo is TipoDeReferencia.TIPO_UNIDADE:
            campos["area_tecnica_id"] = self.area_tecnica_id
        return campos


@dataclass(frozen=True, slots=True)
class Alteracao:
    """Um item como estava e como ficou depois do UPDATE."""

    antes: Referencia
    depois: Referencia


class CodigoRepetidoError(Exception):
    """O código pedido já é de outro item da mesma tabela (índice único)."""
