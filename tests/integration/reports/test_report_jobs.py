"""Tabela `report_jobs` e repositório de pedidos sobre o PostgreSQL (005/T1).

Design da 005 § Modelo de dados (colunas, `CHECK` de coerência, índices) e § Fluxo (transições
de status do pedido).
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.db import alembic_config
from src.core.ids import uuid7
from src.modules.identity.infrastructure.repository import SqlUserRepository
from src.modules.reports.domain.assinatura import Assinatura
from src.modules.reports.domain.pedidos import (
    ERRO_INTERROMPIDO,
    ERRO_MAX,
    Conclusao,
    FormatoDeRelatorio,
    Pagina,
    PedidoDeRelatorio,
    StatusDoPedido,
    TipoDeRelatorio,
    novo_pedido,
)
from src.modules.reports.infrastructure.repository import SqlRepositorioDePedidos
from tests.factories import make_user
from tests.integration.postgres import BancoDeTeste, motor

AGORA = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
SHA256_HEX = "ab" * 32
ESCOPO_GLOBAL = {"global": True, "areas": [], "distritos": [], "unidades": []}
ESCOPO_DISTRITO = {"global": False, "areas": [], "distritos": [3], "unidades": []}

INSERIR_PEDIDO = (
    "INSERT INTO report_jobs (id, report_type, format, filters, requested_by, scope_snapshot,"
    " status{colunas}) VALUES (:id, :tipo, :formato, '{{}}', :usuario, '{{}}', :status{valores})"
)


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessões com o login da API (papel sgs_app), como em produção."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _usuario(sessoes: async_sessionmaker[AsyncSession], username: str = "maria") -> UUID:
    usuario = make_user(username=username, email=f"{username}@example.org")
    async with sessoes() as sessao, sessao.begin():
        await SqlUserRepository(sessao).add(usuario)
    return usuario.id


def _pedido(
    usuario: UUID,
    *,
    agora: datetime = AGORA,
    tipo: TipoDeRelatorio = TipoDeRelatorio.INVENTARIO_UNIDADES,
) -> PedidoDeRelatorio:
    return novo_pedido(
        id=uuid7(),
        tipo=tipo,
        formato=FormatoDeRelatorio.XLSX,
        filtros={"distrito_id": 3},
        solicitado_por=usuario,
        escopo=ESCOPO_DISTRITO,
        agora=agora,
    )


def _conclusao() -> Conclusao:
    return Conclusao(
        bucket="sgs-relatorios",
        chave="reports/2026/11/inventario_unidades/x.xlsx",
        versao="v-1",
        tamanho_bytes=4096,
        sha256=SHA256_HEX,
        assinatura=Assinatura(kid="rel-2026-11", algoritmo="ES256", valor="c2ln"),
        vence_em=AGORA + timedelta(days=90),
    )


async def _criar(
    sessoes: async_sessionmaker[AsyncSession], pedido: PedidoDeRelatorio
) -> PedidoDeRelatorio:
    async with sessoes() as sessao, sessao.begin():
        await SqlRepositorioDePedidos(sessao).criar(pedido)
    return pedido


async def _obter(sessoes: async_sessionmaker[AsyncSession], pedido_id: UUID) -> PedidoDeRelatorio:
    async with sessoes() as sessao:
        pedido = await SqlRepositorioDePedidos(sessao).obter(pedido_id)
    assert pedido is not None
    return pedido


# Tabela


async def test_pedido_pendente_e_gravado_com_filtros_e_escopo(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R1.1: o pedido nasce `pendente`; 005/R1.3: o escopo usado fica gravado nele."""
    usuario = await _usuario(sessoes)
    pedido = await _criar(sessoes, _pedido(usuario))

    gravado = await _obter(sessoes, pedido.id)

    assert gravado == pedido
    assert gravado.status is StatusDoPedido.PENDENTE
    assert gravado.escopo == ESCOPO_DISTRITO
    assert gravado.filtros == {"distrito_id": 3}
    assert gravado.criado_em == AGORA


