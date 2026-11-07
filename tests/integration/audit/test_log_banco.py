"""Log do banco: `db_change_log` gravado por `trg_registry_change_log` (011/T7).

SQL direto, sem a API no meio: o trigger vale para qualquer escrita no cadastro, seja da aplicação
(login da API, membro do `sgs_app`) ou de fora dela (superusuário, o dono do banco de teste). O log
é lido pelo dono, para a leitura não depender dos privilégios em teste.
"""

from typing import Any

import pytest
from sqlalchemy import make_url, text

from tests.integration.postgres import LOGIN_DA_API, BancoDeTeste, motor
from tests.integration.registry.cadastro import (
    inserir_equipamento,
    inserir_servico,
    inserir_unidade,
)


async def _log(banco: BancoDeTeste) -> list[dict[str, Any]]:
    """Registros do log do banco, na ordem em que foram gravados."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(
            text(
                "SELECT table_name, operation, row_id, changed_columns, db_user, via_api,"
                " occurred_at, txid FROM db_change_log ORDER BY id"
            )
        )
        registros = [dict(linha._mapping) for linha in linhas]
    await engine.dispose()
    return registros


async def test_inclusao_registra_cada_coluna_com_de_nulo(banco: BancoDeTeste) -> None:
    """011/R7.1: inclusão de unidade, equipamento e serviço, com data, tabela, operação, linha,
    colunas (de nulo, para o valor gravado), usuário de banco e origem.
    """
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS José Lucena", cnes="2711885")
        equipamento = await inserir_equipamento(conexao, unidade)
        servico = await inserir_servico(conexao, unidade, equipamento=equipamento)
    await engine.dispose()

    log = await _log(banco)

    assert [(r["table_name"], r["operation"], r["row_id"]) for r in log] == [
        ("health_units", "INSERT", unidade),
        ("equipments", "INSERT", equipamento),
        ("services", "INSERT", servico),
    ]
    assert all(r["db_user"] == LOGIN_DA_API and r["via_api"] is True for r in log)
    assert all(r["occurred_at"] is not None and r["txid"] is not None for r in log)
    da_unidade, do_equipamento, do_servico = (r["changed_columns"] for r in log)
    assert da_unidade["name"] == {"de": None, "para": "CAPS José Lucena"}
    assert da_unidade["cnes"] == {"de": None, "para": "2711885"}
    assert da_unidade["neighborhood"] == {"de": None, "para": None}
    # Trigger AFTER: a coluna gerada já está calculada (num BEFORE, chegaria nula).
    assert da_unidade["name_normalized"] == {"de": None, "para": "caps jose lucena"}
    assert do_equipamento["unit_id"] == {"de": None, "para": str(unidade)}
    assert do_servico["equipment_id"] == {"de": None, "para": str(equipamento)}
    # Contagem de pendências, versão e data de atualização não entram no log (011/R7.4).
    assert {"pending_issues", "version", "updated_at"}.isdisjoint(da_unidade)


async def test_alteracao_registra_so_as_colunas_que_mudaram(banco: BancoDeTeste) -> None:
    """011/R7.1: na alteração, só as colunas alteradas, com o valor anterior e o novo.

    A versão e a data de atualização, que o trigger de versão muda junto, ficam de fora (R7.4).
    """
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "USF Upinha Dia Vila Arraes")
    async with engine.begin() as conexao:
        await conexao.execute(
            text(
                "UPDATE health_units SET phone = '8133551234', neighborhood = 'Várzea'"
                " WHERE id = :id"
            ),
            {"id": unidade},
        )
    await engine.dispose()

    *_, alteracao = await _log(banco)

    assert (alteracao["table_name"], alteracao["operation"], alteracao["row_id"]) == (
        "health_units",
        "UPDATE",
        unidade,
    )
    assert alteracao["changed_columns"] == {
        "phone": {"de": None, "para": "8133551234"},
        "neighborhood": {"de": None, "para": "Várzea"},
    }


async def test_exclusao_registra_cada_coluna_com_para_nulo(banco: BancoDeTeste) -> None:
    """011/R7.1: na exclusão, todas as colunas da linha apagada, com o valor anterior."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "Policlínica Amaury Coutinho")
        servico = await inserir_servico(conexao, unidade, nome="Sala de Vacinação")
    async with engine.begin() as conexao:
        await conexao.execute(text("DELETE FROM services WHERE id = :id"), {"id": servico})
    await engine.dispose()

    *_, exclusao = await _log(banco)

    assert (exclusao["table_name"], exclusao["operation"], exclusao["row_id"]) == (
        "services",
        "DELETE",
        servico,
    )
    colunas = exclusao["changed_columns"]
    assert colunas["name"] == {"de": "Sala de Vacinação", "para": None}
    assert colunas["unit_id"] == {"de": str(unidade), "para": None}
    assert all(valores["para"] is None for valores in colunas.values())


# Quem altera: o login da API (membro do `sgs_app`) ou o superusuário, que é membro de todo papel
# e por isso não basta conferir a participação no `sgs_app` (design da 011 § Decisões).
ORIGENS = {"login-da-api": ("url_api", True), "superusuario": ("url_dono", False)}


