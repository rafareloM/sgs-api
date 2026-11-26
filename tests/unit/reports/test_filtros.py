"""Filtros dos relatórios (005/T12; design § Rotas, `filtros`): modelos por tipo, conferidos
antes de gravar o pedido."""

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from src.modules.registry.api.schemas import StatusDaUnidade as StatusDoCadastro
from src.modules.reports.domain.filtros import (
    MODELO_DOS_FILTROS,
    PERIODO_MAXIMO_DA_TRILHA,
    FiltrosDaTrilha,
    FiltrosDoInventario,
    FormatoDeRelatorio,
    StatusDaUnidade,
    TipoDeRelatorio,
)

RECIFE = timezone(timedelta(hours=-3))
INICIO = datetime(2026, 1, 1, tzinfo=RECIFE)
UM_DIA = INICIO + timedelta(days=1)


class _FusoComHorarioDeVerao(tzinfo):
    """-04:00 de janeiro a junho e -05:00 de julho a dezembro, como um `ZoneInfo` com horário de
    verão, sem depender da base de fusos do sistema (`src/core/fuso.py`)."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-4 if dt is not None and dt.month <= 6 else -5)

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


VERAO = _FusoComHorarioDeVerao()


def _erros(exc: pytest.ExceptionInfo[ValidationError]) -> dict[tuple[Any, ...], str]:
    return {tuple(erro["loc"]): erro["type"] for erro in exc.value.errors()}


def _mensagem(exc: pytest.ExceptionInfo[ValidationError]) -> tuple[tuple[Any, ...], str]:
    [erro] = exc.value.errors()
    return tuple(erro["loc"]), str(erro["ctx"]["error"])


def test_tipos_e_formatos_oferecidos() -> None:
    """005/R1.2: os dois tipos, nos dois formatos, cada tipo com o seu modelo de filtros."""
    assert set(get_args(TipoDeRelatorio)) == {"inventario_unidades", "trilha_auditoria"}
    assert set(get_args(FormatoDeRelatorio)) == {"csv", "xlsx"}
    assert {
        "inventario_unidades": FiltrosDoInventario,
        "trilha_auditoria": FiltrosDaTrilha,
    } == MODELO_DOS_FILTROS


def test_inventario_sem_filtros_e_com_todos() -> None:
    """005/R1.2: no inventário, todos os filtros são opcionais."""
    assert FiltrosDoInventario.model_validate({}) == FiltrosDoInventario()

    filtros = FiltrosDoInventario.model_validate(
        {"distrito_id": 2, "area_tecnica_id": 1, "tipo_unidade_id": 7, "status": "ativa"}
    )

    assert (filtros.distrito_id, filtros.area_tecnica_id, filtros.tipo_unidade_id) == (2, 1, 7)
    assert filtros.status == "ativa"


@pytest.mark.parametrize(
    ("dados", "campo", "tipo"),
    [
        ({"distrito_id": 0}, "distrito_id", "greater_than_equal"),
        ({"area_tecnica_id": 32768}, "area_tecnica_id", "less_than_equal"),
        ({"tipo_unidade_id": "7"}, "tipo_unidade_id", "int_type"),
        ({"distrito_id": True}, "distrito_id", "int_type"),
        ({"area_tecnica_id": 2.0}, "area_tecnica_id", "int_type"),
        ({"status": "fechada"}, "status", "literal_error"),
        ({"unidade_id": 3}, "unidade_id", "extra_forbidden"),
    ],
)
def test_inventario_recusa_filtro_invalido(dados: dict[str, object], campo: str, tipo: str) -> None:
    """005/R1.5: id que não é inteiro do JSON (texto, booleano, decimal) ou fora da faixa de
    `smallint`, status desconhecido ou campo que não existe viram 422 (a rota mostra o campo).
    Nada é convertido nem ignorado: um filtro que não filtra como pedido daria outro
    relatório."""
    with pytest.raises(ValidationError) as exc:
        FiltrosDoInventario.model_validate(dados)

    assert _erros(exc) == {(campo,): tipo}


def test_status_do_inventario_sao_os_do_cadastro() -> None:
    """005/R1.5: o filtro `status` aceita os valores do cadastro de unidades, nem mais (sairia
    um relatório vazio sem aviso) nem menos (um status válido daria 422)."""
    assert set(get_args(StatusDaUnidade)) == set(get_args(StatusDoCadastro))


def test_trilha_aceita_ate_366_dias() -> None:
    """005/R1.5: o período da trilha vai até 366 dias, com `ate` exclusivo, como nas consultas
    da auditoria (`occurred_at < :ate`)."""
    assert timedelta(days=366) == PERIODO_MAXIMO_DA_TRILHA

    filtros = FiltrosDaTrilha.model_validate(
        {
            "de": INICIO.isoformat(),
            "ate": (INICIO + PERIODO_MAXIMO_DA_TRILHA).isoformat(),
            "acao": "unidade.",
            "entidade_tipo": "unidade",
        }
    )

    assert filtros.ate - filtros.de == PERIODO_MAXIMO_DA_TRILHA
    assert (filtros.acao, filtros.entidade_tipo) == ("unidade.", "unidade")


def test_trilha_recusa_periodo_maior_que_366_dias() -> None:
    """005/R1.5: período maior que 366 dias dá 422, apontando para `ate`."""
    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha(de=INICIO, ate=INICIO + PERIODO_MAXIMO_DA_TRILHA + timedelta(seconds=1))

    assert _mensagem(exc) == (("ate",), "O período deve ter no máximo 366 dias.")


@pytest.mark.parametrize("ate", [INICIO, INICIO - timedelta(minutes=1)], ids=["igual", "antes"])
def test_trilha_recusa_periodo_vazio_ou_invertido(ate: datetime) -> None:
    """005/R1.5: com `ate` exclusivo, `ate` igual a `de` daria sempre um relatório vazio, e
    antes de `de` não é período."""
    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha(de=INICIO, ate=ate)

    assert _mensagem(exc) == (("ate",), "A data final deve ser posterior à inicial.")


def test_trilha_mede_o_periodo_em_instantes_e_nao_no_relogio() -> None:
    """005/R1.5: o período é medido entre instantes (UTC). Com o mesmo `tzinfo` nos dois lados,
    o Python subtrai o horário de relógio, e um fuso com horário de verão erraria em uma hora:
    366 dias no relógio podem ser 366 dias e 1 hora, e 366 dias e 1 hora no relógio podem ser
    366 dias."""
    de_no_verao = datetime(2026, 6, 30, tzinfo=VERAO)  # 04:00 UTC
    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha(de=de_no_verao, ate=datetime(2027, 7, 1, tzinfo=VERAO))  # 05:00 UTC

    assert _mensagem(exc) == (("ate",), "O período deve ter no máximo 366 dias.")

    filtros = FiltrosDaTrilha(
        de=datetime(2026, 12, 31, tzinfo=VERAO),  # 05:00 UTC
        ate=datetime(2028, 1, 1, 1, tzinfo=VERAO),  # 05:00 UTC
    )

    assert filtros.ate.astimezone(UTC) - filtros.de.astimezone(UTC) == PERIODO_MAXIMO_DA_TRILHA


@pytest.mark.parametrize("campo", ["de", "ate"])
@pytest.mark.parametrize(
    "valor",
    [0, "0", "1767225600", 1767225600.5, True, None],
    ids=["zero", "texto-zero", "texto-unix", "decimal", "booleano", "nulo"],
)
def test_trilha_recusa_numero_no_lugar_de_data(campo: str, valor: object) -> None:
    """005/R1.5: `de` e `ate` são data e hora ISO 8601. Um número, ou texto só com número, o
    Pydantic leria como instante Unix (`0` é 1970-01-01) e o relatório sairia de outro período;
    vira 422, como nos ids, que também não são convertidos."""
    dados: dict[str, object] = {"de": INICIO.isoformat(), "ate": UM_DIA.isoformat(), campo: valor}

    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha.model_validate(dados)

    assert _mensagem(exc) == ((campo,), "Use data e hora ISO 8601, com fuso.")


def test_trilha_exige_inicio_e_fim() -> None:
    """005/R1.5: `de` e `ate` são obrigatórios na trilha."""
    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha.model_validate({})

    assert _erros(exc) == {("de",): "missing", ("ate",): "missing"}


def test_trilha_exige_fuso_horario() -> None:
    """005/R1.5: sem fuso, o instante depende do relógio do banco; vira 422, e misturar data com
    e sem fuso não chega a comparar as duas (não estoura em erro 500)."""
    sem_fuso = datetime(2026, 1, 2)  # noqa: DTZ001 (é o caso testado)

    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha.model_validate({"de": INICIO, "ate": sem_fuso})

    assert _erros(exc) == {("ate",): "timezone_aware"}


@pytest.mark.parametrize(
    ("de", "ate", "campo"),
    [
        ("0001-01-01T00:00:00+14:00", "0001-01-02T00:00:00+00:00", "de"),
        ("9999-12-31T00:00:00-03:00", "9999-12-31T22:00:00-14:00", "ate"),
    ],
)
def test_trilha_recusa_instante_fora_do_calendario_em_utc(de: str, ate: str, campo: str) -> None:
    """005/R1.5: um instante que não cabe no calendário quando vai para UTC (o `timestamptz` do
    banco) dá 422 no pedido, e não falha depois, na geração em segundo plano."""
    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha.model_validate({"de": de, "ate": ate})

    assert _mensagem(exc) == ((campo,), "Data fora do intervalo aceito.")


@pytest.mark.parametrize(
    ("campo", "valor", "tipo"),
    [
        ("acao", "a" * 51, "string_too_long"),
        ("acao", "", "string_pattern_mismatch"),
        ("acao", "%", "string_pattern_mismatch"),
        ("acao", "Unidade.criada", "string_pattern_mismatch"),
        ("entidade_tipo", "e" * 51, "string_too_long"),
        ("entidade_tipo", "", "string_too_short"),
        ("autor", "00000000-0000-0000-0000-000000000000", "extra_forbidden"),
    ],
)
def test_trilha_recusa_texto_invalido_e_campo_desconhecido(
    campo: str, valor: str, tipo: str
) -> None:
    """005/R1.5: `acao` é prefixo de nome de ação (minúsculas, dígitos, `_` e `.`, sem curinga
    `%`) e `entidade_tipo` não é vazio, os dois com até 50 caracteres; a trilha não tem outros
    filtros."""
    with pytest.raises(ValidationError) as exc:
        FiltrosDaTrilha.model_validate({"de": INICIO, "ate": UM_DIA, campo: valor})

    assert _erros(exc) == {(campo,): tipo}


@pytest.mark.parametrize(
    "filtros",
    [
        FiltrosDoInventario(distrito_id=3, status="em_implantacao"),
        FiltrosDaTrilha(de=INICIO, ate=datetime(2026, 6, 30, 23, 59, tzinfo=UTC), acao="unidade."),
    ],
)
def test_filtros_voltam_iguais_do_json(filtros: FiltrosDoInventario | FiltrosDaTrilha) -> None:
    """005/R1.3: o pedido grava os filtros já conferidos (JSONB) e a geração os lê de volta."""
    modelo = type(filtros)

    assert modelo.model_validate(filtros.model_dump(mode="json")) == filtros


def test_filtros_nao_mudam_depois_de_conferidos() -> None:
    """005/R1.5: o que foi conferido é o que a geração usa."""
    filtros = FiltrosDaTrilha(de=INICIO, ate=UM_DIA)

    with pytest.raises(ValidationError):
        filtros.ate = INICIO + timedelta(days=400)
