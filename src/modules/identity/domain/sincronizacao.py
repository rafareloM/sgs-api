"""Plano da sincronização do diretório (spec 004, T12; design § Fluxo > Sincronização).

Função pura: recebe o retrato do diretório e o estado local e diz o que a aplicação (004/T3)
deve gravar. Não lê nem escreve nada.

- R1.5: usuário do retrato sem conta `ldap` com o mesmo `external_id` é criado.
- R1.6: usuário encontrado tem nome, e-mail e status atualizados; todos entram nas atualizações,
  porque todos recebem `synced_at`. Quem estava inativo é reativado (D004-10).
- R1.7: conta `ldap` ativa que não veio na busca é desativada, nunca apagada.
- R1.8: grupos e associações espelham o retrato (membros casados pelo DN); recalcula as
  derivadas de quem mudou de grupo, de quem foi reativado e de quem foi desativado.
- R4.2 e D004-11: `username` e `email` são únicos em todas as origens. Quem seria criado com um
  deles já usado não é criado nem unido à outra conta; na atualização, um e-mail novo que
  colida mantém o antigo. Os dois casos viram conflito, e os demais usuários seguem.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from src.modules.identity.domain.diretorio import DirectoryGroup, DirectorySnapshot, DirectoryUser
from src.modules.identity.domain.users import UserSource

_ESPACOS_DO_DN = re.compile(r"\s*([,=])\s*")


@dataclass(frozen=True)
class UsuarioLocal:
    """Conta local de qualquer origem: as de outras origens só contam para os conflitos."""

    id: UUID
    source: UserSource
    username: str
    email: str | None
    display_name: str
    external_id: str | None
    is_active: bool


@dataclass(frozen=True)
class GrupoLocal:
    """Grupo espelhado de origem `ldap`."""

    id: UUID
    external_id: str
    name: str
    is_active: bool


@dataclass(frozen=True)
class EstadoLocal:
    usuarios: tuple[UsuarioLocal, ...]
    grupos: tuple[GrupoLocal, ...]
    associacoes: frozenset[tuple[UUID, UUID]]  # (`user_id`, `group_id`) de origem `ldap`


class TipoConflito(StrEnum):
    EMAIL = "email"
    USERNAME = "username"


@dataclass(frozen=True)
class Conflito:
    """Sem e-mail nem nome: o Admin TI chega à conta pelo id (LGPD)."""

    tipo: TipoConflito
    external_id: str
    # None quando a colisão é com outro usuário do mesmo retrato, que o plano cria.
    usuario_existente_id: UUID | None


@dataclass(frozen=True)
class AtualizacaoDeUsuario:
    usuario_id: UUID
    dados: DirectoryUser
    email: str | None  # o e-mail a gravar: o do diretório, ou o antigo se o novo colidir


@dataclass(frozen=True)
class AtualizacaoDeGrupo:
    grupo_id: UUID
    dados: DirectoryGroup


@dataclass(frozen=True)
class PlanoDeSincronizacao:
    criacoes: tuple[DirectoryUser, ...]
    atualizacoes: tuple[AtualizacaoDeUsuario, ...]
    reativacoes: tuple[UUID, ...]
    desativacoes: tuple[UUID, ...]
    grupos_criacoes: tuple[DirectoryGroup, ...]
    grupos_atualizacoes: tuple[AtualizacaoDeGrupo, ...]
    grupos_desativacoes: tuple[UUID, ...]
    # `external_id` do usuário -> `external_id` dos grupos: criados, atualizados e desativados
    # (estes com o conjunto vazio).
    associacoes: Mapping[str, frozenset[str]]
    # `external_id` dos usuários cujas atribuições derivadas devem ser recalculadas.
    recalcular: frozenset[str]
    conflitos: tuple[Conflito, ...]


@dataclass
class _Usados:
    """Quem ocupa cada `username` e `email`, contando o que o plano já reservou."""

    usernames: dict[str, UUID | None]
    emails: dict[str, UUID | None]

    @classmethod
    def de(cls, usuarios: Iterable[UsuarioLocal]) -> "_Usados":
        usados = cls(usernames={}, emails={})
        for u in usuarios:
            usados.usernames[u.username] = u.id
            if u.email is not None:
                usados.emails[u.email] = u.id
        return usados


def planejar(retrato: DirectorySnapshot, locais: EstadoLocal) -> PlanoDeSincronizacao:
    ldap_locais = {
        u.external_id: u
        for u in locais.usuarios
        if u.source is UserSource.LDAP and u.external_id is not None
    }
    usados = _Usados.de(locais.usuarios)

    criacoes: list[DirectoryUser] = []
    atualizacoes: list[AtualizacaoDeUsuario] = []
    reativados: list[UsuarioLocal] = []
    conflitos: list[Conflito] = []
    sincronizados: list[DirectoryUser] = []

    # Ordem fixa: o plano não depende da ordem em que o diretório devolveu as entradas.
    for dado in sorted(retrato.users, key=lambda u: u.external_id):
        local = ldap_locais.get(dado.external_id)
        if local is None:
            achados = _conflitos_de_criacao(dado, usados)
            if achados:
                conflitos.extend(achados)
                continue
            usados.usernames[dado.login] = None
            if dado.email is not None:
                usados.emails[dado.email] = None
            criacoes.append(dado)
        else:
            email = _email_da_atualizacao(dado, local, usados, conflitos)
            atualizacoes.append(AtualizacaoDeUsuario(usuario_id=local.id, dados=dado, email=email))
            if not local.is_active:
                reativados.append(local)
        sincronizados.append(dado)

    presentes = {u.external_id for u in retrato.users}
    desativados = {
        ext: u for ext, u in sorted(ldap_locais.items()) if ext not in presentes and u.is_active
    }

    grupos_locais = {g.external_id: g for g in locais.grupos}
    grupos = sorted(retrato.groups, key=lambda g: g.external_id)
    grupos_presentes = {g.external_id for g in grupos}

    associacoes = _associacoes(sincronizados, grupos)
    associacoes.update(dict.fromkeys(desativados, frozenset()))
    anteriores = _associacoes_locais(locais)
    recalcular = {
        ext for ext, novos in associacoes.items() if novos != anteriores.get(ext, frozenset())
    }
    recalcular |= {u.external_id for u in reativados if u.external_id} | desativados.keys()

    return PlanoDeSincronizacao(
        criacoes=tuple(criacoes),
        atualizacoes=tuple(atualizacoes),
        reativacoes=tuple(u.id for u in reativados),
        desativacoes=tuple(u.id for u in desativados.values()),
        grupos_criacoes=tuple(g for g in grupos if g.external_id not in grupos_locais),
        grupos_atualizacoes=tuple(
            AtualizacaoDeGrupo(grupo_id=grupos_locais[g.external_id].id, dados=g)
            for g in grupos
            if g.external_id in grupos_locais
        ),
        grupos_desativacoes=tuple(
            g.id
            for ext, g in sorted(grupos_locais.items())
            if ext not in grupos_presentes and g.is_active
        ),
        associacoes=associacoes,
        recalcular=frozenset(recalcular),
        conflitos=tuple(conflitos),
    )


def _conflitos_de_criacao(dado: DirectoryUser, usados: _Usados) -> list[Conflito]:
    achados: list[Conflito] = []
    if dado.login in usados.usernames:
        achados.append(
            Conflito(TipoConflito.USERNAME, dado.external_id, usados.usernames[dado.login])
        )
    if dado.email is not None and dado.email in usados.emails:
        achados.append(Conflito(TipoConflito.EMAIL, dado.external_id, usados.emails[dado.email]))
    return achados


def _email_da_atualizacao(
    dado: DirectoryUser, local: UsuarioLocal, usados: _Usados, conflitos: list[Conflito]
) -> str | None:
    if dado.email is None or dado.email == local.email:
        return dado.email
    if dado.email in usados.emails:
        conflitos.append(Conflito(TipoConflito.EMAIL, dado.external_id, usados.emails[dado.email]))
        return local.email
    # O e-mail antigo continua reservado: a ordem em que a aplicação grava não importa.
    usados.emails[dado.email] = local.id
    return dado.email


def chave_de_dn(dn: str) -> str:
    """O DN para comparação: o LDAP não diferencia maiúsculas nos nomes nem nos valores dos
    atributos usuais (`uid`, `cn`, `ou`, `dc`) e ignora espaços em volta de `,` e `=`."""
    return _ESPACOS_DO_DN.sub(r"\1", dn.strip()).lower()


def _associacoes(
    usuarios: Iterable[DirectoryUser], grupos: Iterable[DirectoryGroup]
) -> dict[str, frozenset[str]]:
    por_dn = {chave_de_dn(u.dn): u.external_id for u in usuarios}
    membros: dict[str, set[str]] = {ext: set() for ext in por_dn.values()}
    for grupo in grupos:
        for dn in grupo.member_dns:
            ext = por_dn.get(chave_de_dn(dn))
            if ext is not None:  # membro fora da busca (ou em conflito) é ignorado
                membros[ext].add(grupo.external_id)
    return {ext: frozenset(gs) for ext, gs in membros.items()}


def _associacoes_locais(locais: EstadoLocal) -> dict[str, frozenset[str]]:
    usuarios = {
        u.id: u.external_id
        for u in locais.usuarios
        if u.source is UserSource.LDAP and u.external_id is not None
    }
    grupos = {g.id: g.external_id for g in locais.grupos}
    anteriores: dict[str, set[str]] = {}
    for usuario_id, grupo_id in locais.associacoes:
        if usuario_id in usuarios and grupo_id in grupos:
            anteriores.setdefault(usuarios[usuario_id], set()).add(grupos[grupo_id])
    return {ext: frozenset(gs) for ext, gs in anteriores.items()}