async def test_obter_pedido_inexistente_devolve_none(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R1.1"""
    async with sessoes() as sessao:
        assert await SqlRepositorioDePedidos(sessao).obter(uuid7()) is None


async def test_filtros_e_escopo_vao_como_json_com_uuid_e_data_em_texto(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R1.3: o escopo gravado guarda as unidades (UUID) e os filtros guardam as datas da
    trilha; no JSONB, tupla vira lista e UUID e data viram texto."""
    usuario = await _usuario(sessoes)
    unidade = uuid7()
    pedido = replace(
        _pedido(usuario, tipo=TipoDeRelatorio.TRILHA_AUDITORIA),
        filtros={"de": date(2026, 1, 1), "ate": date(2026, 6, 30), "acao": None},
        escopo={"global": False, "areas": (), "distritos": (), "unidades": (unidade,)},
    )

    await _criar(sessoes, pedido)

    gravado = await _obter(sessoes, pedido.id)
    assert gravado.filtros == {"de": "2026-01-01", "ate": "2026-06-30", "acao": None}
    assert gravado.escopo == {
        "global": False,
        "areas": [],
        "distritos": [],
        "unidades": [str(unidade)],
    }


async def test_criar_so_aceita_pedido_pendente(sessoes: async_sessionmaker[AsyncSession]) -> None:
    """005/R1.1: o pedido nasce `pendente`; as outras etapas passam pelas transições."""
    usuario = await _usuario(sessoes)
    gerando = replace(_pedido(usuario), status=StatusDoPedido.GERANDO)

    with pytest.raises(ValueError, match="pendente"):
        async with sessoes() as sessao, sessao.begin():
            await SqlRepositorioDePedidos(sessao).criar(gerando)

    async with sessoes() as sessao:
        assert await SqlRepositorioDePedidos(sessao).obter(gerando.id) is None


@pytest.mark.parametrize(
    ("coluna", "valor"),
    [("tipo", "pacientes"), ("formato", "pdf"), ("status", "cancelado")],
)
async def test_tabela_recusa_valor_fora_das_listas_fechadas(
    sessoes: async_sessionmaker[AsyncSession], coluna: str, valor: str
) -> None:
    """005/R1.2: tipos `inventario_unidades` e `trilha_auditoria`, formatos `csv` e `xlsx`;
    status `pendente`, `gerando`, `concluido` e `falhou` (005/R1.1, R2.5)."""
    usuario = await _usuario(sessoes)
    valores = {"tipo": "trilha_auditoria", "formato": "csv", "status": "pendente"} | {coluna: valor}

    with pytest.raises(IntegrityError, match="ck_report_jobs_"):
        async with sessoes() as sessao, sessao.begin():
            await sessao.execute(
                text(INSERIR_PEDIDO.format(colunas="", valores="")),
                {"id": uuid7(), "usuario": usuario, **valores},
            )


@pytest.mark.parametrize(
    "faltando", ["storage_key", "sha256", "signature", "signature_alg", "signature_kid"]
)
async def test_concluido_exige_chave_hash_e_assinatura(
    sessoes: async_sessionmaker[AsyncSession], faltando: str
) -> None:
    """005/R2.5 e 005/R5.1: `concluido` só com a chave do objeto, o hash e a assinatura."""
    usuario = await _usuario(sessoes)
    completos = {
        "storage_key": "reports/x.csv",
        "sha256": SHA256_HEX,
        "signature": "c2ln",
        "signature_alg": "ES256",
        "signature_kid": "rel-2026-11",
    }
    colunas = [c for c in completos if c != faltando]

    with pytest.raises(IntegrityError, match="ck_report_jobs_concluido_completo"):
        async with sessoes() as sessao, sessao.begin():
            await sessao.execute(
                text(
                    INSERIR_PEDIDO.format(
                        colunas="".join(f", {c}" for c in colunas),
                        valores="".join(f", :{c}" for c in colunas),
                    )
                ),
                {
                    "id": uuid7(),
                    "usuario": usuario,
                    "tipo": "inventario_unidades",
                    "formato": "csv",
                    "status": "concluido",
                    **{c: completos[c] for c in colunas},
                },
            )


async def test_tabela_recusa_hash_que_nao_e_sha256_em_hex(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R2.5: o hash fica em hex, 64 caracteres (design § Modelo de dados)."""
    usuario = await _usuario(sessoes)

    with pytest.raises(IntegrityError, match="ck_report_jobs_sha256_hex"):
        async with sessoes() as sessao, sessao.begin():
            await sessao.execute(
                text(INSERIR_PEDIDO.format(colunas=", sha256", valores=", :sha256")),
                {
                    "id": uuid7(),
                    "usuario": usuario,
                    "tipo": "inventario_unidades",
                    "formato": "csv",
                    "status": "pendente",
                    "sha256": "AB" * 32,
                },
            )


async def test_indices_da_listagem_e_dos_pedidos_abertos_existem(banco: BancoDeTeste) -> None:
    """005/R3.5: listagem por solicitante, mais recente primeiro; 005/R2.6: pedidos abertos,
    marcados como interrompidos na subida."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'report_jobs'")
        )
        indices = {str(nome): str(definicao) for nome, definicao in linhas}
    await engine.dispose()

    assert "(requested_by, created_at DESC)" in indices["ix_report_jobs_requested_by_created_at"]
    aberto = indices["ix_report_jobs_status_aberto"]
    assert "(status)" in aberto
    assert "WHERE" in aberto
    assert "'pendente'" in aberto
    assert "'gerando'" in aberto