@pytest.mark.parametrize(("conexao_de", "via_api"), ORIGENS.values(), ids=ORIGENS.keys())
async def test_log_marca_se_a_alteracao_veio_da_api(
    banco: BancoDeTeste, conexao_de: str, via_api: bool
) -> None:
    """011/R7.1 e R7.2: o usuário de banco de cada alteração, e "fora da API" para qualquer um
    que não seja o da aplicação, inclusive superusuário.
    """
    url = getattr(banco, conexao_de)
    engine = motor(url)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "Maternidade Bandeira Filho")
    async with engine.begin() as conexao:
        await conexao.execute(
            text("UPDATE health_units SET status = 'inativa' WHERE id = :id"), {"id": unidade}
        )
    await engine.dispose()

    log = await _log(banco)

    assert [(r["operation"], r["db_user"], r["via_api"]) for r in log] == [
        ("INSERT", make_url(url).username, via_api),
        ("UPDATE", make_url(url).username, via_api),
    ]


async def test_nome_do_gestor_fica_mascarado(banco: BancoDeTeste) -> None:
    """011/R7.3: o log registra que o nome do gestor mudou, sem guardar o nome (LGPD)."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "CAPS David Capistrano")
        for gestor in ("Maria das Dores Silva", "João Batista Lima"):
            await conexao.execute(
                text("UPDATE health_units SET manager_name = :gestor WHERE id = :id"),
                {"gestor": gestor, "id": unidade},
            )
    await engine.dispose()

    log = await _log(banco)

    assert [r["operation"] for r in log] == ["INSERT", "UPDATE", "UPDATE"]
    assert [r["changed_columns"]["manager_name"] for r in log] == [{"de": "***", "para": "***"}] * 3
    assert [r["changed_columns"] for r in log[1:]] == [
        {"manager_name": {"de": "***", "para": "***"}}
    ] * 2
    assert "Maria" not in repr(log)
    assert "João" not in repr(log)


# Colunas que não são dado da unidade: a contagem mantida pela validação (007) e o que o trigger
# de versão escreve.
SEM_DADO_DA_UNIDADE = {
    "pendencias": "UPDATE health_units SET pending_issues = 3 WHERE id = :id",
    "versao": "UPDATE health_units SET version = version + 5 WHERE id = :id",
    "data-de-atualizacao": (
        "UPDATE health_units SET updated_at = now() + interval '1 day' WHERE id = :id"
    ),
}


@pytest.mark.parametrize("alteracao", SEM_DADO_DA_UNIDADE.values(), ids=SEM_DADO_DA_UNIDADE.keys())
async def test_mudanca_so_em_pendencias_versao_ou_data_nao_gera_registro(
    banco: BancoDeTeste, alteracao: str
) -> None:
    """011/R7.4: só a contagem de pendências, a versão ou a data de atualização não é alteração."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "USF Upinha Dia Vila Arraes")
    async with engine.begin() as conexao:
        await conexao.execute(text(alteracao), {"id": unidade})
    await engine.dispose()

    log = await _log(banco)

    assert [r["operation"] for r in log] == ["INSERT"]


async def test_exclusao_de_equipamento_registra_os_servicos_desligados(
    banco: BancoDeTeste,
) -> None:
    """011/R7.5: o SET NULL da exclusão de equipamento aparece como alteração de cada serviço."""
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "Hospital da Mulher do Recife")
        equipamento = await inserir_equipamento(conexao, unidade)
        servicos = {
            await inserir_servico(conexao, unidade, equipamento=equipamento, nome=nome)
            for nome in ("Pré-natal de alto risco", "Banco de Leite")
        }
    async with engine.begin() as conexao:
        await conexao.execute(text("DELETE FROM equipments WHERE id = :id"), {"id": equipamento})
    await engine.dispose()

    log = await _log(banco)
    da_exclusao = [r for r in log if r["txid"] == log[-1]["txid"]]

    assert {(r["table_name"], r["operation"], r["row_id"]) for r in da_exclusao} == {
        ("equipments", "DELETE", equipamento),
        *(("services", "UPDATE", servico) for servico in servicos),
    }
    assert [r["changed_columns"] for r in da_exclusao if r["table_name"] == "services"] == [
        {"equipment_id": {"de": str(equipamento), "para": None}}
    ] * 2


async def test_correcao_de_codigo_de_tipo_registra_os_equipamentos_do_tipo(
    banco: BancoDeTeste,
) -> None:
    """011/R7.5: o ON UPDATE CASCADE do código de referência aparece como alteração de cada
    equipamento do tipo (R9.2).
    """
    engine = motor(banco.url_api)
    async with engine.begin() as conexao:
        unidade = await inserir_unidade(conexao, "Hospital da Mulher do Recife")
        equipamento = await inserir_equipamento(conexao, unidade, tipo="MATERNIDADE")
    async with engine.begin() as conexao:
        await conexao.execute(
            text(
                "UPDATE equipment_types SET code = 'MATERNIDADE_ALTO_RISCO'"
                " WHERE code = 'MATERNIDADE'"
            )
        )
    await engine.dispose()

    *_, cascata = await _log(banco)

    assert (cascata["table_name"], cascata["operation"], cascata["row_id"]) == (
        "equipments",
        "UPDATE",
        equipamento,
    )
    assert cascata["changed_columns"] == {
        "equipment_type_code": {"de": "MATERNIDADE", "para": "MATERNIDADE_ALTO_RISCO"}
    }
