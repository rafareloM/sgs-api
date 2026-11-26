"""Plano da sincronização do diretório, função pura do domínio (004/T12).

Design § Portas e adaptadores e § Fluxo > Sincronização; D004-11 (conflito também por `username`).
"""

from dataclasses import fields
from uuid import UUID, uuid4

from hypothesis import given
from hypothesis import strategies as st

from src.modules.identity.domain.diretorio import DirectoryGroup, DirectorySnapshot, DirectoryUser
from src.modules.identity.domain.sincronizacao import (
    Conflito,
    EstadoLocal,
    GrupoLocal,
    PlanoDeSincronizacao,
    TipoConflito,
    UsuarioLocal,
    planejar,
)
from src.modules.identity.domain.users import UserSource

BASE_PESSOAS = "ou=pessoas,dc=recife,dc=pe,dc=gov,dc=br"
BASE_GRUPOS = "ou=grupos,dc=recife,dc=pe,dc=gov,dc=br"


def _dn(login: str) -> str:
    return f"uid={login},{BASE_PESSOAS}"


def make_dir_user(
    login: str, *, email: str | None = "", nome: str | None = None, external_id: str | None = None
) -> DirectoryUser:
    return DirectoryUser(
        external_id=external_id or f"uuid-{login}",
        dn=_dn(login),
        login=login,
        email=f"{login}@recife.pe.gov.br" if email == "" else email,
        display_name=nome or login.title(),
    )


def make_dir_group(nome: str, *membros: str) -> DirectoryGroup:
    return DirectoryGroup(
        external_id=f"uuid-grupo-{nome}",
        dn=f"cn={nome},{BASE_GRUPOS}",
        name=nome,
        member_dns=frozenset(_dn(m) for m in membros),
    )


def make_local(
    login: str,
    *,
    source: UserSource = UserSource.LDAP,
    email: str | None = "",
    nome: str | None = None,
    external_id: str | None = "",
    ativo: bool = True,
) -> UsuarioLocal:
    return UsuarioLocal(
        id=uuid4(),
        source=source,
        username=login,
        email=f"{login}@recife.pe.gov.br" if email == "" else email,
        display_name=nome or login.title(),
        external_id=(f"uuid-{login}" if source is not UserSource.LOCAL else None)
        if external_id == ""
        else external_id,
        is_active=ativo,
    )


def make_local_group(nome: str, *, ativo: bool = True) -> GrupoLocal:
    return GrupoLocal(id=uuid4(), external_id=f"uuid-grupo-{nome}", name=nome, is_active=ativo)


def _retrato(
    usuarios: tuple[DirectoryUser, ...] = (), grupos: tuple[DirectoryGroup, ...] = ()
) -> DirectorySnapshot:
    return DirectorySnapshot(users=usuarios, groups=grupos)


def _locais(
    usuarios: tuple[UsuarioLocal, ...] = (),
    grupos: tuple[GrupoLocal, ...] = (),
    associacoes: frozenset[tuple[UUID, UUID]] = frozenset(),
) -> EstadoLocal:
    return EstadoLocal(usuarios=usuarios, grupos=grupos, associacoes=associacoes)


# --- Usuários -------------------------------------------------------------------------------


def test_usuario_do_diretorio_que_nao_existe_localmente_e_criado() -> None:
    """004/R1.5"""
    maria = make_dir_user("maria.silva")

    plano = planejar(_retrato((maria,)), _locais())

    assert plano.criacoes == (maria,)
    assert plano.atualizacoes == ()
    assert plano.conflitos == ()


def test_usuario_existente_tem_nome_e_email_atualizados() -> None:
    """004/R1.6"""
    local = make_local("maria.silva", nome="Maria", email="maria@antigo.recife.pe.gov.br")
    maria = make_dir_user("maria.silva", nome="Maria da Silva", email="maria@recife.pe.gov.br")

    plano = planejar(_retrato((maria,)), _locais((local,)))

    assert plano.criacoes == ()
    [atualizacao] = plano.atualizacoes
    assert atualizacao.usuario_id == local.id
    assert atualizacao.dados == maria
    assert atualizacao.email == "maria@recife.pe.gov.br"


def test_usuario_existente_sem_mudanca_tambem_entra_nas_atualizacoes() -> None:
    """004/R1.6: todo usuário encontrado recebe `synced_at`."""
    local = make_local("joao")

    plano = planejar(_retrato((make_dir_user("joao"),)), _locais((local,)))

    assert [a.usuario_id for a in plano.atualizacoes] == [local.id]
    assert plano.reativacoes == ()


