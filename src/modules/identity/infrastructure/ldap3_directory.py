"""`DirectoryPort` com o `ldap3` (spec 004, design § Portas e adaptadores, `ldap3_directory.py`).

- Só LDAPS, ou `ldap://` com StartTLS antes de qualquer bind, com a CA de LDAP_CA_FILE e a
  conferência do nome do servidor (R1.2, R1.13).
- A conta de serviço faz as buscas, paginadas e só com os atributos configurados (R1.3, R1.4).
- Todo valor que entra em filtro passa por `escape_filter_chars` (R2.2).
- A senha do usuário é conferida por bind com o DN dele; senha vazia nem chega ao bind (R2.4).
- Referral nunca é seguido: seguir refaria o bind da conta de serviço no host indicado, em claro
  se o referral for `ldap://` (R1.13). Busca que não termina em sucesso (referral, limite de
  tamanho ou de tempo) é falha, nunca retrato parcial: a R1.7 desativaria quem ficou de fora.
- O `ldap3` é síncrono: cada chamada roda em `anyio.to_thread.run_sync`.

Erros do `ldap3` viram `DirectoryUnavailable` com mensagem genérica e sem a exceção original
encadeada: nenhuma senha vai para exceção ou log.
"""

import contextlib
import functools
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from ssl import CERT_REQUIRED
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import anyio.to_thread
from ldap3 import NONE, SUBTREE, SYNC, Connection, Server, Tls
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPCertificateError,
    LDAPException,
    LDAPInvalidCredentialsResult,
    LDAPReferralError,
    LDAPSSLConfigurationError,
    LDAPStartTLSError,
)
from ldap3.core.results import RESULT_SUCCESS
from ldap3.utils.conv import escape_filter_chars
from pydantic import SecretStr

from src.core.config import Settings
from src.modules.identity.domain.diretorio import (
    DirectoryGroup,
    DirectorySnapshot,
    DirectoryUnavailable,
    DirectoryUser,
)

CONNECT_TIMEOUT_SECONDS = 5
RECEIVE_TIMEOUT_SECONDS = 10
_UNAVAILABLE = "Serviço de diretório indisponível"
# Resultado de `testar`: "ok" ou um motivo genérico (design § Roteiro e ferramenta).
MotivoDoTeste = Literal["ok", "certificado", "conexao", "credencial"]


@dataclass(frozen=True)
class LdapConfig:
    """As variáveis LDAP_* já validadas por `Settings._ldap_problems`."""

    url: str
    start_tls: bool
    ca_file: Path | None
    bind_dn: str
    bind_password: SecretStr
    user_base: str
    user_filter: str
    group_base: str
    group_filter: str
    attr_login: str
    attr_email: str
    attr_name: str
    attr_id: str  # vazio: o DN (R1.5)
    attr_member: str
    page_size: int

    @classmethod
    def from_settings(cls, settings: Settings) -> Self | None:
        """None com o LDAP desligado (sem LDAP_URL)."""
        if settings.ldap_url is None:
            return None
        required = (
            settings.ldap_bind_dn,
            settings.ldap_bind_password,
            settings.ldap_user_base,
            settings.ldap_user_filter,
            settings.ldap_group_base,
            settings.ldap_group_filter,
        )
        if any(value is None for value in required):  # pragma: no cover - `Settings` recusa
            raise ValueError("configuração LDAP incompleta")
        return cls(
            url=settings.ldap_url,
            start_tls=settings.ldap_start_tls,
            ca_file=Path(settings.ldap_ca_file) if settings.ldap_ca_file else None,
            bind_dn=str(settings.ldap_bind_dn),
            bind_password=settings.ldap_bind_password or SecretStr(""),
            user_base=str(settings.ldap_user_base),
            user_filter=str(settings.ldap_user_filter),
            group_base=str(settings.ldap_group_base),
            group_filter=str(settings.ldap_group_filter),
            attr_login=settings.ldap_attr_login,
            attr_email=settings.ldap_attr_email,
            attr_name=settings.ldap_attr_name,
            attr_id=settings.ldap_attr_id,
            attr_member=settings.ldap_attr_member,
            page_size=settings.ldap_page_size,
        )


