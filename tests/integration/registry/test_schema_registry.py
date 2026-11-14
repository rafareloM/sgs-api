"""Esquema do cadastro criado pela migração 0006_registry (006/T1).

As referências esperadas são as de docs/architecture/modelo-dados.md § 2 e de
specs/010-dados-demonstracao (tipos de Saúde Mental), copiadas à mão: o teste confere a migração
contra os documentos, e não contra ela mesma.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

VIOLA_UNICIDADE = "23505"  # SQLSTATE unique_violation

DISTRITOS = {f"DS-{romano}" for romano in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")}
AREAS_TECNICAS = {"SAUDE_MENTAL", "SAUDE_BUCAL", "APS", "MAC"}
TIPOS_DE_UNIDADE = {
    "CAPS_II": "SAUDE_MENTAL",
    "CAPS_AD": "SAUDE_MENTAL",
    "CAPS_IJ": "SAUDE_MENTAL",
    "CECON": "SAUDE_MENTAL",
    "SIM": "SAUDE_MENTAL",
    "USF": "APS",
    "POLICLINICA": "MAC",
}
TIPOS_DE_SERVICO = {"FARMACIA", "FARMACIA_FAMILIA", "SALA_VACINA", "ESPACO_MAE_CORUJA"}
TIPOS_DE_EQUIPAMENTO = {"UTI_MOVEL", "MATERNIDADE", "POLICLINICA"}


async def _codigos_ativos(banco: BancoDeTeste, tabela: str) -> set[str]:
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        codigos = set(
            await conexao.scalars(text(f"SELECT code FROM {tabela} WHERE is_active"))  # noqa: S608
        )
    await engine.dispose()
    return codigos


async def test_referencias_semeadas_para_preencher_formularios(banco: BancoDeTeste) -> None:
    """006/R7.1: distritos, áreas técnicas e tipos já existem, ativos, para o login da API."""
    assert await _codigos_ativos(banco, "districts") == DISTRITOS
    assert await _codigos_ativos(banco, "technical_areas") == AREAS_TECNICAS
    assert await _codigos_ativos(banco, "unit_types") == set(TIPOS_DE_UNIDADE)
    assert await _codigos_ativos(banco, "service_types") == TIPOS_DE_SERVICO
    assert await _codigos_ativos(banco, "equipment_types") == TIPOS_DE_EQUIPAMENTO


async def test_tipo_de_unidade_pertence_a_area_tecnica(banco: BancoDeTeste) -> None:
    """006/R7.1: o tipo liga a unidade à área técnica, escopo do COORD_TECNICO (003)."""
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(
            text(
                "SELECT t.code, a.code FROM unit_types t"
                " JOIN technical_areas a ON a.id = t.technical_area_id"
            )
        )
        areas_por_tipo = {str(tipo): str(area) for tipo, area in linhas}
    await engine.dispose()

    assert areas_por_tipo == TIPOS_DE_UNIDADE


async def test_cnes_repetido_e_recusado(banco: BancoDeTeste) -> None:
    """006/R1.3: o CNES identifica uma unidade só, pelo login da API."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        await inserir_unidade(conexao, "CAPS José Carlos Souto", cnes="2711397")

    with pytest.raises(IntegrityError, match="ix_health_units_cnes") as erro:
        async with engine.begin() as conexao:
            await inserir_unidade(conexao, "CAPS Esperança", distrito="DS-II", cnes="2711397")
    await engine.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == VIOLA_UNICIDADE


async def test_unidades_sem_cnes_convivem(banco: BancoDeTeste) -> None:
    """006/R1.3 e R1.5: a unicidade do CNES vale só quando ele existe."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        await inserir_unidade(conexao, "Sala de Vacinação do Shopping")
        await inserir_unidade(conexao, "Atende Gestante")
        sem_cnes = await conexao.scalar(
            text("SELECT count(*) FROM health_units WHERE cnes IS NULL")
        )
    await engine.dispose()

    assert sem_cnes == 2


async def test_nome_e_unico_so_dentro_do_distrito(banco: BancoDeTeste) -> None:
    """006/R1.4: o mesmo nome normalizado se repete em outro distrito, mas não no mesmo."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        await inserir_unidade(conexao, "USF Alto do Mandu", distrito="DS-I", tipo="USF")
        await inserir_unidade(conexao, "USF Alto do Mandu", distrito="DS-IV", tipo="USF")

    with pytest.raises(IntegrityError, match="ix_health_units_district_id_name_normalized") as erro:
        async with engine.begin() as conexao:
            await inserir_unidade(conexao, "usf  alto do mandu", distrito="DS-I", tipo="USF")
    await engine.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == VIOLA_UNICIDADE


async def test_busca_por_trecho_do_nome_usa_o_indice_de_trigramas(banco: BancoDeTeste) -> None:
    """006/R2.2 e R2.7 (base da 006/T4): `ILIKE '%termo%'` sobre o nome normalizado tem índice.

    Com `enable_seqscan = off`, o plano só prova que o índice serve à consulta; com poucas linhas,
    o planejador prefere a varredura sequencial (o desempenho com volume é a 006/T10).
    """
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        await inserir_unidade(conexao, "CAPS Esperança")
        await conexao.execute(text("SET LOCAL enable_seqscan = off"))
        plano = "\n".join(
            await conexao.scalars(
                text(
                    "EXPLAIN SELECT id FROM health_units"
                    " WHERE name_normalized ILIKE '%' || fn_normalize_name(:q) || '%'"
                ),
                {"q": "Esperança"},
            )
        )
    await engine.dispose()

    assert "ix_health_units_name_normalized_trgm" in plano