def test_usuario_casado_pelo_external_id_e_nao_pelo_login() -> None:
    """004/R1.5, 004/R1.6"""
    local = make_local("maria.silva", external_id="uuid-1")
    renomeada = make_dir_user(
        "maria.souza", external_id="uuid-1", email="maria.silva@recife.pe.gov.br"
    )

    plano = planejar(_retrato((renomeada,)), _locais((local,)))

    assert plano.criacoes == ()
    assert [a.usuario_id for a in plano.atualizacoes] == [local.id]


def test_usuario_ldap_ausente_da_busca_e_desativado() -> None:
    """004/R1.7"""
    presente = make_local("joao")
    ausente = make_local("maria.silva")

    plano = planejar(_retrato((make_dir_user("joao"),)), _locais((presente, ausente)))

    assert plano.desativacoes == (ausente.id,)


def test_ausente_ja_inativo_nao_e_desativado_de_novo() -> None:
    """004/R1.7"""
    inativo = make_local("maria.silva", ativo=False)

    plano = planejar(_retrato(), _locais((inativo,)))

    assert plano.desativacoes == ()


def test_contas_de_outras_origens_nunca_sao_desativadas() -> None:
    """004/R1.7"""
    local = make_local("admin", source=UserSource.LOCAL)
    oidc = make_local("ana", source=UserSource.OIDC)

    plano = planejar(_retrato(), _locais((local, oidc)))

    assert plano.desativacoes == ()
    assert plano.atualizacoes == ()


def test_usuario_ldap_inativo_que_reaparece_e_reativado() -> None:
    """004/R1.6: o status vem da busca filtrada (D004-10)."""
    inativo = make_local("maria.silva", ativo=False)

    plano = planejar(_retrato((make_dir_user("maria.silva"),)), _locais((inativo,)))

    assert plano.reativacoes == (inativo.id,)
    assert [a.usuario_id for a in plano.atualizacoes] == [inativo.id]
    assert plano.criacoes == ()


# --- Grupos e associações --------------------------------------------------------------------


def test_grupos_sao_criados_atualizados_e_desativados() -> None:
    """004/R1.8"""
    novo = make_dir_group("vigilancia")
    renomeado = make_dir_group("gestores")
    local_renomeado = make_local_group("gestores-antigo")
    local_renomeado = GrupoLocal(
        id=local_renomeado.id,
        external_id=renomeado.external_id,
        name="gestores-antigo",
        is_active=True,
    )
    sumiu = make_local_group("extinto")
    ja_inativo = make_local_group("arquivado", ativo=False)

    plano = planejar(
        _retrato(grupos=(novo, renomeado)), _locais(grupos=(local_renomeado, sumiu, ja_inativo))
    )

    assert plano.grupos_criacoes == (novo,)
    assert [(g.grupo_id, g.dados) for g in plano.grupos_atualizacoes] == [
        (local_renomeado.id, renomeado)
    ]
    assert plano.grupos_desativacoes == (sumiu.id,)


def test_associacoes_espelham_os_membros_dos_grupos_pelo_dn() -> None:
    """004/R1.8"""
    maria, joao = make_dir_user("maria.silva"), make_dir_user("joao")
    gestores = make_dir_group("gestores", "maria.silva", "joao")
    vigilancia = make_dir_group("vigilancia", "maria.silva", "fora.da.busca")

    plano = planejar(_retrato((maria, joao), (gestores, vigilancia)), _locais())

    assert plano.associacoes == {
        maria.external_id: frozenset({gestores.external_id, vigilancia.external_id}),
        joao.external_id: frozenset({gestores.external_id}),
    }


def test_recalcula_so_quem_mudou_de_grupo_e_os_desativados() -> None:
    """004/R1.8"""
    gestores_local = make_local_group("gestores")
    vigilancia_local = make_local_group("vigilancia")
    sem_mudanca = make_local("joao")
    mudou = make_local("maria.silva")
    desativado = make_local("ana")
    locais = _locais(
        (sem_mudanca, mudou, desativado),
        (gestores_local, vigilancia_local),
        frozenset(
            {
                (sem_mudanca.id, gestores_local.id),
                (mudou.id, gestores_local.id),
                (desativado.id, gestores_local.id),
            }
        ),
    )
    retrato = _retrato(
        (make_dir_user("joao"), make_dir_user("maria.silva"), make_dir_user("pedro")),
        (
            make_dir_group("gestores", "joao"),
            make_dir_group("vigilancia", "maria.silva", "pedro"),
        ),
    )

    plano = planejar(retrato, locais)

    assert plano.recalcular == frozenset({"uuid-maria.silva", "uuid-pedro", "uuid-ana"})
    assert plano.associacoes["uuid-ana"] == frozenset()
    assert plano.associacoes["uuid-maria.silva"] == frozenset({"uuid-grupo-vigilancia"})


