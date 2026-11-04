"""Entidade UnidadeSaude (Etapa 02 - Banco de Dados)."""

import re
from dataclasses import dataclass
from datetime import datetime

from src.core.errors import DomainValidationError, FieldError

CNES_REGEX = re.compile(r"^[0-9]{7}$")
CEP_REGEX = re.compile(r"^[0-9]{8}$")
TELEFONE_REGEX = re.compile(r"^\(?[0-9]{2,3}\)?[ \t]?[0-9]{4,5}-?[0-9]{4}$")

TIPOS_UNIDADE_VALIDOS = frozenset(
    {"UBS", "UPA", "Hospital", "Laboratório", "Posto de Saúde", "Centro de Saúde"}
)

STATUS_UNIDADE_VALIDOS = frozenset({"Ativa", "Inativa", "Em reforma", "Suspensa"})


@dataclass(frozen=True)
class UnidadeSaude:
    codigo_cnes: str
    nome: str
    tipo: str
    endereco: str
    cep: str
    distrito_sanitario: str
    status: str
    telefone: str | None = None
    data_criacao: datetime | None = None
    data_atualizacao: datetime | None = None
    id_unidade: int | None = None

    def __post_init__(self) -> None:
        errors: list[FieldError] = []

        if not self.codigo_cnes or not CNES_REGEX.fullmatch(self.codigo_cnes):
            errors.append(
                FieldError(
                    campo="codigo_cnes",
                    mensagem="Código CNES deve conter exatamente 7 dígitos numéricos.",
                )
            )

        if not self.nome or not self.nome.strip():
            errors.append(FieldError(campo="nome", mensagem="Nome da unidade não pode ser vazio."))

        if self.tipo not in TIPOS_UNIDADE_VALIDOS:
            permitidos = ", ".join(sorted(TIPOS_UNIDADE_VALIDOS))
            errors.append(
                FieldError(
                    campo="tipo",
                    mensagem=f"Tipo de unidade inválido. Permitidos: {permitidos}.",
                )
            )

        if not self.endereco or not self.endereco.strip():
            errors.append(FieldError(campo="endereco", mensagem="Endereço não pode ser vazio."))

        if not self.cep or not CEP_REGEX.fullmatch(self.cep):
            errors.append(
                FieldError(campo="cep", mensagem="CEP deve conter exatamente 8 dígitos numéricos.")
            )

        if not self.distrito_sanitario or not self.distrito_sanitario.strip():
            errors.append(
                FieldError(
                    campo="distrito_sanitario",
                    mensagem="Distrito sanitário não pode ser vazio.",
                )
            )

        if self.telefone is not None and not TELEFONE_REGEX.fullmatch(self.telefone):
            errors.append(
                FieldError(
                    campo="telefone",
                    mensagem="Formato de telefone inválido.",
                )
            )

        if self.status not in STATUS_UNIDADE_VALIDOS:
            errors.append(
                FieldError(
                    campo="status",
                    mensagem=f"Status inválido. Permitidos: {sorted(STATUS_UNIDADE_VALIDOS)}.",
                )
            )

        if (
            self.data_criacao is not None
            and self.data_atualizacao is not None
            and self.data_atualizacao < self.data_criacao
        ):
            errors.append(
                FieldError(
                    campo="data_atualizacao",
                    mensagem="Data de atualização não pode ser anterior à data de criação.",
                )
            )

        if errors:
            raise DomainValidationError("Dados de unidade de saúde inválidos.", errors=errors)
