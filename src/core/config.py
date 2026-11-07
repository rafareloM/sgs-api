"""Configuração da API, lida só de variáveis de ambiente e validada na subida (spec 001, R2)."""

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, unquote, urlsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FilePath,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import ErrorDetails, PydanticCustomError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class DatabaseSslMode(StrEnum):
    """Modo TLS da conexão com o PostgreSQL (mesmos nomes do libpq)."""

    DISABLE = "disable"
    REQUIRE = "require"
    VERIFY_FULL = "verify-full"


# Senhas usadas no .env.example e no compose de dev, e marcadores de valor de exemplo.
EXAMPLE_PASSWORDS = frozenset({"sgs", "sgs_api", "postgres", "password", "senha", "admin"})
EXAMPLE_MARKERS = ("troque", "exemplo", "example", "changeme", "change-me")
# TLS do banco é configurado só por DATABASE_SSL_MODE, para não haver duas fontes de verdade.
URL_TLS_PARAMS = frozenset({"ssl", "sslmode", "sslrootcert", "sslcert", "sslkey"})
# `kid` vai no cabeçalho de todo JWT e no JWKS: curto e sem caracteres especiais.
JWT_KID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class SettingsError(Exception):
    """Configuração ausente ou inválida: a API não deve iniciar."""


class JwtSigningKey(BaseModel):
    """Chave privada de assinatura do JWT, identificada pelo `kid` (spec 002, § Chaves JWT)."""

    model_config = ConfigDict(frozen=True)

    kid: str
    pem: SecretStr

    def private_key(self) -> ec.EllipticCurvePrivateKey:
        """Carrega a chave; só aceita chave privada EC P-256 sem senha, a única que assina ES256."""
        try:
            key = load_pem_private_key(self.pem.get_secret_value().encode(), password=None)
        except (ValueError, TypeError, UnsupportedAlgorithm):
            # `from None`: a exceção original pode citar trechos do PEM.
            raise ValueError("chave ilegível") from None
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("a chave não é EC P-256")
        return key


class Settings(BaseSettings):
    """Configuração da API. Cada campo é lido da variável de mesmo nome, em maiúsculas."""

    model_config = SettingsConfigDict(frozen=True)

    app_env: AppEnv
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: Annotated[tuple[str, ...], NoDecode] = ()

    database_url: SecretStr
    database_migration_url: SecretStr | None = None
    database_ssl_mode: DatabaseSslMode = DatabaseSslMode.VERIFY_FULL
    database_ssl_root_cert: FilePath | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=50)

    # Chaves JWT (spec 002, § Chaves JWT): lista JSON de objetos {"kid", "pem"}; a primeira assina.
    # Vêm de JWT_PRIVATE_KEYS ou de um arquivo montado, cujo caminho vai em JWT_PRIVATE_KEYS_FILE
    # (uma das duas). Os dois campos guardam as chaves já lidas; use `jwt_signing_keys`.
    jwt_private_keys: Annotated[tuple[JwtSigningKey, ...], NoDecode] = ()
    jwt_private_keys_file: Annotated[tuple[JwtSigningKey, ...], NoDecode] = ()

    @property
    def jwt_signing_keys(self) -> tuple[JwtSigningKey, ...]:
        """Chaves JWT na ordem configurada, da variável ou do arquivo; a primeira assina."""
        return self.jwt_private_keys or self.jwt_private_keys_file

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("cors_origins")
    @classmethod
    def _validate_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        for origin in origins:
            if not _is_origin(origin):
                raise PydanticCustomError(
                    "origem_invalida",
                    "origem inválida '{origem}'; use esquema://host[:porta], sem caminho",
                    {"origem": origin},
                )
        return origins

    @field_validator("jwt_private_keys", mode="before")
    @classmethod
    def _parse_jwt_keys(cls, value: object) -> object:
        return _parse_jwt_keys(value) if isinstance(value, str) else value

    @field_validator("jwt_private_keys_file", mode="before")
    @classmethod
    def _read_jwt_keys_file(cls, value: object) -> object:
        if not isinstance(value, str | Path):
            return value
        try:
            content = Path(value).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise _jwt_keys_error("arquivo não encontrado ou ilegível") from None
        return _parse_jwt_keys(content)

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        parts = urlsplit(value.get_secret_value())
        if parts.scheme != "postgresql+asyncpg":
            raise PydanticCustomError("url_banco_invalida", "use o esquema postgresql+asyncpg://")
        if not parts.hostname or not parts.path.strip("/"):
            raise PydanticCustomError("url_banco_invalida", "informe o host e o nome do banco")
        if URL_TLS_PARAMS & {key.lower() for key, _ in parse_qsl(parts.query)}:
            raise PydanticCustomError(
                "url_banco_invalida", "configure o TLS só por DATABASE_SSL_MODE, não na URL"
            )
        return value

    @model_validator(mode="after")
    def _check_environment(self) -> Self:
        problems: list[str] = []
        if self.app_env is AppEnv.DEV and self.database_migration_url is None:
            problems.append(
                "DATABASE_MIGRATION_URL: obrigatória em dev, onde as migrações rodam na subida"
            )
        if not self.jwt_private_keys and not self.jwt_private_keys_file:
            problems.append(
                "JWT_PRIVATE_KEYS: variável obrigatória não definida "
                "(ou JWT_PRIVATE_KEYS_FILE, com o caminho do arquivo das chaves)"
            )
        elif self.jwt_private_keys and self.jwt_private_keys_file:
            problems.append(
                "JWT_PRIVATE_KEYS_FILE: defina as chaves JWT só nela ou só em JWT_PRIVATE_KEYS"
            )
        if self.app_env is AppEnv.PROD:
            problems.extend(self._production_problems())
        if problems:
            raise PydanticCustomError(
                "configuracao_recusada", "{problemas}", {"problemas": "\n- ".join(problems)}
            )
        return self

    def _production_problems(self) -> list[str]:
        problems: list[str] = []
        if self.debug:
            problems.append("DEBUG: não pode ficar ligado em prod")
        if self.database_ssl_mode is not DatabaseSslMode.VERIFY_FULL:
            problems.append("DATABASE_SSL_MODE: prod exige verify-full")
        urls = {
            "DATABASE_URL": self.database_url,
            "DATABASE_MIGRATION_URL": self.database_migration_url,
        }
        for name, url in urls.items():
            if url is not None and _uses_example_password(url.get_secret_value()):
                problems.append(f"{name}: senha de exemplo não é aceita em prod")
        jwt_keys = {
            "JWT_PRIVATE_KEYS": self.jwt_private_keys,
            "JWT_PRIVATE_KEYS_FILE": self.jwt_private_keys_file,
        }
        for name, keys in jwt_keys.items():
            # Nenhuma chave real vai para o repositório; a de exemplo se reconhece pelo `kid`.
            if any(_is_example(key.kid) for key in keys):
                problems.append(f"{name}: chave de exemplo não é aceita em prod")
        return problems


