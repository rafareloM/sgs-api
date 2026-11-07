"""Permissões efetivas resolvidas do banco, com cache e `users.authz_version` (003/T3).

Design da 003 § Resolução de permissões: atribuições ativas (diretas e de grupo, não expiradas)
juntas com `role_permissions`, cada escopo limitado pelo `max_scope` da permissão no papel, e
cache por usuário que a versão invalida.

A matriz esperada é a de docs/architecture/arquitetura-conceitual.md § 4, copiada à mão.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.ids import uuid7
from src.modules.access.application.permissoes import ResolvedorDePermissoes
from src.modules.access.domain.authorization import Area, Distrito, Escopo, Global, Unidade
from src.modules.access.infrastructure.repository import SqlRepositorioDePermissoes
from tests.integration.postgres import BancoDeTeste, motor

SAUDE_MENTAL = 1
DS_III = 3
CAPS_DS_III = UUID("01970000-0000-7000-8000-000000000001")

PAPEIS = (
    "ADMIN_TI",
    "GESTOR_DADOS",
    "COORD_TECNICO",
    "TECNICO_DISTRITAL",
    "GESTOR_UNIDADE",
    "DIRETORIA",
    "AUDITOR",
)

# G = global · A = na sua área técnica · D = no seu distrito · U = na sua unidade
# - = sem permissão. Colunas na ordem de PAPEIS.
MATRIZ: dict[str, tuple[str, ...]] = {
    "unidade:read":           ("-", "G", "G", "G", "G", "G", "G"),
    "unidade:create":         ("-", "G", "A", "-", "-", "-", "-"),
    "unidade:update":         ("-", "G", "A", "D", "U", "-", "-"),
    "unidade:deactivate":     ("-", "G", "-", "-", "-", "-", "-"),
    "equipamento:write":      ("-", "G", "A", "D", "U", "-", "-"),
    "servico:write":          ("-", "G", "A", "D", "U", "-", "-"),
    "alteracao:propor":       ("-", "G", "A", "D", "U", "-", "-"),
    "alteracao:validar":      ("-", "G", "A", "-", "-", "-", "-"),
    "regra_validacao:manage": ("-", "G", "-", "-", "-", "-", "-"),
    "auditoria:read":         ("-", "G", "A", "D", "U", "-", "G"),
    "auditoria:read_acessos": ("G", "-", "-", "-", "-", "-", "G"),
    "dashboard:read":         ("-", "G", "G", "G", "G", "G", "-"),
    "relatorio:export":       ("-", "G", "A", "-", "-", "G", "G"),
    "relatorio:download":     ("-", "G", "A", "-", "-", "G", "G"),
    "usuario:manage":         ("G", "-", "-", "-", "-", "-", "-"),
    "papel:assign":           ("G", "-", "-", "-", "-", "-", "-"),
    "diretorio:sync":         ("G", "-", "-", "-", "-", "-", "-"),
}  # fmt: skip

# Escopo típico de cada papel (arquitetura § 2), como a atribuição o grava: (scope_type, scope_id).
ATRIBUICAO_TIPICA: dict[str, tuple[str, str | None]] = {
    "ADMIN_TI": ("global", None),
    "GESTOR_DADOS": ("global", None),
    "COORD_TECNICO": ("area", str(SAUDE_MENTAL)),
    "TECNICO_DISTRITAL": ("distrito", str(DS_III)),
    "GESTOR_UNIDADE": ("unidade", str(CAPS_DS_III)),
    "DIRETORIA": ("global", None),
    "AUDITOR": ("global", None),
}
ESCOPO_DA_LETRA: dict[str, Escopo] = {
    "G": Global(),
    "A": Area(SAUDE_MENTAL),
    "D": Distrito(DS_III),
    "U": Unidade(CAPS_DS_III),
}

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


class Relogio:
    """Relógio parado que o teste adianta."""

    def __init__(self) -> None:
        self.agora = AGORA

    def __call__(self) -> datetime:
        return self.agora


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessões com o login da API (papel sgs_app), como em produção."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _novo_usuario(sessoes: async_sessionmaker[AsyncSession]) -> UUID:
    usuario = uuid7()
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text(
                "INSERT INTO users (id, username, display_name, source, external_id)"
                " VALUES (:id, :nome, 'Usuário de teste', 'ldap', :dn)"
            ),
            {"id": usuario, "nome": f"u{usuario.hex}", "dn": f"uid={usuario.hex},ou=pessoas"},
        )
    return usuario


async def _atribuir(
    sessao: AsyncSession,
    usuario: UUID,
    papel: str,
    escopo: tuple[str, str | None],
    *,
    valido_ate: datetime | None = None,
) -> UUID:
    atribuicao = uuid7()
    await sessao.execute(
        text(
            "INSERT INTO role_assignments"
            " (id, user_id, role_id, scope_type, scope_id, origin, valid_until)"
            " SELECT :id, :usuario, id, :tipo, :id_do_escopo, 'direct', :valido_ate"
            " FROM roles WHERE code = :papel"
        ),
        {
            "id": atribuicao,
            "usuario": usuario,
            "tipo": escopo[0],
            "id_do_escopo": escopo[1],
            "valido_ate": valido_ate,
            "papel": papel,
        },
    )
    return atribuicao


async def _resolver(
    resolvedor: ResolvedorDePermissoes,
    sessoes: async_sessionmaker[AsyncSession],
    usuario: UUID,
) -> dict[str, set[Escopo]]:
    """Uma requisição: sessão nova, permissões do usuário como conjuntos (a ordem não importa)."""
    async with sessoes() as sessao:
        permissoes = await resolvedor.permissoes_de(SqlRepositorioDePermissoes(sessao), usuario)
    return _como_conjuntos(permissoes)


def _como_conjuntos(permissoes: Mapping[str, Sequence[Escopo]]) -> dict[str, set[Escopo]]:
    return {codigo: set(escopos) for codigo, escopos in permissoes.items()}


def _esperado(papel: str) -> dict[str, set[Escopo]]:
    coluna = PAPEIS.index(papel)
    return {
        perm: {ESCOPO_DA_LETRA[linha[coluna]]}
        for perm, linha in MATRIZ.items()
        if linha[coluna] != "-"
    }


@pytest.mark.parametrize("papel", PAPEIS)
async def test_papel_no_escopo_tipico_da_as_permissoes_da_matriz(
    sessoes: async_sessionmaker[AsyncSession], papel: str
) -> None:
    """003/R1.2, 003/R4.3: `G` vale em todo lugar; `A`, `D` e `U`, no escopo da atribuição."""
    usuario = await _novo_usuario(sessoes)
    async with sessoes() as sessao, sessao.begin():
        await _atribuir(sessao, usuario, papel, ATRIBUICAO_TIPICA[papel])

    permissoes = await _resolver(ResolvedorDePermissoes(relogio=Relogio()), sessoes, usuario)

    assert permissoes == _esperado(papel)


async def test_mudanca_sem_nova_versao_so_aparece_depois_de_30_segundos(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """003/R4.5: design § Resolução, passo 3 (cache de 30 s por usuário)."""
    relogio = Relogio()
    resolvedor = ResolvedorDePermissoes(relogio=relogio)
    usuario = await _novo_usuario(sessoes)
    async with sessoes() as sessao, sessao.begin():
        await _atribuir(sessao, usuario, "DIRETORIA", ("global", None))
    assert await _resolver(resolvedor, sessoes, usuario) == _esperado("DIRETORIA")

    # Alteração feita direto no banco, sem incrementar a versão.
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            text("DELETE FROM role_assignments WHERE user_id = :usuario"), {"usuario": usuario}
        )
    relogio.agora += timedelta(seconds=29)
    assert await _resolver(resolvedor, sessoes, usuario) == _esperado("DIRETORIA")

    relogio.agora += timedelta(seconds=1)
    assert await _resolver(resolvedor, sessoes, usuario) == {}


async def test_papel_removido_deixa_de_valer_na_proxima_requisicao(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """003/R4.5: a remoção incrementa `users.authz_version` e o cache não espera os 30 s."""
    resolvedor = ResolvedorDePermissoes(relogio=Relogio())
    usuario = await _novo_usuario(sessoes)
    async with sessoes() as sessao, sessao.begin():
        await _atribuir(sessao, usuario, "TECNICO_DISTRITAL", ("distrito", str(DS_III)))
        gestor = await _atribuir(sessao, usuario, "GESTOR_UNIDADE", ("unidade", str(CAPS_DS_III)))
    antes = await _resolver(resolvedor, sessoes, usuario)
    assert antes["unidade:update"] == {Distrito(DS_III), Unidade(CAPS_DS_III)}

    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(text("DELETE FROM role_assignments WHERE id = :id"), {"id": gestor})
        await SqlRepositorioDePermissoes(sessao).invalidar(usuario)

    assert await _resolver(resolvedor, sessoes, usuario) == _esperado("TECNICO_DISTRITAL")


async def test_papel_concedido_vale_na_proxima_requisicao(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """003/R4.5: a concessão também invalida o cache."""
    resolvedor = ResolvedorDePermissoes(relogio=Relogio())
    usuario = await _novo_usuario(sessoes)
    assert await _resolver(resolvedor, sessoes, usuario) == {}

    async with sessoes() as sessao, sessao.begin():
        await _atribuir(sessao, usuario, "AUDITOR", ("global", None))
        await SqlRepositorioDePermissoes(sessao).invalidar(usuario)

    assert await _resolver(resolvedor, sessoes, usuario) == _esperado("AUDITOR")


async def test_atribuicao_expirada_nao_conta_nem_no_cache(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """003/R2.3: a atribuição deixa de valer no `valid_until`, sem esperar os 30 s do cache."""
    relogio = Relogio()
    resolvedor = ResolvedorDePermissoes(relogio=relogio)
    usuario = await _novo_usuario(sessoes)
    async with sessoes() as sessao, sessao.begin():
        await _atribuir(
            sessao, usuario, "AUDITOR", ("global", None), valido_ate=AGORA - timedelta(days=1)
        )
        await _atribuir(
            sessao, usuario, "DIRETORIA", ("global", None), valido_ate=AGORA + timedelta(seconds=10)
        )
    assert await _resolver(resolvedor, sessoes, usuario) == _esperado("DIRETORIA")

    relogio.agora += timedelta(seconds=10)
    assert await _resolver(resolvedor, sessoes, usuario) == {}


async def test_atribuicao_derivada_de_grupo_vale_como_a_direta(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """003/R3.1: design § Resolução, passo 1 (atribuições diretas e derivadas de grupo)."""
    usuario = await _novo_usuario(sessoes)
    async with sessoes() as sessao, sessao.begin():
        mapeamento = await sessao.scalar(
            text(
                "INSERT INTO group_role_mappings"
                " (id, group_id, role_id, scope_type, scope_id, created_by)"
                " SELECT :id, :grupo, id, 'distrito', :distrito, :usuario"
                " FROM roles WHERE code = 'TECNICO_DISTRITAL' RETURNING id"
            ),
            {"id": uuid7(), "grupo": uuid7(), "distrito": str(DS_III), "usuario": usuario},
        )
        await sessao.execute(
            text(
                "INSERT INTO role_assignments"
                " (id, user_id, role_id, scope_type, scope_id, origin, group_mapping_id)"
                " SELECT :id, :usuario, role_id, scope_type, scope_id, 'group', id"
                " FROM group_role_mappings WHERE id = :mapeamento"
            ),
            {"id": uuid7(), "usuario": usuario, "mapeamento": mapeamento},
        )

    permissoes = await _resolver(ResolvedorDePermissoes(relogio=Relogio()), sessoes, usuario)

    assert permissoes == _esperado("TECNICO_DISTRITAL")


async def test_usuario_inexistente_nao_tem_permissao(
    sessoes: async_sessionmaker[AsyncSession],
) -> None:
    """003/R4.2: deny by default."""
    permissoes = await _resolver(ResolvedorDePermissoes(relogio=Relogio()), sessoes, uuid7())

    assert permissoes == {}
