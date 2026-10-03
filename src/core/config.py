"""Configuração da API, lida só de variáveis de ambiente e validada na subida (spec 001, R2)."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, unquote, urlsplit

from pydantic import Field, FilePath, SecretStr, ValidationError, field_validator, model_validator
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


class SettingsError(Exception):
    """Configuração ausente ou inválida: a API não deve iniciar."""


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
        return problems


def load_settings() -> Settings:
    """Lê e valida a configuração. Em caso de erro, a mensagem nomeia cada variável problemática."""
    try:
        return Settings()  # os valores vêm do ambiente
    except ValidationError as error:
        # `from None`: a ValidationError original carrega os valores recebidos, inclusive senhas.
        raise SettingsError(_describe(error)) from None


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
    return password in EXAMPLE_PASSWORDS or any(marker in password for marker in EXAMPLE_MARKERS)


_MESSAGES = {
    "missing": "variável obrigatória não definida",
    "bool_parsing": "use true ou false",
    "int_parsing": "use um número inteiro",
    "path_not_file": "arquivo não encontrado",
}
# Erros levantados pelos validadores acima, já com mensagem em português e sem o valor secreto.
_CUSTOM_ERRORS = frozenset({"origem_invalida", "url_banco_invalida"})


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
