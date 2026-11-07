"""Views do inventário e do histórico das unidades: `vw_unit_inventory` e `vw_unit_history`
(011/T4).

Lidas pelo login da API, que é quem as consulta (inventário do dashboard e histórico da unidade,
011/T13 e T14); o cadastro é semeado pelo dono do banco.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.core.ids import uuid7
from src.modules.audit.application.registrar import Ator, Entidade, Mudanca, registrar
from src.modules.audit.domain.entry import AuditEntry
from src.modules.audit.infrastructure.repository import SqlAuditStore
from tests.integration.postgres import LOGIN_DA_API, BancoDeTeste, motor
from tests.integration.registry.cadastro import (
    inserir_equipamento,
    inserir_servico,
    inserir_unidade,
)


async def _ids_das_referencias(conexao: AsyncConnection) -> dict[tuple[str, str], int]:
    """Ids que o banco gerou para as referências semeadas, por (tabela, código)."""
    linhas = await conexao.execute(
        text(
            "SELECT 'districts', code, id FROM districts"
            " UNION ALL SELECT 'unit_types', code, id FROM unit_types"
            " UNION ALL SELECT 'technical_areas', code, id FROM technical_areas"
        )
    )
    return {(tabela, codigo): id_ for tabela, codigo, id_ in linhas}


async def _inventario(banco: BancoDeTeste) -> dict[UUID, dict[str, Any]]:
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(text("SELECT * FROM vw_unit_inventory"))
        inventario = {linha["unit_id"]: dict(linha) for linha in linhas.mappings()}
    await engine.dispose()
    return inventario


async def test_inventario_conta_equipamentos_servicos_e_servicos_fora_do_cnes(
    banco: BancoDeTeste,
) -> None:
    """011/R4.1: uma linha por unidade, com tipo, área técnica, distrito, status, situação
    cadastral (011/R5.3) e as quantidades de equipamentos, serviços e serviços fora do CNES."""
    engine = motor(banco.url_dono)
    async with engine.begin() as conexao:
        caps = await inserir_unidade(conexao, "CAPS Esperança", cnes="2345678")
        maternidade = await inserir_equipamento(conexao, caps, nome="Maternidade")
        await inserir_equipamento(conexao, caps, nome="Policlínica", tipo="POLICLINICA")
        await inserir_servico(conexao, caps, nome="Farmácia do CAPS", no_cnes=True)
        await inserir_servico(conexao, caps, equipamento=maternidade, nome="Sala de Vacina")
        await inserir_servico(conexao, caps, nome="Espaço Mãe Coruja")

        usf = await inserir_unidade(conexao, "USF Ibura", distrito="DS-VI", tipo="USF")

        cecon = await inserir_unidade(conexao, "CECON Boa Vista", tipo="CECON", cnes="3456789")
        await inserir_servico(conexao, cecon, nome="Farmácia do CECON")
        await conexao.execute(
            text("UPDATE health_units SET status = 'inativa' WHERE id = :id"), {"id": cecon}
        )

        # Sem unidade (006/R5.2 e R6.2): não entram na contagem de nenhuma unidade.
        await inserir_equipamento(conexao, None, nome="UTI móvel do SAMU", tipo="UTI_MOVEL")
        await inserir_servico(conexao, None, nome="Sala de Vacinação do Shopping")

        ids = await _ids_das_referencias(conexao)
    await engine.dispose()

    inventario = await _inventario(banco)

    assert inventario == {
        caps: {
            "unit_id": caps,
            "name": "CAPS Esperança",
            "cnes": "2345678",
            "status": "ativa",
            "registration_status": "regular",
            "unit_type_id": ids["unit_types", "CAPS_II"],
            "unit_type_name": "CAPS II",
            "technical_area_id": ids["technical_areas", "SAUDE_MENTAL"],
            "technical_area_name": "Saúde Mental",
            "district_id": ids["districts", "DS-I"],
            "district_name": "Distrito Sanitário I",
            "equipment_count": 2,
            "service_count": 3,
            "services_outside_cnes_count": 2,
        },
        usf: {
            "unit_id": usf,
            "name": "USF Ibura",
            "cnes": None,
            "status": "ativa",
            "registration_status": "sem_cnes",
            "unit_type_id": ids["unit_types", "USF"],
            "unit_type_name": "Unidade de Saúde da Família",
            "technical_area_id": ids["technical_areas", "APS"],
            "technical_area_name": "Atenção Primária à Saúde",
            "district_id": ids["districts", "DS-VI"],
            "district_name": "Distrito Sanitário VI",
            "equipment_count": 0,
            "service_count": 0,
            "services_outside_cnes_count": 0,
        },
        cecon: {
            "unit_id": cecon,
            "name": "CECON Boa Vista",
            "cnes": "3456789",
            "status": "inativa",
            "registration_status": "inativa",
            "unit_type_id": ids["unit_types", "CECON"],
            "unit_type_name": "CECON",
            "technical_area_id": ids["technical_areas", "SAUDE_MENTAL"],
            "technical_area_name": "Saúde Mental",
            "district_id": ids["districts", "DS-I"],
            "district_name": "Distrito Sanitário I",
            "equipment_count": 0,
            "service_count": 1,
            "services_outside_cnes_count": 1,
        },
    }


# Colunas do design da 011 § `vw_unit_inventory`, na ordem.
COLUNAS_DO_INVENTARIO = (
    "unit_id",
    "name",
    "cnes",
    "status",
    "registration_status",
    "unit_type_id",
    "unit_type_name",
    "technical_area_id",
    "technical_area_name",
    "district_id",
    "district_name",
    "equipment_count",
    "service_count",
    "services_outside_cnes_count",
)


async def _colunas(banco: BancoDeTeste, view: str) -> tuple[str, ...]:
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        colunas = await conexao.scalars(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = :view ORDER BY ordinal_position"
            ),
            {"view": view},
        )
        resultado = tuple(colunas)
    await engine.dispose()
    return resultado


async def test_inventario_nao_expoe_dado_pessoal(banco: BancoDeTeste) -> None:
    """011/R4.2: nem o nome do gestor nem o contato da unidade saem pelo inventário (LGPD)."""
    engine = motor(banco.url_dono)
    async with engine.begin() as conexao:
        caps = await inserir_unidade(conexao, "CAPS Esperança", cnes="2345678")
        await conexao.execute(
            text(
                "UPDATE health_units SET manager_name = 'Joana Pereira da Silva',"
                " phone = '8133551234', neighborhood = 'Boa Vista' WHERE id = :id"
            ),
            {"id": caps},
        )
    await engine.dispose()

    colunas = await _colunas(banco, "vw_unit_inventory")
    linha = (await _inventario(banco))[caps]

    assert colunas == COLUNAS_DO_INVENTARIO
    valores = {str(valor) for valor in linha.values()}
    assert valores.isdisjoint(
        {"Joana Pereira da Silva", "8133551234", "Boa Vista", "Rua do Sol, 150", "50010100"}
    )


# Colunas do design da 011 § `vw_unit_history`, na ordem.
COLUNAS_DO_HISTORICO = (
    "audit_id",
    "occurred_at",
    "action",
    "changes",
    "metadata",
    "actor_user_id",
    "actor_name",
    "actor_roles",
    "unit_id",
    "unit_name",
    "district_id",
    "district_name",
    "unit_type_name",
    "technical_area_id",
)


async def _registrar(
    sessoes: async_sessionmaker[AsyncSession],
    acao: str,
    ator: Ator,
    entidade: Entidade | None,
    mudancas: Sequence[Mudanca] = (),
    metadados: dict[str, Any] | None = None,
) -> AuditEntry:
    """Evento gravado pelo `audit.registrar`, como os casos de uso da 006 fazem."""
    async with sessoes() as sessao, sessao.begin():
        return await registrar(
            SqlAuditStore(sessao),
            acao=acao,
            ator=ator,
            entidade=entidade,
            mudancas=mudancas,
            metadados=metadados,
        )


async def test_historico_traz_eventos_da_unidade_de_equipamentos_e_servicos_com_autor(
    banco: BancoDeTeste,
) -> None:
    """011/R4.4: data, autor, ação, unidade, distrito, tipo e a lista {campo, de, para}, com os
    eventos de equipamentos e serviços da unidade (gravados no nível dela, 006/R5.3)."""
    gestora = uuid7()
    dono = motor(banco.url_dono)
    async with dono.begin() as conexao:
        caps = await inserir_unidade(conexao, "CAPS Esperança", cnes="2345678")
        usf = await inserir_unidade(conexao, "USF Ibura", distrito="DS-VI", tipo="USF")
        maternidade = await inserir_equipamento(conexao, caps, nome="Maternidade")
        farmacia = await inserir_servico(conexao, caps, nome="Farmácia do CAPS")
        await conexao.execute(
            text(
                "INSERT INTO users (id, username, display_name, source, external_id)"
                " VALUES (:id, 'joana', 'Joana Gestora', 'ldap', 'uid=joana,ou=pessoas')"
            ),
            {"id": gestora},
        )
        ids = await _ids_das_referencias(conexao)
    await dono.dispose()

    api = motor(banco.url_api)
    sessoes = async_sessionmaker(api, expire_on_commit=False)
    autora = Ator(user_id=gestora, papeis=("GESTOR_DADOS",))
    no_caps = Entidade(tipo="unidade", id=str(caps))
    criada = await _registrar(
        sessoes, "unidade.criada", autora, no_caps, [Mudanca("nome", None, "CAPS Esperança")]
    )
    equipamento = await _registrar(
        sessoes,
        "unidade.equipamento_criado",
        autora,
        no_caps,
        [Mudanca("equipamento.nome", None, "Maternidade")],
        {"equipamento_id": str(maternidade)},
    )
    servico = await _registrar(
        sessoes,
        "unidade.servico_criado",
        autora,
        no_caps,
        [Mudanca("servico.nome", None, "Farmácia do CAPS")],
        {"servico_id": str(farmacia)},
    )
    # Sem autor (tarefa do sistema): o evento continua no histórico, com o autor nulo.
    pendencias = await _registrar(
        sessoes, "unidade.atualizada", Ator(), no_caps, [Mudanca("pendencias", 0, 1)]
    )
    # Fora do histórico do CAPS: evento de outra unidade e evento sem entidade.
    await _registrar(sessoes, "unidade.criada", autora, Entidade(tipo="unidade", id=str(usf)))
    await _registrar(sessoes, "auth.login", autora, None)

    async with api.connect() as conexao:
        todos = (
            await conexao.execute(
                text("SELECT action, unit_id FROM vw_unit_history ORDER BY audit_id")
            )
        ).all()
        do_caps = [
            dict(linha)
            for linha in (
                await conexao.execute(
                    text("SELECT * FROM vw_unit_history WHERE unit_id = :id ORDER BY audit_id"),
                    {"id": caps},
                )
            ).mappings()
        ]
    await api.dispose()

    assert [tuple(linha) for linha in todos] == [
        ("unidade.criada", caps),
        ("unidade.equipamento_criado", caps),
        ("unidade.servico_criado", caps),
        ("unidade.atualizada", caps),
        ("unidade.criada", usf),
    ]
    assert all(tuple(linha) == COLUNAS_DO_HISTORICO for linha in do_caps)
    da_unidade = {
        "unit_id": caps,
        "unit_name": "CAPS Esperança",
        "district_id": ids["districts", "DS-I"],
        "district_name": "Distrito Sanitário I",
        "unit_type_name": "CAPS II",
        "technical_area_id": ids["technical_areas", "SAUDE_MENTAL"],
    }
    pela_gestora = {
        "actor_user_id": gestora,
        "actor_name": "Joana Gestora",
        "actor_roles": ["GESTOR_DADOS"],
    }
    assert [{k: v for k, v in linha.items() if k != "audit_id"} for linha in do_caps] == [
        {
            "occurred_at": criada.occurred_at,
            "action": "unidade.criada",
            "changes": [{"campo": "nome", "de": None, "para": "CAPS Esperança"}],
            "metadata": {},
            **pela_gestora,
            **da_unidade,
        },
        {
            "occurred_at": equipamento.occurred_at,
            "action": "unidade.equipamento_criado",
            "changes": [{"campo": "equipamento.nome", "de": None, "para": "Maternidade"}],
            "metadata": {"equipamento_id": str(maternidade)},
            **pela_gestora,
            **da_unidade,
        },
        {
            "occurred_at": servico.occurred_at,
            "action": "unidade.servico_criado",
            "changes": [{"campo": "servico.nome", "de": None, "para": "Farmácia do CAPS"}],
            "metadata": {"servico_id": str(farmacia)},
            **pela_gestora,
            **da_unidade,
        },
        {
            "occurred_at": pendencias.occurred_at,
            "action": "unidade.atualizada",
            "changes": [{"campo": "pendencias", "de": 0, "para": 1}],
            "metadata": {},
            "actor_user_id": None,
            "actor_name": None,
            "actor_roles": [],
            **da_unidade,
        },
    ]


# Leitura de cada view; o nome não vem de fora do teste.
LEITURAS = {
    "vw_unit_inventory": "SELECT * FROM vw_unit_inventory",
    "vw_unit_history": "SELECT * FROM vw_unit_history",
}
SEM_PRIVILEGIO = "42501"  # SQLSTATE insufficient_privilege


@pytest.mark.parametrize(("view", "leitura"), LEITURAS.items(), ids=LEITURAS.keys())
async def test_papel_sem_select_nas_tabelas_base_nao_le_a_view(
    banco: BancoDeTeste, view: str, leitura: str
) -> None:
    """011/R4.6: a view usa as permissões de quem consulta, não as do dono que a criou.

    O papel recebe SELECT só na view; sem `security_invoker`, leria o cadastro e a trilha com o
    privilégio do dono das migrações (superusuário). Tudo numa transação desfeita no fim: o papel
    não sobra no servidor.
    """
    papel = f"leitor_so_da_view_{uuid7().hex[-12:]}"
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        await conexao.execute(text(f"CREATE ROLE {papel} NOLOGIN"))
        await conexao.execute(text(f"GRANT SELECT ON {view} TO {papel}"))
        await conexao.execute(text(f"SET LOCAL ROLE {papel}"))
        with pytest.raises(DBAPIError) as erro:
            await conexao.execute(text(leitura))
        await conexao.rollback()
    await engine.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == SEM_PRIVILEGIO
    assert "permission denied for table" in str(erro.value.orig)


@pytest.mark.parametrize("view", LEITURAS.keys())
async def test_login_da_api_so_le_as_views(banco: BancoDeTeste, view: str) -> None:
    """011/R4.6: o login da API lê as views (inventário e histórico) e nada além disso."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_table_privilege(:login, CAST(:view AS regclass), 'SELECT'),"
                " has_table_privilege(:login, CAST(:view AS regclass),"
                " 'INSERT, UPDATE, DELETE, TRUNCATE')"
            ),
            {"login": LOGIN_DA_API, "view": view},
        )
        leitura, escrita = linha.one()
    await engine.dispose()

    assert (leitura, escrita) == (True, False)