class Ldap3Directory:
    """Diretório LDAP. `server` e `client_strategy` só mudam nos testes (`MOCK_SYNC`)."""

    def __init__(
        self, config: LdapConfig, *, server: Server | None = None, client_strategy: str = SYNC
    ) -> None:
        self._config = config
        self._server = server or _build_server(config)
        self._strategy = client_strategy

    async def snapshot(self) -> DirectorySnapshot:
        return await self._run(self._snapshot)

    async def find_user(self, login: str) -> DirectoryUser | None:
        return await self._run(functools.partial(self._find_user, login))

    async def verify_password(self, dn: str, password: str) -> bool:
        if not dn or not password:  # R2.4: sem bind, que poderia virar bind anônimo
            return False
        return await self._run(functools.partial(self._verify_password, dn, password))

    async def groups_of(self, user: DirectoryUser) -> tuple[DirectoryGroup, ...]:
        return await self._run(functools.partial(self._groups_of, user.dn))

    async def testar(self) -> MotivoDoTeste:
        """Conexão, TLS e bind da conta de serviço, sem busca nem escrita (`sgs-admin diretorio
        testar`). Devolve "ok" ou o motivo genérico, nunca a mensagem do `ldap3`."""
        return await anyio.to_thread.run_sync(self._testar)

    def _testar(self) -> MotivoDoTeste:
        try:
            self._service_connection().unbind()
        except (LDAPBindError, LDAPInvalidCredentialsResult):
            return "credencial"
        except LDAPException as erro:
            return "certificado" if _is_certificate_error(erro) else "conexao"
        return "ok"

    async def _run[T](self, call: Callable[[], T]) -> T:
        try:
            return await anyio.to_thread.run_sync(call)
        except LDAPException:
            # `from None`: a exceção do `ldap3` pode citar a requisição de bind.
            raise DirectoryUnavailable(_UNAVAILABLE) from None

    # Chamadas síncronas, sempre fora do loop de eventos.

    def _snapshot(self) -> DirectorySnapshot:
        cfg = self._config
        with self._service_connection() as conn:
            users = self._search(conn, cfg.user_base, cfg.user_filter, self._user_attributes)
            groups = self._search(conn, cfg.group_base, cfg.group_filter, self._group_attributes)
        return DirectorySnapshot(
            users=tuple(u for u in map(self._to_user, users) if u is not None),
            groups=tuple(g for g in map(self._to_group, groups) if g is not None),
        )

    def _find_user(self, login: str) -> DirectoryUser | None:
        cfg = self._config
        search_filter = f"(&{cfg.user_filter}({cfg.attr_login}={escape_filter_chars(login)}))"
        with self._service_connection() as conn:
            found = self._search(conn, cfg.user_base, search_filter, self._user_attributes)
        users = [u for u in map(self._to_user, found) if u is not None]
        return users[0] if len(users) == 1 else None  # ambíguo não autentica ninguém

    def _verify_password(self, dn: str, password: str) -> bool:
        try:
            conn = self._connection(dn, password)
        except (LDAPBindError, LDAPInvalidCredentialsResult):
            return False
        conn.unbind()
        return True

    def _groups_of(self, dn: str) -> tuple[DirectoryGroup, ...]:
        cfg = self._config
        search_filter = f"(&{cfg.group_filter}({cfg.attr_member}={escape_filter_chars(dn)}))"
        with self._service_connection() as conn:
            found = self._search(conn, cfg.group_base, search_filter, self._group_attributes)
        return tuple(g for g in map(self._to_group, found) if g is not None)

    def _service_connection(self) -> Connection:
        cfg = self._config
        return self._connection(cfg.bind_dn, cfg.bind_password.get_secret_value())

    def _connection(self, user: str, password: str) -> Connection:
        """Abre e faz o bind; com StartTLS, o TLS vem antes do bind (R1.13).

        É o `AUTO_BIND_TLS_BEFORE_BIND` do design, feito passo a passo: o `MOCK_SYNC` ignora o
        `auto_bind`, e assim os testes passam pelo mesmo bind da produção."""
        conn = Connection(
            self._server,
            user=user,
            password=password,
            client_strategy=self._strategy,
            read_only=True,
            receive_timeout=RECEIVE_TIMEOUT_SECONDS,
            raise_exceptions=True,
            # O padrão (True) refaz o bind, com esta senha, no host que o referral indicar.
            auto_referrals=False,
        )
        try:
            conn.open()
            # A recusa do TLS levanta; o False, se vier, também barra o bind.
            if self._config.start_tls and not conn.start_tls():
                raise LDAPStartTLSError("StartTLS recusado")
            if not conn.bind():  # com raise_exceptions, a recusa já levanta
                raise LDAPBindError(_UNAVAILABLE)
        except BaseException:
            # O unbind num socket já quebrado (TLS recusado) levantaria outro erro por cima.
            with contextlib.suppress(LDAPException, OSError):
                conn.unbind()
            raise
        return conn

    def _search(
        self, conn: Connection, base: str, search_filter: str, attributes: list[str]
    ) -> list[dict[str, Any]]:
        entries = conn.extend.standard.paged_search(
            base,
            search_filter,
            search_scope=SUBTREE,
            attributes=attributes,
            paged_size=self._config.page_size,
            generator=False,
        )
        # Referral (10) e os limites (3, 4) estão em DO_NOT_RAISE_EXCEPTIONS: sem esta
        # conferência, a busca volta vazia ou cortada, sem erro (004/T2, revisão B1 e S1).
        if (conn.result or {}).get("result") != RESULT_SUCCESS:
            raise LDAPReferralError("busca não concluída")
        return [e for e in entries if e.get("type") == "searchResEntry"]

    @property
    def _user_attributes(self) -> list[str]:
        cfg = self._config
        names = [cfg.attr_login, cfg.attr_email, cfg.attr_name, cfg.attr_id]
        return [name for name in names if name]

    @property
    def _group_attributes(self) -> list[str]:
        cfg = self._config
        return [name for name in (cfg.attr_name, cfg.attr_id, cfg.attr_member) if name]

    def _to_user(self, entry: dict[str, Any]) -> DirectoryUser | None:
        cfg = self._config
        attributes = entry.get("attributes", {})
        login = (_first(attributes.get(cfg.attr_login)) or "").strip()
        if not login:
            return None
        email = (_first(attributes.get(cfg.attr_email)) or "").strip()
        return DirectoryUser(
            external_id=self._external_id(entry),
            dn=entry["dn"],
            login=login.lower(),
            email=email.lower() or None,
            display_name=_first(attributes.get(cfg.attr_name)) or login,
        )

    def _to_group(self, entry: dict[str, Any]) -> DirectoryGroup | None:
        attributes = entry.get("attributes", {})
        name = _first(attributes.get(self._config.attr_name))
        if not name:
            return None
        return DirectoryGroup(
            external_id=self._external_id(entry),
            dn=entry["dn"],
            name=name,
            member_dns=frozenset(_all(attributes.get(self._config.attr_member))),
        )

    def _external_id(self, entry: dict[str, Any]) -> str:
        if not self._config.attr_id:
            return str(entry["dn"])
        return _first(entry.get("attributes", {}).get(self._config.attr_id)) or str(entry["dn"])


