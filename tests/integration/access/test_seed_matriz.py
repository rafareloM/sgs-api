"""Catálogo de papéis e permissões semeado pela migração 0003_access (003/T1).

A matriz esperada é a de docs/architecture/arquitetura-conceitual.md § 4, copiada à mão em
`tests/fixtures/matriz.py`: o teste confere a migração contra o documento, e não contra ela
mesma. `relatorio:export` do AUDITOR é "G (só auditoria)": o recorte por tipo de relatório é da
005.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.fixtures.matriz import MATRIZ as LINHAS_DA_MATRIZ
from tests.fixtures.matriz import PAPEIS, escopos_maximos
from tests.integration.postgres import BancoDeTeste, motor

SEM_PRIVILEGIO = "42501"  # SQLSTATE insufficient_privilege

# Uma entrada por célula preenchida da matriz; célula "-" é permissão ausente no papel.
MATRIZ: dict[str, dict[str, str]] = {papel: escopos_maximos(papel) for papel in PAPEIS}

# As linhas da matriz, com `equipamento:write` / `servico:write` separadas.
PERMISSOES = set(LINHAS_DA_MATRIZ)


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
