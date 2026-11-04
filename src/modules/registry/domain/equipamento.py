"""Entidade Equipamento (Etapa 02 - Banco de Dados)."""

from dataclasses import dataclass

from src.core.errors import DomainValidationError, FieldError

TIPOS_EQUIPAMENTO_VALIDOS = frozenset(
    {
        "Monitor de sinais vitais",
        "Respirador",
        "Tomógrafo",
        "Ultrassom",
        "Balança",
        "Aparelho de RX",
        "Cadeira de rodas",
        "Desfibrilador",
        "Fitas de esterilização",
        "Estetoscópio",
    }
)


@dataclass(frozen=True)
class Equipamento:
    nome: str
    tipo: str
    quantidade: int
    id_unidade: int | None
    id_equipamento: int | None = None

    def __post_init__(self) -> None:
        errors: list[FieldError] = []

        if not self.nome or not self.nome.strip():
            errors.append(
                FieldError(campo="nome", mensagem="Nome do equipamento não pode ser vazio.")
            )

        if self.tipo not in TIPOS_EQUIPAMENTO_VALIDOS:
            permitidos = ", ".join(sorted(TIPOS_EQUIPAMENTO_VALIDOS))
            errors.append(
                FieldError(
                    campo="tipo",
                    mensagem=f"Tipo de equipamento inválido. Permitidos: {permitidos}.",
                )
            )

        if self.quantidade < 0 or self.quantidade > 5000:
            errors.append(
                FieldError(
                    campo="quantidade",
                    mensagem="Quantidade deve ser um número inteiro entre 0 e 5000.",
                )
            )

        if errors:
            raise DomainValidationError("Dados de equipamento inválidos.", errors=errors)
