"""Privilégio mínimo no banco: papel dono, EXECUTE e índices da 0011 (011/T3).

Consultas ao catálogo pelo dono do banco (o superusuário que migra) e, onde importa quem executa,
pelo login da API.
"""

import pytest
from sqlalchemy import text

from tests.integration.postgres import LOGIN_DA_API, BancoDeTeste, motor

# O que as funções do dono (DEFINER) leem, pela tabela do design da 011 § Na 0011, item 1.
LIDAS_PELAS_FUNCOES_DO_DONO = (
    "health_units",
    "equipments",
    "services",
    "users",
    "audit_log",
    "districts",
    "unit_types",
    "technical_areas",
)


async def test_papel_dono_nao_tem_login_nem_superusuario(banco: BancoDeTeste) -> None:
    """011/R10.2: as funções que rodam com privilégio do dono pertencem a um papel sem login."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text("SELECT rolcanlogin, rolsuper FROM pg_roles WHERE rolname = 'sgs_owner'")
        )
        papel = linha.one_or_none()
    await engine.dispose()

    assert papel is not None
    assert tuple(papel) == (False, False)


async def test_papel_dono_cria_no_schema(banco: BancoDeTeste) -> None:
    """011/R10.2: o `sgs_owner` usa e cria objetos no schema `public` (log e funções, T7 e T8)."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_schema_privilege('sgs_owner', 'public', 'USAGE'),"
                " has_schema_privilege('sgs_owner', 'public', 'CREATE')"
            )
        )
        uso, criacao = linha.one()
    await engine.dispose()

    assert (uso, criacao) == (True, True)


@pytest.mark.parametrize("tabela", LIDAS_PELAS_FUNCOES_DO_DONO)
async def test_papel_dono_so_le_as_tabelas_que_as_funcoes_usam(
    banco: BancoDeTeste, tabela: str
) -> None:
    """011/R10.2: SELECT, e nenhuma escrita, nas tabelas que as funções do dono leem."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_table_privilege('sgs_owner', CAST(:tabela AS regclass), 'SELECT'),"
                " has_table_privilege('sgs_owner', CAST(:tabela AS regclass),"
                " 'INSERT, UPDATE, DELETE, TRUNCATE')"
            ),
            {"tabela": tabela},
        )
        leitura, escrita = linha.one()
    await engine.dispose()

    assert (leitura, escrita) == (True, False)


# Quem cria funções e procedimentos na 0011: o dono do banco, que roda as migrações (`sgs` no
# compose; o superusuário do container nos testes), e o `sgs_owner` (011/T7, T8).
CRIADORES = {"dono-das-migracoes": None, "sgs_owner": "sgs_owner"}
ROTINAS = {
    "funcao": (
        "CREATE FUNCTION fn_criada_no_teste() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        "fn_criada_no_teste()",
    ),
    "procedimento": (
        "CREATE PROCEDURE sp_criado_no_teste() LANGUAGE sql AS 'SELECT 1'",
        "sp_criado_no_teste()",
    ),
}


@pytest.mark.parametrize("papel", CRIADORES.values(), ids=CRIADORES.keys())
@pytest.mark.parametrize(("criacao", "assinatura"), ROTINAS.values(), ids=ROTINAS.keys())
async def test_rotina_nova_nasce_sem_execute_para_public(
    banco: BancoDeTeste, papel: str | None, criacao: str, assinatura: str
) -> None:
    """011/R10.1: por default privileges, nenhuma função ou procedimento novo é de todo usuário."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        if papel is not None:
            await conexao.execute(text(f"SET LOCAL ROLE {papel}"))
        await conexao.execute(text(criacao))
        publico = await conexao.scalar(
            text("SELECT has_function_privilege('public', :assinatura, 'EXECUTE')"),
            {"assinatura": assinatura},
        )
        await conexao.rollback()
    await engine.dispose()

    assert publico is False


# As rotinas que a aplicação executa (design da 011 § Segurança); `sp_deactivate_unit` entra na
# 011/T6.
DA_APLICACAO = {
    "fn_normalize_name": "fn_normalize_name(text)",
    "fn_registration_status": "fn_registration_status(health_units)",
}


@pytest.mark.parametrize("assinatura", DA_APLICACAO.values(), ids=DA_APLICACAO.keys())
async def test_so_a_aplicacao_executa_as_rotinas_liberadas(
    banco: BancoDeTeste, assinatura: str
) -> None:
    """011/R10.1: EXECUTE para o `sgs_app` e o login da API; nenhum para PUBLIC."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        linha = await conexao.execute(
            text(
                "SELECT has_function_privilege('public', :assinatura, 'EXECUTE'),"
                " has_function_privilege('sgs_app', :assinatura, 'EXECUTE'),"
                " has_function_privilege(:login, :assinatura, 'EXECUTE')"
            ),
            {"assinatura": assinatura, "login": LOGIN_DA_API},
        )
        publico, aplicacao, login = linha.one()
    await engine.dispose()

    assert (publico, aplicacao, login) == (False, True, True)


# Definições do design da 011 § Na 0011, itens 3 e 4, como o PostgreSQL as devolve.
INDICES = {
    "ix_audit_log_entity": (
        "011/R1.1",
        "CREATE INDEX ix_audit_log_entity ON public.audit_log"
        " USING btree (entity_type, entity_id, occurred_at DESC)",
    ),
    "ix_services_unit_id": (
        "011/R1.2",
        "CREATE INDEX ix_services_unit_id ON public.services USING btree (unit_id)",
    ),
}


@pytest.mark.parametrize(("requisito", "definicao"), INDICES.values(), ids=INDICES.keys())
async def test_indices_das_consultas_por_unidade_existem(
    banco: BancoDeTeste, requisito: str, definicao: str
) -> None:
    """011/R1.1 (histórico por entidade, mais recente primeiro) e 011/R1.2 (serviços da unidade).

    O uso dos índices com volume de demonstração é provado à parte (011/T9, `test_indices.py`).
    """
    nome = definicao.split()[2]
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        no_banco = await conexao.scalar(
            text(
                "SELECT pg_get_indexdef(oid) FROM pg_class WHERE relname = :nome AND relkind = 'i'"
            ),
            {"nome": nome},
        )
    await engine.dispose()

    assert no_banco == definicao, requisito