def load_settings() -> Settings:
    """Lê e valida a configuração. Em caso de erro, a mensagem nomeia cada variável problemática."""
    try:
        return Settings()  # os valores vêm do ambiente
    except ValidationError as error:
        # `from None`: a ValidationError original carrega os valores recebidos, inclusive senhas.
        raise SettingsError(_describe(error)) from None


def _parse_jwt_keys(raw: str) -> tuple[JwtSigningKey, ...]:
    """Lê a lista JSON de chaves JWT. Os erros citam a posição e o `kid`, nunca o PEM."""
    try:
        items = json.loads(raw)
    except ValueError:
        raise _jwt_keys_error("use uma lista JSON de objetos com kid e pem") from None
    if not isinstance(items, list) or not items:
        raise _jwt_keys_error(
            "informe ao menos uma chave, numa lista JSON de objetos com kid e pem"
        )
    keys: list[JwtSigningKey] = []
    for position, item in enumerate(items, start=1):
        if not (isinstance(item, dict) and set(item) == {"kid", "pem"}) or not all(
            isinstance(field, str) for field in item.values()
        ):
            raise _jwt_keys_error(f"chave {position}: use um objeto só com kid e pem, em texto")
        if not JWT_KID.fullmatch(item["kid"]):
            raise _jwt_keys_error(
                f"chave {position}: kid inválido; use até 64 letras, dígitos, '.', '-' ou '_'"
            )
        key = JwtSigningKey(kid=item["kid"], pem=SecretStr(item["pem"]))
        try:
            key.private_key()
        except ValueError:
            raise _jwt_keys_error(
                f"chave {key.kid}: use uma chave privada EC P-256 em PEM, sem senha"
            ) from None
        if any(other.kid == key.kid for other in keys):
            raise _jwt_keys_error(f"kid repetido: {key.kid}")
        keys.append(key)
    return tuple(keys)


def _jwt_keys_error(detail: str) -> PydanticCustomError:
    return PydanticCustomError("chaves_jwt_invalidas", "{detalhe}", {"detalhe": detail})


def _is_origin(origin: str) -> bool:
    try:
        parts = urlsplit(origin)
        _ = parts.port  # porta inválida levanta ValueError
    except ValueError:
        return False
    return (
        parts.scheme in {"http", "https"}
        and bool(parts.hostname)
        and parts.username is None
        and not (parts.path or parts.query or parts.fragment)
    )


def _uses_example_password(url: str) -> bool:
    password = unquote(urlsplit(url).password or "").lower()
    return password in EXAMPLE_PASSWORDS or _is_example(password)


def _is_example(value: str) -> bool:
    return any(marker in value.lower() for marker in EXAMPLE_MARKERS)


_MESSAGES = {
    "missing": "variável obrigatória não definida",
    "bool_parsing": "use true ou false",
    "int_parsing": "use um número inteiro",
    "path_not_file": "arquivo não encontrado",
}
# Erros levantados pelos validadores acima, já com mensagem em português e sem o valor secreto.
_CUSTOM_ERRORS = frozenset({"origem_invalida", "url_banco_invalida", "chaves_jwt_invalidas"})


def _describe(error: ValidationError) -> str:
    items = [_describe_item(item) for item in error.errors(include_input=False, include_url=False)]
    return "Configuração inválida; a API não vai iniciar:\n" + "\n".join(f"- {i}" for i in items)


def _describe_item(item: ErrorDetails) -> str:
    if not item["loc"]:
        return item["msg"]
    variable = str(item["loc"][0]).upper()
    context = item.get("ctx", {})
    match item["type"]:
        case "enum" | "literal_error":
            options = str(context.get("expected", "")).replace(" or ", " ou ")
            message = f"valor inválido; opções: {options}"
        case "greater_than_equal":
            message = f"deve ser maior ou igual a {context.get('ge')}"
        case "less_than_equal":
            message = f"deve ser menor ou igual a {context.get('le')}"
        case kind if kind in _MESSAGES:
            message = _MESSAGES[kind]
        case kind if kind in _CUSTOM_ERRORS:
            message = item["msg"]
        case _:
            message = "valor inválido"
    return f"{variable}: {message}"
