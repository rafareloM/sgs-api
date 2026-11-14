"""Normalização de nomes no banco: `fn_normalize_name` e quem a usa (011/T2)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.modules.registry.domain.unidade import normalizar_nome
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_unidade

# Entrada e saída esperada, escritas à mão a partir da regra de R5.1.
CASOS = {
    "acento": ("Espaço Mãe Coruja", "espaco mae coruja"),
    "caixa": ("CAPS AD Ibura", "caps ad ibura"),
    "pontas": ("   Policlínica Gouveia de Barros   ", "policlinica gouveia de barros"),
    "espacos-repetidos": ("UPA  da   Várzea", "upa da varzea"),
    "tab-e-quebra-no-meio": ("Sala de\tVacina\n Shopping", "sala de vacina shopping"),
    # O `btrim` vai por fora: tab e quebra de linha nas pontas também saem (decisão do Rafael,
    # 07/11/2026, em Perguntas em aberto da 011).
    "tab-na-ponta": ("UPA  Ibura\t", "upa ibura"),
    "quebra-e-tab-nas-pontas": ("\n CAPS Esperança \t", "caps esperanca"),
    "cedilha-e-til": ("AÇÃO SOCIAL São João", "acao social sao joao"),
}


@pytest.mark.parametrize(("nome", "esperado"), CASOS.values(), ids=CASOS.keys())
async def test_funcao_normaliza_acento_caixa_e_espacos(
    banco: BancoDeTeste, nome: str, esperado: str
) -> None:
    """011/R5.1: sem acento, minúsculo, sem espaços nas pontas e repetidos; pelo login da API."""
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        normalizado = await conexao.scalar(text("SELECT fn_normalize_name(:nome)"), {"nome": nome})
    await engine.dispose()

    assert normalizado == esperado


async def test_so_a_aplicacao_executa_a_funcao(banco: BancoDeTeste) -> None:
    """011/R10.1: EXECUTE revogado de PUBLIC e concedido ao `sgs_app`."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_function_privilege('public', 'fn_normalize_name(text)', 'EXECUTE'),"
                " has_function_privilege('sgs_app', 'fn_normalize_name(text)', 'EXECUTE')"
            )
        )
        publico, aplicacao = linha.one()
    await engine.dispose()

    assert (publico, aplicacao) == (False, True)


async def test_nome_normalizado_e_gerado_na_insercao_pelo_login_da_api(
    banco: BancoDeTeste,
) -> None:
    """011/R5.2: a coluna gerada usa a função, também quando quem insere é a aplicação."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "  Espaço  Mãe Coruja ")
        normalizado = await conexao.scalar(
            text("SELECT name_normalized FROM health_units WHERE id = :id"), {"id": unidade}
        )
    await engine.dispose()

    assert normalizado == "espaco mae coruja"


async def test_grafias_do_mesmo_nome_no_distrito_violam_a_unicidade(banco: BancoDeTeste) -> None:
    """011/R5.2 e 006/R1.4: acento, caixa e espaços não fazem de um nome outra unidade."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        await inserir_unidade(conexao, "Espaço Azul")

    with pytest.raises(IntegrityError, match="ix_health_units_district_id_name_normalized"):
        async with engine.begin() as conexao:
            await inserir_unidade(conexao, " ESPACO   azul")
    await engine.dispose()


async def test_busca_acha_o_nome_digitado_sem_acento(banco: BancoDeTeste) -> None:
    """011/R5.2 e 006/R2.2: "espaco azul" acha "Espaço  Azul" pela mesma função."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        await inserir_unidade(conexao, "Espaço  Azul")
        await inserir_unidade(conexao, "CAPS Leste")
        encontrados = list(
            await conexao.scalars(
                text(
                    "SELECT name FROM health_units"
                    " WHERE name_normalized ILIKE '%' || fn_normalize_name(:q) || '%'"
                ),
                {"q": "espaco azul"},
            )
        )
    await engine.dispose()

    assert encontrados == ["Espaço  Azul"]


async def test_dominio_da_006_normaliza_igual_ao_banco(banco: BancoDeTeste) -> None:
    """011/R5.2: para um mesmo texto, a `normalizar_nome` (006/T2) e a função do banco concordam."""
    nomes = [nome for nome, _ in CASOS.values()]
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        no_banco = [
            await conexao.scalar(text("SELECT fn_normalize_name(:nome)"), {"nome": nome})
            for nome in nomes
        ]
    await engine.dispose()

    assert [normalizar_nome(nome) for nome in nomes] == no_banco