def _alembic(conexao: Connection, comando: Callable[[Config, str], None], revisao: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = conexao
    comando(config, revisao)


async def _migrar(url_dono: str, comando: Callable[[Config, str], None], revisao: str) -> None:
    engine = motor(url_dono)
    async with engine.connect() as conexao:
        await conexao.run_sync(_alembic, comando, revisao)
        await conexao.commit()
    await engine.dispose()


async def _tabelas(url_dono: str) -> set[str]:
    engine = motor(url_dono)
    async with engine.connect() as conexao:
        nomes = await conexao.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tabelas = {str(nome) for nome in nomes}
    await engine.dispose()
    return tabelas


async def test_downgrade_tira_so_a_report_jobs_e_o_upgrade_a_devolve(banco: BancoDeTeste) -> None:
    """005/T1 (design § Modelo de dados / migrações): a `0005_relatorios` desce até a
    `0004_diretorio` sem levar outra tabela e sobe de novo."""
    antes = await _tabelas(banco.url_dono)

    await _migrar(banco.url_dono, command.downgrade, "0004")
    sem_a_0005 = await _tabelas(banco.url_dono)
    await _migrar(banco.url_dono, command.upgrade, "head")

    assert "report_jobs" in antes
    assert sem_a_0005 == antes - {"report_jobs"}
    assert await _tabelas(banco.url_dono) == antes


# Transições


async def test_marca_gerando_so_se_pendente(sessoes: async_sessionmaker[AsyncSession]) -> None:
    """005/R1.1 (design § Geração e envio, passo 1): só um pedido `pendente` passa a `gerando`."""
    usuario = await _usuario(sessoes)
    pedido = await _criar(sessoes, _pedido(usuario))
    inicio = AGORA + timedelta(seconds=1)

    async with sessoes() as sessao, sessao.begin():
        primeira = await SqlRepositorioDePedidos(sessao).marcar_gerando(pedido.id, inicio)
    async with sessoes() as sessao, sessao.begin():
        segunda = await SqlRepositorioDePedidos(sessao).marcar_gerando(pedido.id, inicio)

    gravado = await _obter(sessoes, pedido.id)
    assert (primeira, segunda) == (True, False)
    assert gravado.status is StatusDoPedido.GERANDO
    assert gravado.iniciado_em == inicio
    assert gravado.atualizado_em == inicio


async def test_conclui_com_objeto_tamanho_hash_assinatura_e_vencimento(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R2.5: `concluido` com tamanho e hash; 005/R5.1: assinatura, algoritmo e `kid`."""
    usuario = await _usuario(sessoes)
    pedido = await _criar(sessoes, _pedido(usuario))
    fim = AGORA + timedelta(minutes=1)
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlRepositorioDePedidos(sessao)
        await repositorio.marcar_gerando(pedido.id, AGORA)
        concluiu = await repositorio.concluir(pedido.id, _conclusao(), fim)

    gravado = await _obter(sessoes, pedido.id)
    conclusao = _conclusao()
    assert concluiu is True
    assert gravado.status is StatusDoPedido.CONCLUIDO
    assert (gravado.bucket, gravado.chave, gravado.versao) == (
        conclusao.bucket,
        conclusao.chave,
        conclusao.versao,
    )
    assert (gravado.tamanho_bytes, gravado.sha256) == (4096, SHA256_HEX)
    assert gravado.assinatura == conclusao.assinatura
    assert (gravado.terminado_em, gravado.vence_em) == (fim, conclusao.vence_em)
    assert gravado.erro is None


@pytest.mark.parametrize("status", [StatusDoPedido.PENDENTE, StatusDoPedido.FALHOU])
async def test_so_conclui_pedido_gerando(
    sessoes: async_sessionmaker[AsyncSession], status: StatusDoPedido
) -> None:
    """005/R2.5: só a geração em andamento termina em `concluido`."""
    usuario = await _usuario(sessoes)
    pedido = await _criar(sessoes, _pedido(usuario))
    if status is StatusDoPedido.FALHOU:
        async with sessoes() as sessao, sessao.begin():
            await SqlRepositorioDePedidos(sessao).falhar(pedido.id, "Erro", AGORA)

    async with sessoes() as sessao, sessao.begin():
        concluiu = await SqlRepositorioDePedidos(sessao).concluir(pedido.id, _conclusao(), AGORA)

    assert concluiu is False
    assert (await _obter(sessoes, pedido.id)).status is status


@pytest.mark.parametrize("gerando", [False, True])
async def test_falha_grava_mensagem_generica(
    sessoes: async_sessionmaker[AsyncSession], gerando: bool
) -> None:
    """005/R2.6: `falhou` com a mensagem genérica, de `pendente` ou de `gerando`."""
    usuario = await _usuario(sessoes)
    pedido = await _criar(sessoes, _pedido(usuario))
    fim = AGORA + timedelta(minutes=2)
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlRepositorioDePedidos(sessao)
        if gerando:
            await repositorio.marcar_gerando(pedido.id, AGORA)
        falhou = await repositorio.falhar(pedido.id, "Não foi possível gerar o relatório", fim)

    gravado = await _obter(sessoes, pedido.id)
    assert falhou is True
    assert gravado.status is StatusDoPedido.FALHOU
    assert gravado.erro == "Não foi possível gerar o relatório"
    assert gravado.terminado_em == fim


async def test_falha_corta_a_mensagem_no_tamanho_da_coluna(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R2.6: a falha é gravada mesmo com mensagem longa, cortada em 200 caracteres, para o
    pedido não ficar preso em `gerando`."""
    usuario = await _usuario(sessoes)
    pedido = await _criar(sessoes, _pedido(usuario))

    async with sessoes() as sessao, sessao.begin():
        falhou = await SqlRepositorioDePedidos(sessao).falhar(pedido.id, "x" * 250, AGORA)

    gravado = await _obter(sessoes, pedido.id)
    assert falhou is True
    assert gravado.erro == "x" * ERRO_MAX


async def test_falha_nao_desfaz_pedido_concluido(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R2.5: um relatório concluído não volta a `falhou`."""
    usuario = await _usuario(sessoes)
    pedido = await _criar(sessoes, _pedido(usuario))
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlRepositorioDePedidos(sessao)
        await repositorio.marcar_gerando(pedido.id, AGORA)
        await repositorio.concluir(pedido.id, _conclusao(), AGORA)

    async with sessoes() as sessao, sessao.begin():
        falhou = await SqlRepositorioDePedidos(sessao).falhar(pedido.id, "Erro", AGORA)

    gravado = await _obter(sessoes, pedido.id)
    assert falhou is False
    assert gravado.status is StatusDoPedido.CONCLUIDO
    assert gravado.erro is None


async def test_pedidos_interrompidos_viram_falhou_na_subida(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R2.6 (design § Geração e envio, passo 8): na subida, `pendente` e `gerando` viram
    `falhou` com "Interrompido"; concluídos e falhos ficam como estão."""
    usuario = await _usuario(sessoes)
    pendente = await _criar(sessoes, _pedido(usuario))
    gerando = await _criar(sessoes, _pedido(usuario))
    concluido = await _criar(sessoes, _pedido(usuario))
    async with sessoes() as sessao, sessao.begin():
        repositorio = SqlRepositorioDePedidos(sessao)
        await repositorio.marcar_gerando(gerando.id, AGORA)
        await repositorio.marcar_gerando(concluido.id, AGORA)
        await repositorio.concluir(concluido.id, _conclusao(), AGORA)
    subida = AGORA + timedelta(hours=1)

    async with sessoes() as sessao, sessao.begin():
        interrompidos = await SqlRepositorioDePedidos(sessao).marcar_interrompidos(subida)

    assert set(interrompidos) == {pendente.id, gerando.id}
    for pedido_id in (pendente.id, gerando.id):
        gravado = await _obter(sessoes, pedido_id)
        assert gravado.status is StatusDoPedido.FALHOU
        assert gravado.erro == ERRO_INTERROMPIDO
        assert gravado.terminado_em == subida
    assert (await _obter(sessoes, concluido.id)).status is StatusDoPedido.CONCLUIDO


# Listagem


async def test_lista_os_pedidos_do_usuario_mais_recente_primeiro_com_total(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R3.5: os pedidos do usuário, do mais recente ao mais antigo, paginados e com total."""
    maria = await _usuario(sessoes, "maria")
    joao = await _usuario(sessoes, "joao")
    da_maria = [
        await _criar(sessoes, _pedido(maria, agora=AGORA + timedelta(minutes=i))) for i in range(3)
    ]
    await _criar(sessoes, _pedido(joao))

    async with sessoes() as sessao:
        repositorio = SqlRepositorioDePedidos(sessao)
        primeira, total = await repositorio.listar(
            solicitado_por=maria, status=None, pagina=Pagina(numero=1, tamanho=2)
        )
        segunda, _ = await repositorio.listar(
            solicitado_por=maria, status=None, pagina=Pagina(numero=2, tamanho=2)
        )

    assert total == 3
    assert [p.id for p in primeira] == [da_maria[2].id, da_maria[1].id]
    assert [p.id for p in segunda] == [da_maria[0].id]


async def test_lista_todos_os_pedidos_e_filtra_por_status(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """005/R3.5: sem solicitante, a listagem traz os pedidos de todos (`GESTOR_DADOS`)."""
    maria = await _usuario(sessoes, "maria")
    joao = await _usuario(sessoes, "joao")
    da_maria = await _criar(sessoes, _pedido(maria))
    do_joao = await _criar(sessoes, _pedido(joao, agora=AGORA + timedelta(minutes=1)))
    async with sessoes() as sessao, sessao.begin():
        await SqlRepositorioDePedidos(sessao).marcar_gerando(do_joao.id, AGORA)

    async with sessoes() as sessao:
        repositorio = SqlRepositorioDePedidos(sessao)
        todos, total = await repositorio.listar(
            solicitado_por=None, status=None, pagina=Pagina(numero=1, tamanho=10)
        )
        pendentes, total_pendentes = await repositorio.listar(
            solicitado_por=None, status=StatusDoPedido.PENDENTE, pagina=Pagina(numero=1, tamanho=10)
        )

    assert (total, [p.id for p in todos]) == (2, [do_joao.id, da_maria.id])
    assert (total_pendentes, [p.id for p in pendentes]) == (1, [da_maria.id])
