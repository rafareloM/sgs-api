"""Portas do módulo de identidade.

Os repositórios trabalham sobre a transação de quem os usa: quem chama abre, confirma ou desfaz.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.modules.identity.domain.espelho_diretorio import (
    GroupListing,
    OrigemDeGrupo,
    StatusDaExecucao,
    SyncConflict,
    SyncCounts,
    SyncRun,
    UpsertedGroup,
)
from src.modules.identity.domain.login import EstadoDeLogin
from src.modules.identity.domain.oidc import OidcLoginRequest
from src.modules.identity.domain.sessions import AuthSession, RefreshToken
from src.modules.identity.domain.sincronizacao import EstadoLocal
from src.modules.identity.domain.users import User, UserSource


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_username(self, username: str) -> User | None:
        """Busca sem diferenciar maiúsculas de minúsculas (o nome é normalizado)."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Busca sem diferenciar maiúsculas de minúsculas (o e-mail é guardado em minúsculas)."""
        ...

    async def get_by_external_id(self, source: UserSource, external_id: str) -> User | None:
        """A conta de diretório pela origem e pelo identificador externo (spec 004)."""
        ...


class SessionRepository(Protocol):
    async def add(self, session: AuthSession) -> None: ...

    async def get_by_id(self, session_id: UUID) -> AuthSession | None: ...


class RefreshTokenRepository(Protocol):
    async def add(self, token: RefreshToken) -> None: ...

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Busca pelo SHA-256 do token (`hash_refresh_token`), nunca pelo valor em claro."""
        ...


class LoginStateRepository(Protocol):
    """Contadores de falha, bloqueio e estado do 2FA em `users` (002, design § Modelo)."""

    async def estado(self, user_id: UUID) -> EstadoDeLogin | None: ...

    async def registrar_falha(self, user_id: UUID, agora: datetime) -> EstadoDeLogin:
        """Incrementa `failed_logins`; na 5ª seguida, bloqueia por 15 min e zera (R1.4)."""
        ...

    async def registrar_sucesso(self, user_id: UUID, agora: datetime) -> None:
        """Zera as falhas, tira o bloqueio e grava `last_login_at`."""
        ...

    async def novo_desafio(self, user_id: UUID, jti: UUID) -> None:
        """Troca o `mfa_challenge_jti` e zera as tentativas: só o `mfa_token` novo vale (R2.6)."""
        ...

    async def falha_de_mfa(self, user_id: UUID) -> int:
        """Incrementa `mfa_failed_attempts` e devolve o total; na 5ª, limpa o desafio (R2.6)."""
        ...

    async def gravar_segredo(self, user_id: UUID, segredo_cifrado: str) -> None: ...

    async def concluir_mfa(self, user_id: UUID, passo: int, *, ativar: bool) -> None:
        """Grava o passo usado (anti-reuso), limpa o desafio e, no cadastro, ativa o 2FA."""
        ...


class PapeisDoUsuario(Protocol):
    """Papéis efetivos de um usuário agora, para o `auth.login` (spec 013, R1.4). A raiz de
    composição liga ao resolvedor de permissões do módulo access; o identity não o importa."""

    async def de(self, usuario_id: UUID) -> tuple[str, ...]: ...


class SessionRevoker(Protocol):
    async def revogar(self, session_id: UUID, agora: datetime) -> None:
        """Revoga a sessão e os refresh tokens dela (R3.5, R3.7)."""
        ...


class RefreshTokenWriter(Protocol):
    async def marcar_usado(self, token_id: UUID, agora: datetime) -> bool:
        """Marca o refresh como usado, só se ainda não estava; `False` se outro já usou."""
        ...


class DirectoryRepository(Protocol):
    """Grupos espelhados, associações e execuções da sincronização (spec 004, design § Modelo)."""

    async def upsert_group(
        self, source: OrigemDeGrupo, external_id: str, name: str, agora: datetime
    ) -> UpsertedGroup:
        """Cria ou atualiza por (`source`, `external_id`) e reativa (R1.8, R3.3)."""
        ...

    async def deactivate_groups_except(
        self, source: OrigemDeGrupo, external_ids: set[str], agora: datetime
    ) -> int:
        """Desativa, sem apagar, os grupos ativos da origem fora da lista; devolve quantos."""
        ...

    async def replace_user_groups(
        self, user_id: UUID, source: OrigemDeGrupo, group_ids: set[UUID]
    ) -> None:
        """Troca as associações da origem do usuário pelas dadas (R1.8, R2.3, R3.3)."""
        ...

    async def groups_of_user(self, user_id: UUID, source: OrigemDeGrupo) -> frozenset[UUID]: ...

    async def active_member_counts(self, group_ids: set[UUID]) -> dict[UUID, int]:
        """Membros com conta ativa por grupo (R1.14)."""
        ...

    async def start_run(self, run_id: UUID, *, triggered_by: UUID | None, agora: datetime) -> bool:
        """Grava a execução `em_andamento`; `False` se já houver uma (R1.11)."""
        ...

    async def finish_run(
        self,
        run_id: UUID,
        status: StatusDaExecucao,
        agora: datetime,
        *,
        counts: SyncCounts | None = None,
        conflicts: tuple[SyncConflict, ...] = (),
        error: str | None = None,
    ) -> None:
        """Fecha a execução com as contagens, os conflitos e o erro genérico (R1.9, R1.10)."""
        ...

    async def fail_running_runs(self, error: str, agora: datetime) -> tuple[UUID, ...]:
        """Fecha como `falhou` as execuções `em_andamento` e devolve os ids (design § Fluxo,
        Sincronização, passo 6)."""
        ...

    async def local_state(self, source: OrigemDeGrupo) -> EstadoLocal:
        """Todas as contas (de qualquer origem, para os conflitos), os grupos e as associações
        da origem (R1.5 a R1.8, R4.2)."""
        ...

    async def add_synced_user(self, user: User, agora: datetime) -> None:
        """Cria a conta do diretório, ativa e com `synced_at` (R1.5)."""
        ...

    async def update_synced_user(
        self, user_id: UUID, *, display_name: str, email: str | None, agora: datetime
    ) -> None:
        """Atualiza nome e e-mail, ativa e grava `synced_at` (R1.6)."""
        ...

    async def deactivate_users(self, user_ids: set[UUID], agora: datetime) -> None:
        """Desativa, sem apagar (R1.7)."""
        ...

    async def list_runs(self, *, limit: int, offset: int) -> tuple[tuple[SyncRun, ...], int]:
        """Uma página das execuções, da mais recente para a mais antiga, e o total (R1.9)."""
        ...

    async def list_groups(
        self,
        *,
        source: OrigemDeGrupo | None,
        active: bool,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[tuple[GroupListing, ...], int]:
        """Uma página dos grupos, por nome, com os membros ativos, e o total (R1.14)."""
        ...

    async def get_run(self, run_id: UUID) -> SyncRun | None: ...


class OidcLoginRequestRepository(Protocol):
    async def add(self, request: OidcLoginRequest) -> None: ...

    async def consume(self, state_hash: str, agora: datetime) -> OidcLoginRequest | None:
        """Marca como usado, num passo só, se ainda não usado nem vencido (R3.7)."""
        ...

    async def delete_expired_before(self, limite: datetime) -> int: ...
