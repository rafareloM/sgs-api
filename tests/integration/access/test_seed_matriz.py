"""Catálogo de papéis e permissões semeado pela migração 0003_access (003/T1).

A matriz esperada é a de docs/architecture/arquitetura-conceitual.md § 4, copiada à mão: o teste
confere a migração contra o documento, e não contra ela mesma.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.postgres import BancoDeTeste, motor

SEM_PRIVILEGIO = "42501"  # SQLSTATE insufficient_privilege
G, A, D, U = "global", "area", "distrito", "unidade"

# Uma entrada por célula preenchida da matriz; célula "—" é permissão ausente no papel.
# `relatorio:export` do AUDITOR é "G (só auditoria)": o recorte por tipo de relatório é da 005.
MATRIZ: dict[str, dict[str, str]] = {
    "ADMIN_TI": {
        "auditoria:read_acessos": G,
        "usuario:manage": G,
        "papel:assign": G,
        "diretorio:sync": G,
    },
    "GESTOR_DADOS": {
        "unidade:read": G,
        "unidade:create": G,
        "unidade:update": G,
        "unidade:deactivate": G,
        "equipamento:write": G,
        "servico:write": G,
        "alteracao:propor": G,
        "alteracao:validar": G,
        "regra_validacao:manage": G,
        "auditoria:read": G,
        "dashboard:read": G,
        "relatorio:export": G,
        "relatorio:download": G,
    },
    "COORD_TECNICO": {
        "unidade:read": G,
        "unidade:create": A,
        "unidade:update": A,
        "equipamento:write": A,
        "servico:write": A,
        "alteracao:propor": A,
        "alteracao:validar": A,
        "auditoria:read": A,
        "dashboard:read": G,
        "relatorio:export": A,
        "relatorio:download": A,
    },
    "TECNICO_DISTRITAL": {
        "unidade:read": G,
        "unidade:update": D,
        "equipamento:write": D,
        "servico:write": D,
        "alteracao:propor": D,
        "auditoria:read": D,
        "dashboard:read": G,
    },
    "GESTOR_UNIDADE": {
        "unidade:read": G,
        "unidade:update": U,
        "equipamento:write": U,
        "servico:write": U,
        "alteracao:propor": U,
        "auditoria:read": U,
        "dashboard:read": G,
    },
    "DIRETORIA": {
        "unidade:read": G,
        "dashboard:read": G,
        "relatorio:export": G,
        "relatorio:download": G,
    },
    "AUDITOR": {
        "unidade:read": G,
        "auditoria:read": G,
        "auditoria:read_acessos": G,
        "relatorio:export": G,
        "relatorio:download": G,
    },
}

# As linhas da matriz, com `equipamento:write` / `servico:write` separadas.
PERMISSOES = {
    "unidade:read",
    "unidade:create",
    "unidade:update",
    "unidade:deactivate",
    "equipamento:write",
    "servico:write",
    "alteracao:propor",
    "alteracao:validar",
    "regra_validacao:manage",
    "auditoria:read",
    "auditoria:read_acessos",
    "dashboard:read",
    "relatorio:export",
    "relatorio:download",
    "usuario:manage",
    "papel:assign",
    "diretorio:sync",
}


async def test_migracao_cria_os_sete_papeis_de_sistema(banco: BancoDeTeste) -> None:
    """003/R1.1"""
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(text("SELECT code, is_system FROM roles"))
        papeis: dict[str, bool] = dict(linhas.all())
    await engine.dispose()

    assert papeis == dict.fromkeys(MATRIZ, True)


async def test_migracao_cria_as_permissoes_da_matriz(banco: BancoDeTeste) -> None:
    """003/R1.1"""
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        permissoes = set(await conexao.scalars(text("SELECT code FROM permissions")))
    await engine.dispose()

    assert permissoes == PERMISSOES


@pytest.mark.parametrize("papel", MATRIZ)
async def test_cada_permissao_do_papel_tem_o_escopo_maximo_da_matriz(
    banco: BancoDeTeste, papel: str
) -> None:
    """003/R1.1, 003/R1.2"""
    engine = motor(banco.url_api)
    async with engine.connect() as conexao:
        linhas = await conexao.execute(
            text(
                "SELECT p.code, rp.max_scope FROM role_permissions rp"
                " JOIN roles r ON r.id = rp.role_id"
                " JOIN permissions p ON p.id = rp.permission_id"
                " WHERE r.code = :papel"
            ),
            {"papel": papel},
        )
        escopos: dict[str, str] = dict(linhas.all())
    await engine.dispose()

    assert escopos == MATRIZ[papel]


async def test_escopo_maximo_fora_dos_quatro_niveis_e_recusado(banco: BancoDeTeste) -> None:
    """003/R1.2"""
    engine = motor(banco.url_dono)
    with pytest.raises(IntegrityError, match="ck_role_permissions_escopo_maximo_valido"):
        async with engine.begin() as conexao:
            await conexao.execute(
                text(
                    "UPDATE role_permissions SET max_scope = 'estado'"
                    " WHERE role_id = (SELECT id FROM roles WHERE code = 'GESTOR_DADOS')"
                )
            )
    await engine.dispose()


async def _papeis_de_sistema(banco: BancoDeTeste) -> set[str]:
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        papeis = set(await conexao.scalars(text("SELECT code FROM roles WHERE is_system")))
    await engine.dispose()
    return papeis


@pytest.mark.parametrize(
    "comando",
    [
        "DELETE FROM roles WHERE code = 'AUDITOR'",
        # Desmarcar o papel para apagá-lo depois também conta como apagar.
        "UPDATE roles SET is_system = false WHERE code = 'AUDITOR'",
        "TRUNCATE roles CASCADE",
    ],
    ids=["delete", "desmarca", "truncate"],
)
async def test_papel_de_sistema_nao_e_apagado_nem_pelo_dono(
    banco: BancoDeTeste, comando: str
) -> None:
    """003/R1.3"""
    engine = motor(banco.url_dono)
    with pytest.raises(DBAPIError, match="papel de sistema"):
        async with engine.begin() as conexao:
            await conexao.execute(text(comando))
    await engine.dispose()

    assert await _papeis_de_sistema(banco) == set(MATRIZ)


@pytest.mark.parametrize(
    "comando",
    [
        "DELETE FROM roles WHERE code = 'AUDITOR'",
        "UPDATE role_permissions SET max_scope = 'global'",
        "INSERT INTO permissions (id, code, description) VALUES (gen_random_uuid(), 'x:y', 'x')",
    ],
    ids=["apaga-papel", "amplia-escopo", "cria-permissao"],
)
async def test_login_da_api_so_le_o_catalogo(banco: BancoDeTeste, comando: str) -> None:
    """003/R1.1, 003/R1.3: o catálogo vem da migração; a API não o altera."""
    engine = motor(banco.url_api)
    with pytest.raises(DBAPIError) as erro:
        async with engine.begin() as conexao:
            await conexao.execute(text(comando))
    await engine.dispose()

    assert getattr(erro.value.orig, "sqlstate", None) == SEM_PRIVILEGIO
    assert await _papeis_de_sistema(banco) == set(MATRIZ)
