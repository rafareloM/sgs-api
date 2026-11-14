"""Prova de uso dos índices com volume de demonstração (011/T9; os da 0006 e o do log do banco,
na revisão do /implement-spec, pela letra de 011/R1.4, "cada índice").

A massa (1.000 unidades com CNES, 3.000 serviços e a trilha que os casos de uso da 006
gravariam, pelo `audit.registrar`) é semeada pelo dono do banco; depois do `ANALYZE`, o `EXPLAIN`
roda pelo login da API, que é quem faz as consultas. Sem `enable_seqscan = off`: o plano é o que
o planejador escolhe sozinho com o volume, não um plano forçado.

Roda à parte (`uv run pytest tests/integration/db/test_indices.py -m slow`), fora do `make check`:
a massa leva alguns segundos para semear.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.sql import consulta
from src.modules.audit.application.registrar import Ator, Entidade, Mudanca, registrar
from src.modules.audit.infrastructure.repository import SqlAuditStore
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import inserir_servico, inserir_unidade

pytestmark = pytest.mark.slow

UNIDADES = 1_000
SERVICOS_POR_UNIDADE = 3
DISTRITOS = ("DS-I", "DS-II", "DS-III", "DS-IV", "DS-V", "DS-VI", "DS-VII", "DS-VIII")

RAIZ = Path(__file__).resolve().parents[3]
DDL = RAIZ / "migrations/sql"
CONSULTAS_DO_AUDIT = RAIZ / "src/modules/audit/infrastructure/sql"
CONSULTAS_DO_REGISTRY = RAIZ / "src/modules/registry/infrastructure/sql"
HISTORICO = CONSULTAS_DO_AUDIT / "unit_history.sql"
LOG_DO_BANCO = CONSULTAS_DO_AUDIT / "db_change_log_list.sql"

# O `.sql` de cada índice escrito à mão (011/R1.4, "cada índice").
SQL_DOS_INDICES = {
    "ix_audit_log_entity": DDL / "0011_03/06_ix_audit_log_entity.sql",
    "ix_services_unit_id": DDL / "0011_03/07_ix_services_unit_id.sql",
    "ix_health_units_cnes": DDL / "0006/13_ix_health_units_cnes.sql",
    "ix_health_units_district_id_name_normalized": (
        DDL / "0006/14_ix_health_units_district_id_name_normalized.sql"
    ),
    "ix_health_units_name_normalized_trgm": (
        DDL / "0006/15_ix_health_units_name_normalized_trgm.sql"
    ),
    "ix_db_change_log_occurred_at": DDL / "0011_07/03_ix_db_change_log_occurred_at.sql",
}

# Sem uso pelo planejador com o volume de demonstração: o cabeçalho diz isso e por quê
# (011, "Perguntas em aberto", R1.4).
SEM_USO_COMPROVADO = {"ix_health_units_name_normalized_trgm"}

# Serviços de uma unidade, como a rota de serviços da unidade os lista (006/T8, 011/R1.2).
SERVICOS_DA_UNIDADE = CONSULTAS_DO_REGISTRY / "services_by_unit.sql"
UNIDADE_PELO_CNES = CONSULTAS_DO_REGISTRY / "health_unit_id_by_cnes.sql"
UNIDADE_PELO_NOME = CONSULTAS_DO_REGISTRY / "health_unit_id_by_name.sql"
BUSCA_DE_UNIDADES = CONSULTAS_DO_REGISTRY / "search_health_units.sql"


@dataclass(frozen=True)
class Volume:
    banco: BancoDeTeste
    unidade: UUID


async def _semear(banco: BancoDeTeste) -> UUID:
    """Cadastro e trilha de demonstração; devolve uma unidade do meio da massa."""
    engine = motor(banco.url_dono)
    servicos: dict[UUID, list[UUID]] = {}
    async with engine.begin() as conexao:
        for n in range(UNIDADES):
            unidade = await inserir_unidade(
                conexao,
                f"Unidade de Demonstração {n:04d}",
                distrito=DISTRITOS[n % len(DISTRITOS)],
                cnes=f"{n:07d}",
            )
            servicos[unidade] = [
                await inserir_servico(conexao, unidade, nome=f"Serviço {s} da unidade {n:04d}")
                for s in range(SERVICOS_POR_UNIDADE)
            ]

    # A trilha que a 006 grava: criação da unidade e de cada serviço, no nível da unidade
    # (006/R5.3), pelo mesmo caso de uso dos módulos.
    sessoes = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ator = Ator(papeis=("GESTOR_DADOS",))
    async with sessoes() as sessao, sessao.begin():
        store = SqlAuditStore(sessao)
        for unidade, dela in servicos.items():
            entidade = Entidade(tipo="unidade", id=str(unidade))
            await registrar(
                store,
                acao="unidade.criada",
                ator=ator,
                entidade=entidade,
                mudancas=[Mudanca("status", None, "ativa")],
            )
            for servico in dela:
                await registrar(
                    store,
                    acao="unidade.servico_criado",
                    ator=ator,
                    entidade=entidade,
                    mudancas=[Mudanca("servico.status", None, "ativo")],
                    metadados={"servico_id": str(servico)},
                )

    async with engine.connect() as conexao:
        await conexao.execute(text("ANALYZE"))
    await engine.dispose()
    return list(servicos)[UNIDADES // 2]


@pytest.fixture
async def volume(banco: BancoDeTeste) -> Volume:
    return Volume(banco=banco, unidade=await _semear(banco))


async def _plano(banco: BancoDeTeste, consulta_sql: str, parametros: dict[str, object]) -> str:
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(text(f"EXPLAIN (COSTS OFF) {consulta_sql}"), parametros)
        plano = "\n".join(linha for (linha,) in linhas)
    await engine.dispose()
    return plano


def _cabecalho(arquivo: Path) -> str:
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    return "\n".join(linha for linha in linhas if linha.startswith("--"))


async def test_historico_de_uma_unidade_usa_ix_audit_log_entity(volume: Volume) -> None:
    """011/R1.1, R1.3: com volume, o histórico de uma unidade (a consulta da rota) chega à trilha
    pelo índice, não por leitura da tabela inteira."""
    parametros: dict[str, object] = {
        "unit_id": volume.unidade,
        "occurred_from": None,
        "occurred_to": None,
        "actor_user_id": None,
        "changed_field": None,
        "limit": 50,
        "offset": 0,
    }

    plano = await _plano(volume.banco, consulta(HISTORICO).text, parametros)

    assert "ix_audit_log_entity" in plano, plano
    assert "Seq Scan on audit_log" not in plano, plano


async def test_servicos_de_uma_unidade_usam_ix_services_unit_id(volume: Volume) -> None:
    """011/R1.2, R1.3: com volume, os serviços de uma unidade são achados pelo índice."""
    plano = await _plano(
        volume.banco, consulta(SERVICOS_DA_UNIDADE).text, {"unit_id": volume.unidade}
    )

    assert "ix_services_unit_id" in plano, plano
    assert "Seq Scan on services" not in plano, plano


async def test_unidade_pelo_cnes_usa_ix_health_units_cnes(volume: Volume) -> None:
    """011/R1.4, 006/R1.3: a procura da unidade pelo CNES (o 409 da criação e da alteração) acha
    a linha pelo índice parcial do CNES."""
    plano = await _plano(volume.banco, consulta(UNIDADE_PELO_CNES).text, {"cnes": "0000500"})

    assert "Index Scan using ix_health_units_cnes on health_units" in plano, plano


async def test_unidade_pelo_nome_no_distrito_usa_o_indice_unico(volume: Volume) -> None:
    """011/R1.4, 006/R1.4: a procura pelo nome normalizado no distrito (o 409 do nome repetido)
    usa o índice único `(district_id, name_normalized)`."""
    distrito = await _id_do_distrito(volume.banco, "DS-I")
    parametros = {"district_id": distrito, "name": "Unidade de Demonstração 0504"}

    plano = await _plano(volume.banco, consulta(UNIDADE_PELO_NOME).text, parametros)

    assert "Index Scan using ix_health_units_district_id_name_normalized" in plano, plano


async def test_busca_por_texto_nao_usa_o_indice_de_trigramas_com_1000_unidades(
    volume: Volume,
) -> None:
    """011/R1.4 (registro honesto): com 1.000 unidades, a busca por texto livre (006/R2.2) lê a
    tabela inteira; o planejador acha a leitura sequencial mais barata e o `OR cnes LIKE` da
    consulta não tem índice. O cabeçalho do índice registra este plano, e o teste falha se ele
    mudar, para o cabeçalho ser revisto (011, "Perguntas em aberto", R1.4)."""
    parametros: dict[str, object] = {
        "scope_global": True,
        "scope_areas": [],
        "scope_districts": [],
        "scope_units": [],
        "q": "Demonstração 0500",
        "q_like": "Demonstração 0500",
        "unit_type_id": None,
        "technical_area_id": None,
        "district_id": None,
        "status": None,
        "with_pending": None,
        "order_by": "relevancia",
        "limit": 20,
        "offset": 0,
    }

    plano = await _plano(volume.banco, consulta(BUSCA_DE_UNIDADES).text, parametros)

    assert "Seq Scan on health_units" in plano, plano
    assert "ix_health_units_name_normalized_trgm" not in plano, plano


async def test_log_do_banco_por_periodo_usa_o_indice_da_particao(volume: Volume) -> None:
    """011/R1.4, R7.7: a listagem do log do banco por período lê só a partição do mês e chega às
    linhas pelo índice de `occurred_at` que o PostgreSQL criou nela a partir de
    `ix_db_change_log_occurred_at` (o índice da tabela-mãe vale em cada partição)."""
    agora = datetime.now(UTC)
    parametros: dict[str, object] = {
        "occurred_from": agora - timedelta(hours=1),
        "occurred_to": agora + timedelta(hours=1),
        "table_name": None,
        "outside_api": None,
        "limit": 50,
        "offset": 0,
    }

    plano = await _plano(volume.banco, consulta(LOG_DO_BANCO).text, parametros)

    mes = f"db_change_log_y{agora:%Y}m{agora:%m}"
    assert f"Bitmap Index Scan on {mes}_occurred_at_idx" in plano, plano
    assert "Seq Scan" not in plano, plano


async def _id_do_distrito(banco: BancoDeTeste, codigo: str) -> int:
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        distrito = await conexao.scalar(
            text("SELECT id FROM districts WHERE code = :codigo"), {"codigo": codigo}
        )
    await engine.dispose()
    return int(distrito)


@pytest.mark.parametrize("indice", SQL_DOS_INDICES)
def test_cabecalho_do_indice_registra_o_plano(indice: str) -> None:
    """011/R1.4: o cabeçalho do `.sql` de cada índice traz o plano de execução (`EXPLAIN`) que
    comprova o uso ou, se o planejador não o usa com o volume de demonstração, diz isso."""
    cabecalho = _cabecalho(SQL_DOS_INDICES[indice])

    assert "EXPLAIN" in cabecalho
    if indice in SEM_USO_COMPROVADO:
        assert "Sem uso comprovado" in cabecalho
    else:
        # "Index Scan using <índice>" ou "Bitmap Index Scan on <índice>", conforme o plano; no
        # log particionado, o índice que o PostgreSQL criou na partição a partir dele.
        nome = "occurred_at_idx" if indice == "ix_db_change_log_occurred_at" else indice
        assert any("Index Scan" in linha and nome in linha for linha in cabecalho.splitlines())