def _build_server(config: LdapConfig) -> Server:
    parts = urlsplit(config.url)
    host = parts.hostname or ""
    ldaps = parts.scheme == "ldaps"
    tls = Tls(
        validate=CERT_REQUIRED,
        ca_certs_file=str(config.ca_file) if config.ca_file else None,
        # Sem `version`, o `ldap3` usa `ssl.create_default_context`: TLS 1.2 ou maior.
        valid_names=[host],
        sni=host,
    )
    return Server(
        host,
        port=parts.port or (636 if ldaps else 389),
        use_ssl=ldaps,
        tls=tls,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        # Sem NONE, o `ldap3` lê o root DSE ao abrir a conexão: com StartTLS, essa busca sairia
        # em claro, antes do TLS (004/T11, `test_ldap_tls.py`). Sem esquema, binários viram hex.
        get_info=NONE,
    )


def _is_certificate_error(error: LDAPException) -> bool:
    """TLS recusado (CA, nome, StartTLS). O `ldap3` agrega as tentativas de conexão numa
    `LDAPSocketOpenError` cujo texto cita o erro do `ssl`; o texto só é lido, nunca mostrado."""
    if isinstance(error, LDAPCertificateError | LDAPStartTLSError | LDAPSSLConfigurationError):
        return True
    text = str(error).lower()
    return any(marker in text for marker in ("ssl", "certificate", "tls"))


def _all(value: object) -> Iterable[str]:
    values = value if isinstance(value, list | tuple) else ([] if value is None else [value])
    return [_text(v) for v in values]


def _first(value: object) -> str | None:
    values = list(_all(value))
    return values[0] if values else None


def _text(value: object) -> str:
    # Atributos binários (objectGUID sem esquema) viram hexadecimal.
    return value.hex() if isinstance(value, bytes) else str(value)
