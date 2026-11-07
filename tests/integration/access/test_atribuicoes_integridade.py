"""O banco recusa atribuição de papel incoerente (003/T1, modelo-dados.md § 1)."""

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.ids import uuid7
from tests.integration.postgres import BancoDeTeste, motor

UNIDADE = str(uuid7())

INSERIR_ATRIBUICAO = text(
    "INSERT INTO role_assignments"
    " (id, user_id, role_id, scope_type, scope_id, origin, group_mapping_id)"
    " SELECT :id, :usuario, id, :escopo, :id_do_escopo, :origem, :mapeamento"
    " FROM roles WHERE code = 'TECNICO_DISTRITAL'"
)


async def _usuario_e_mapeamento(engine: AsyncEngine) -> tuple[UUID, UUID]:
    usuario, mapeamento = uuid7(), uuid7()
    async with engine.begin() as conexao:
        await conexao.execute(
            text(
                "INSERT INTO users (id, username, display_name, source, external_id)"
                " VALUES (:id, 'tecnico', 'Técnico', 'ldap', 'uid=tecnico,ou=pessoas')"
            ),
            {"id": usuario},
        )
        await conexao.execute(
            text(
                "INSERT INTO group_role_mappings (id, group_id, role_id, scope_type, created_by)"
                " SELECT :id, :grupo, id, 'global', :usuario FROM roles WHERE code = 'DIRETORIA'"
            ),
            {"id": mapeamento, "grupo": uuid7(), "usuario": usuario},
        )
    return usuario, mapeamento


def _atribuicao(
    usuario: UUID,
    mapeamento: UUID,
    escopo: str,
    id_do_escopo: str | None,
    origem: str,
    com_mapeamento: bool,
) -> dict[str, object]:
    return {
        "id": uuid7(),
        "usuario": usuario,
        "escopo": escopo,
        "id_do_escopo": id_do_escopo,
        "origem": origem,
        "mapeamento": mapeamento if com_mapeamento else None,
    }


@pytest.mark.parametrize(
    ("escopo", "id_do_escopo", "origem", "com_mapeamento"),
    [
        ("global", None, "direct", False),
        ("distrito", "3", "group", True),
        ("unidade", UNIDADE, "direct", False),
    ],
    ids=["global-direta", "distrito-de-grupo", "unidade-direta"],
)
async def test_atribuicao_coerente_e_aceita(
    banco: BancoDeTeste,
    escopo: str,
    id_do_escopo: str | None,
    origem: str,
    com_mapeamento: bool,
) -> None:
    """003/T1: o caso válido de cada combinação passa (controle do teste abaixo)."""
    engine = motor(banco.url_dono)
    usuario, mapeamento = await _usuario_e_mapeamento(engine)
    async with engine.begin() as conexao:
        await conexao.execute(
            INSERIR_ATRIBUICAO,
            _atribuicao(usuario, mapeamento, escopo, id_do_escopo, origem, com_mapeamento),
        )
        total = await conexao.scalar(text("SELECT count(*) FROM role_assignments"))
    await engine.dispose()

    assert total == 1


@pytest.mark.parametrize(
    ("escopo", "id_do_escopo", "origem", "com_mapeamento", "restricao"),
    [
        ("global", "3", "direct", False, "ck_role_assignments_escopo_conforme_tipo"),
        ("unidade", None, "direct", False, "ck_role_assignments_escopo_conforme_tipo"),
        ("estado", "3", "direct", False, "ck_role_assignments_escopo_valido"),
        ("distrito", "3", "group", False, "ck_role_assignments_origem_conforme_mapeamento"),
        ("unidade", UNIDADE, "direct", True, "ck_role_assignments_origem_conforme_mapeamento"),
    ],
    ids=[
        "global-com-id",
        "unidade-sem-id",
        "nivel-desconhecido",
        "grupo-sem-mapeamento",
        "direta-com-mapeamento",
    ],
)
async def test_atribuicao_incoerente_e_recusada(
    banco: BancoDeTeste,
    escopo: str,
    id_do_escopo: str | None,
    origem: str,
    com_mapeamento: bool,
    restricao: str,
) -> None:
    """003/T1: escopo global sem id, os demais com id; derivada de grupo aponta o mapeamento."""
    engine = motor(banco.url_dono)
    usuario, mapeamento = await _usuario_e_mapeamento(engine)

    with pytest.raises(IntegrityError, match=restricao):
        async with engine.begin() as conexao:
            await conexao.execute(
                INSERIR_ATRIBUICAO,
                _atribuicao(usuario, mapeamento, escopo, id_do_escopo, origem, com_mapeamento),
            )
    await engine.dispose()
