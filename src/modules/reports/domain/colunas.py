"""Colunas dos relatórios e neutralização de fórmulas (spec 005, R1.2, R4.2, R4.3; design
§ Conteúdo)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class TipoColuna(StrEnum):
    """Decide como o gerador formata a célula: só texto passa pela neutralização (R4.2)."""

    TEXTO = "texto"
    NUMERO = "numero"
    DATA = "data"


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: TipoColuna = TipoColuna.TEXTO


# OWASP, CSV injection: o Excel e o LibreOffice leem como fórmula a célula que começa por um
# destes caracteres. A tabulação e o `\r` entram porque alguns leitores os descartam antes de
# olhar o primeiro caractere de verdade.
PREFIXOS_DE_FORMULA: Final = ("=", "+", "-", "@", "\t", "\r")


def neutralizar(texto: str) -> str:
    """R4.2: põe um `'` na frente do texto que uma planilha leria como fórmula."""
    return "'" + texto if texto.startswith(PREFIXOS_DE_FORMULA) else texto


# Colunas da `vw_unit_inventory` (011/R4.1), sem `unit_id` e sem os ids de escopo. A view não
# tem dado pessoal (011/R4.2). O CNES é texto: tem zeros à esquerda.
COLUNAS_INVENTARIO_UNIDADES: Final = (
    Coluna("CNES"),
    Coluna("Nome"),
    Coluna("Tipo"),
    Coluna("Área técnica"),
    Coluna("Distrito"),
    Coluna("Status"),
    Coluna("Situação cadastral"),
    Coluna("Equipamentos", TipoColuna.NUMERO),
    Coluna("Serviços", TipoColuna.NUMERO),
    Coluna("Serviços fora do CNES", TipoColuna.NUMERO),
)

# R4.3: a trilha exportada não traz `metadata`, IP, User-Agent nem sessão. As mudanças saem como
# gravadas, com os valores pessoais já em `***`.
COLUNAS_TRILHA_AUDITORIA: Final = (
    Coluna("Instante", TipoColuna.DATA),
    Coluna("Ação"),
    Coluna("Tipo de ator"),
    Coluna("Autor"),
    Coluna("Papéis"),
    Coluna("Entidade"),
    Coluna("Id da entidade"),
    Coluna("Resultado"),
    Coluna("Mudanças"),
)

COLUNAS_POR_TIPO: Final[dict[str, tuple[Coluna, ...]]] = {
    "inventario_unidades": COLUNAS_INVENTARIO_UNIDADES,
    "trilha_auditoria": COLUNAS_TRILHA_AUDITORIA,
}
