"""Fábricas de objetos usados nos testes (steering/testing.md: funções make_*)."""

import json
import secrets
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from src.core.config import AppEnv, DatabaseSslMode, Settings
from src.core.ids import uuid7
from src.modules.identity.domain.sessions import AuthSession, RefreshToken, hash_refresh_token
from src.modules.identity.domain.users import User, UserSource

# Banco fictício: os testes que precisam de banco de verdade usam tests/integration/conftest.py.
URL_SEM_BANCO = "postgresql+asyncpg://sgs_api:sgs_api@127.0.0.1:1/sgs"

# Hash Argon2id (formato PHC) de uma senha de teste; nos testes ele é só um dado.
ARGON2ID_DE_TESTE = (
    "$argon2id$v=19$m=65536,t=3,p=4$YxqVkrRrqLmQ9woZLsBFRA"
    "$vJSDeU0/lJlyM62jPEdu74pquyj1q3ELup5LW3fP98w"
)
# Hash bcrypt usado no PR #5 (esquema da disciplina): é hash, mas não é Argon2id.
HASH_BCRYPT = "$2b$12$GkQ1zKVQJcF9m6mB0KKxvu3fd8m2fGXQxmz9g8rM3S5uW1aQw9J3."

INICIO_DA_SESSAO = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


class _SettingsSemAmbiente(Settings):
    """Settings que ignora as variáveis de ambiente da máquina: o teste diz tudo o que vale."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def make_pem_privado(curva: ec.EllipticCurve | None = None) -> str:
    """Chave privada EC nova em PEM (PKCS#8), gerada na hora: nenhuma chave vai para o Git."""
    chave = ec.generate_private_key(curva or ec.SECP256R1())
    return chave.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


def make_jwt_private_keys(*kids: str) -> str:
    """Valor de JWT_PRIVATE_KEYS com uma chave P-256 nova por `kid`; a primeira assina."""
    return json.dumps([{"kid": kid, "pem": make_pem_privado()} for kid in kids or ("teste",)])


@cache
def _jwt_private_keys_de_teste() -> str:
    # Uma chave por processo de teste basta para quem só precisa montar o app.
    return make_jwt_private_keys("teste")


def make_settings(**overrides: Any) -> Settings:
    valores: dict[str, Any] = {
        "app_env": AppEnv.TEST,
        "database_url": SecretStr(URL_SEM_BANCO),
        "database_ssl_mode": DatabaseSslMode.DISABLE,
        "jwt_private_keys": _jwt_private_keys_de_teste(),
    }
    return _SettingsSemAmbiente(**(valores | overrides))


def make_user(**overrides: Any) -> User:
    """Usuário local ativo, com hash Argon2id."""
    valores: dict[str, Any] = {
        "id": uuid7(),
        "username": "maria.silva",
        "display_name": "Maria Silva",
        "email": "maria.silva@example.org",
        "source": UserSource.LOCAL,
        "password_hash": ARGON2ID_DE_TESTE,
    }
    return User(**(valores | overrides))


def make_auth_session(**overrides: Any) -> AuthSession:
    valores: dict[str, Any] = {
        "id": uuid7(),
        "user_id": uuid7(),
        "amr": "pwd+otp",
        "created_at": INICIO_DA_SESSAO,
    }
    return AuthSession(**(valores | overrides))


def make_refresh_token(**overrides: Any) -> RefreshToken:
    valores: dict[str, Any] = {
        "id": uuid7(),
        "session_id": uuid7(),
        "family_id": uuid7(),
        "token_hash": hash_refresh_token(secrets.token_urlsafe(32)),
        "expires_at": INICIO_DA_SESSAO + timedelta(hours=8),
    }
    return RefreshToken(**(valores | overrides))