def test_reativado_tem_as_derivadas_recalculadas() -> None:
    """004/R1.8"""
    inativo = make_local("maria.silva", ativo=False)

    plano = planejar(_retrato((make_dir_user("maria.silva"),)), _locais((inativo,)))

    assert "uuid-maria.silva" in plano.recalcular


# --- Conflitos (R4.2, D004-11) ---------------------------------------------------------------


def test_email_usado_por_conta_de_outra_origem_e_conflito_e_nao_cria() -> None:
    """004/R4.2"""
    existente = make_local("maria", source=UserSource.LOCAL, email="maria.silva@recife.pe.gov.br")
    maria = make_dir_user("maria.silva")

    plano = planejar(_retrato((maria,)), _locais((existente,)))

    assert plano.criacoes == ()
    assert plano.conflitos == (Conflito(TipoConflito.EMAIL, maria.external_id, existente.id),)
    assert maria.external_id not in plano.associacoes


def test_username_usado_por_conta_de_outra_origem_e_conflito_e_nao_cria() -> None:
    """004/R4.2; D004-11"""
    existente = make_local("maria.silva", source=UserSource.OIDC, email="outra@recife.pe.gov.br")
    maria = make_dir_user("maria.silva")

    plano = planejar(_retrato((maria,)), _locais((existente,)))

    assert plano.criacoes == ()
    assert plano.conflitos == (Conflito(TipoConflito.USERNAME, maria.external_id, existente.id),)


def test_username_de_outra_conta_ldap_tambem_e_conflito() -> None:
    """004/R4.2; D004-11: a unicidade vale em todas as origens."""
    antiga = make_local("maria.silva", external_id="uuid-antigo", email=None, ativo=False)
    nova = make_dir_user("maria.silva", external_id="uuid-novo")

    plano = planejar(_retrato((nova,)), _locais((antiga,)))

    assert plano.criacoes == ()
    assert plano.conflitos == (Conflito(TipoConflito.USERNAME, "uuid-novo", antiga.id),)


def test_email_e_username_em_conflito_registram_os_dois() -> None:
    """004/R4.2; D004-11"""
    existente = make_local("maria.silva", source=UserSource.LOCAL)
    maria = make_dir_user("maria.silva")

    plano = planejar(_retrato((maria,)), _locais((existente,)))

    assert set(plano.conflitos) == {
        Conflito(TipoConflito.USERNAME, maria.external_id, existente.id),
        Conflito(TipoConflito.EMAIL, maria.external_id, existente.id),
    }


def test_um_conflito_nao_para_os_demais() -> None:
    """004/R4.2"""
    por_email = make_local("x", source=UserSource.LOCAL, email="ana@recife.pe.gov.br")
    por_username = make_local("pedro", source=UserSource.OIDC, email="p@recife.pe.gov.br")
    atualizado = make_local("joao", nome="Joao")
    ausente = make_local("bia")
    joao = make_dir_user("joao", nome="João Souza")
    maria = make_dir_user("maria.silva")
    retrato = _retrato(
        (make_dir_user("ana"), make_dir_user("pedro"), maria, joao),
        (make_dir_group("gestores", "ana", "pedro", "maria.silva"),),
    )

    plano = planejar(retrato, _locais((por_email, por_username, atualizado, ausente)))

    assert {c.external_id for c in plano.conflitos} == {"uuid-ana", "uuid-pedro"}
    assert plano.criacoes == (maria,)
    assert [a.dados for a in plano.atualizacoes] == [joao]
    assert plano.desativacoes == (ausente.id,)
    assert plano.associacoes[maria.external_id] == frozenset({"uuid-grupo-gestores"})


