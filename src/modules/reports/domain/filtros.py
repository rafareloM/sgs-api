"""Tipos, formatos e filtros dos relatórios (spec 005, design § Rotas; R1.2, R1.5).

Os modelos conferem os filtros antes de o pedido ser gravado: a rota os usa no corpo e responde
422 com o campo (R1.5); o pedido guarda `model_dump(mode="json")` em `filters` (JSONB), e a
geração os lê de volta com `model_validate`. Ids que não existem no banco também dão 422, mas
isso a rota confere, porque depende do banco.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationInfo,
    field_validator,
)

TipoDeRelatorio = Literal["inventario_unidades", "trilha_auditoria"]
FormatoDeRelatorio = Literal["csv", "xlsx"]

PERIODO_MAXIMO_DA_TRILHA = timedelta(days=366)
"""R1.5: período máximo da trilha, de `de` (incluído) a `ate` (excluído)."""

_DATA_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
"""Começo de uma data e hora ISO 8601. Sem esta conferência, o Pydantic leria número, ou texto só
com número, como instante Unix (`0` é 1970-01-01), e o relatório sairia de outro período."""

_IdDeReferencia = Annotated[StrictInt, Field(ge=1, le=32767)]
"""Ids de distrito, área técnica e tipo de unidade: `smallint` no banco, como no cadastro.
Estrito: texto, booleano e decimal do JSON dão 422 em vez de virar outro id."""

StatusDaUnidade = Literal["ativa", "inativa", "em_implantacao"]
"""Os mesmos valores do cadastro (`registry/api/schemas.py`) e do `CHECK` de `health_units`."""

_PREFIXO_DE_ACAO = r"^[a-z][a-z0-9_.]*$"
"""Começo de um nome de ação (`audit/domain/entry.py`, `recurso.verbo`), sem o curinga `%`. O
`_` é válido em nome de ação e também é curinga do `LIKE`: a consulta da 005/T11 tem de
escapá-lo."""

_CONFIG = ConfigDict(frozen=True, extra="forbid")
# extra="forbid": um filtro que a API não conhece seria ignorado e o relatório sairia maior que
# o pedido; vira 422.


class FiltrosDoInventario(BaseModel):
    """Filtros de `inventario_unidades` (`vw_unit_inventory`), todos opcionais."""

    model_config = _CONFIG

    distrito_id: _IdDeReferencia | None = None
    area_tecnica_id: _IdDeReferencia | None = None
    tipo_unidade_id: _IdDeReferencia | None = None
    status: StatusDaUnidade | None = None


class FiltrosDaTrilha(BaseModel):
    """Filtros de `trilha_auditoria`: período obrigatório de até 366 dias (R1.5), prefixo da
    ação e tipo de entidade.

    - `de` incluído e `ate` excluído, como as consultas da auditoria (`occurred_at < :ate`).
    - Data e hora com fuso: sem ele, o instante dependeria do fuso da sessão do banco.
    """

    model_config = _CONFIG

    de: AwareDatetime
    ate: AwareDatetime
    acao: Annotated[
        str | None, Field(max_length=50, pattern=_PREFIXO_DE_ACAO, description="Prefixo da ação.")
    ] = None
    entidade_tipo: Annotated[str | None, Field(min_length=1, max_length=50)] = None

    @field_validator("de", "ate", mode="before")
    @classmethod
    def _iso_8601(cls, valor: object) -> object:
        """Só data e hora (o JSON traz texto ISO 8601), nada convertido, como nos ids."""
        if isinstance(valor, datetime) or (isinstance(valor, str) and _DATA_ISO.match(valor)):
            return valor
        raise ValueError("Use data e hora ISO 8601, com fuso.")

    @field_validator("de", "ate")
    @classmethod
    def _cabe_em_utc(cls, instante: AwareDatetime) -> AwareDatetime:
        """O banco guarda em UTC; um instante que sai do calendário ao ir para UTC (ano 1 com
        +14:00, ano 9999 com -14:00) falharia só na geração, em segundo plano."""
        try:
            instante.astimezone(UTC)
        except OverflowError:
            raise ValueError("Data fora do intervalo aceito.") from None
        return instante

    @field_validator("ate")
    @classmethod
    def _periodo(cls, ate: AwareDatetime, info: ValidationInfo) -> AwareDatetime:
        de = info.data.get("de")
        if de is None:  # `de` já foi recusado; o erro dele basta
            return ate
        # Em UTC: com o mesmo `tzinfo` nos dois lados, o Python subtrai e compara o horário de
        # relógio, e um fuso com horário de verão erraria o período em uma hora.
        periodo = ate.astimezone(UTC) - de.astimezone(UTC)
        if periodo <= timedelta(0):
            raise ValueError("A data final deve ser posterior à inicial.")
        if periodo > PERIODO_MAXIMO_DA_TRILHA:
            raise ValueError("O período deve ter no máximo 366 dias.")
        return ate


Filtros = FiltrosDoInventario | FiltrosDaTrilha

MODELO_DOS_FILTROS: Mapping[TipoDeRelatorio, type[Filtros]] = {
    "inventario_unidades": FiltrosDoInventario,
    "trilha_auditoria": FiltrosDaTrilha,
}
"""R1.2: o modelo de filtros de cada tipo de relatório."""