def test_email_novo_que_colide_na_atualizacao_mantem_o_antigo_e_vira_conflito() -> None:
    """004/R4.2: design § Fluxo > Sincronização (4)."""
    dono = make_local("ana", source=UserSource.LOCAL, email="ana@recife.pe.gov.br")
    local = make_local("maria.silva", nome="Maria")
    maria = make_dir_user("maria.silva", nome="Maria da Silva", email="ana@recife.pe.gov.br")

    plano = planejar(_retrato((maria,)), _locais((dono, local)))

    [atualizacao] = plano.atualizacoes
    assert atualizacao.email == local.email
    assert atualizacao.dados.display_name == "Maria da Silva"
    assert plano.conflitos == (Conflito(TipoConflito.EMAIL, maria.external_id, dono.id),)


def test_dois_usuarios_do_retrato_com_o_mesmo_email_nao_sao_criados_os_dois() -> None:
    """004/R4.2: só o primeiro (pela ordem do `external_id`) é criado."""
    a = make_dir_user("ana", external_id="uuid-a", email="dup@recife.pe.gov.br")
    b = make_dir_user("bia", external_id="uuid-b", email="dup@recife.pe.gov.br")

    plano = planejar(_retrato((b, a)), _locais())

    assert plano.criacoes == (a,)
    assert plano.conflitos == (Conflito(TipoConflito.EMAIL, "uuid-b", None),)


def test_conflito_nao_traz_email_nem_nome() -> None:
    """004/R4.2: o Admin TI chega à conta pelo id (LGPD)."""
    assert {f.name for f in fields(Conflito)} == {"tipo", "external_id", "usuario_existente_id"}


# --- Propriedade: o plano nunca viola a unicidade de `username` e `email` -------------------

_LOGINS = st.sampled_from(["ana", "bia", "joao", "maria", "pedro"])
_EMAILS = st.one_of(st.none(), st.sampled_from(["a@x.br", "b@x.br", "c@x.br"]))
_IDS = st.sampled_from(["uuid-1", "uuid-2", "uuid-3", "uuid-4"])


@st.composite
def _cenario(draw: st.DrawFn) -> tuple[DirectorySnapshot, EstadoLocal]:
    diretorio = draw(
        st.lists(st.tuples(_IDS, _LOGINS, _EMAILS), max_size=4, unique_by=lambda t: t[0])
    )
    locais = draw(
        st.lists(
            st.tuples(st.sampled_from(list(UserSource)), _IDS, _LOGINS, _EMAILS, st.booleans()),
            max_size=4,
            unique_by=(lambda t: t[2], lambda t: t[3] or object()),
        )
    )
    usuarios_locais: list[UsuarioLocal] = []
    externos_ldap: set[str] = set()
    for origem, ext, login, email, ativo in locais:
        if origem is UserSource.LDAP:
            if ext in externos_ldap:  # (`source`, `external_id`) é único no banco
                continue
            externos_ldap.add(ext)
        usuarios_locais.append(
            make_local(login, source=origem, email=email, external_id=ext, ativo=ativo)
        )
    retrato = _retrato(
        tuple(make_dir_user(login, email=email, external_id=ext) for ext, login, email in diretorio)
    )
    return retrato, _locais(tuple(usuarios_locais))


def _estado_final(plano: PlanoDeSincronizacao, locais: EstadoLocal) -> list[tuple[str, str | None]]:
    emails = {a.usuario_id: a.email for a in plano.atualizacoes}
    finais = [(u.username, emails.get(u.id, u.email)) for u in locais.usuarios]
    finais += [(c.login, c.email) for c in plano.criacoes]
    return finais


@given(_cenario())
def test_plano_nunca_repete_username_nem_email(
    cenario: tuple[DirectorySnapshot, EstadoLocal],
) -> None:
    """004/R4.2; D004-11"""
    retrato, locais = cenario

    finais = _estado_final(planejar(retrato, locais), locais)

    usernames = [u for u, _ in finais]
    emails = [e for _, e in finais if e is not None]
    assert len(usernames) == len(set(usernames))
    assert len(emails) == len(set(emails))


def test_membro_casa_pelo_dn_sem_diferenciar_maiusculas_nem_espacos() -> None:
    """004/R1.8 (DN é insensível a maiúsculas; o `member` do grupo pode vir escrito diferente do
    DN da entrada do usuário)"""
    ana = make_dir_user("ana")
    grupo = DirectoryGroup(
        external_id="uuid-grupo-ti",
        dn=f"cn=ti,{BASE_GRUPOS}",
        name="ti",
        member_dns=frozenset({ana.dn.upper().replace(",", ", ")}),
    )

    plano = planejar(_retrato((ana,), (grupo,)), _locais())

    assert plano.associacoes["uuid-ana"] == frozenset({"uuid-grupo-ti"})
