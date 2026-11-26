"""Configuração da API, lida só de variáveis de ambiente e validada na subida (spec 001, R2)."""

import base64
import binascii
import json
import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, unquote, urlsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FilePath,
    SecretBytes,
    SecretStr,
    ValidationError,
    ValidationInfo,
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
# Retorno do provedor OIDC: só o callback da API (004/R3.8, design § Configuração).
OIDC_CALLBACK_PATH = "/api/v1/auth/oidc/callback"
# Nomes de atributo LDAP: entram nos filtros e na lista de atributos pedidos (004, design).
LDAP_ATTRIBUTE = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,63}")
LDAP_PAGE_SIZE_MAX = 1000
# Chave KMS como ARN de chave, nunca alias nem id solto: a resposta do PutObject traz o ARN, e a
# conferência da gravação é exata (005, D005-5). Vale para as partições da AWS e para as chaves
# multirregião (`mrk-`); o id vem em minúsculas, como a AWS o devolve. A conta é `[0-9]`, não `\d`,
# que aceitaria dígitos Unicode.
KMS_KEY_ARN = re.compile(
    r"arn:aws(?:-[a-z]+)*:kms:[a-z0-9-]+:[0-9]{12}:key/"
    r"(?:mrk-[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


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

    # Chaves de assinatura dos relatórios (005, design § Assinatura): mesmo formato e mesmo leitor
    # das chaves JWT, mas chaves próprias (R5.2), em REPORT_SIGNING_KEYS ou num arquivo montado
    # (REPORT_SIGNING_KEYS_FILE); a primeira assina e todas são publicadas. Use
    # `chaves_de_relatorio`.
    report_signing_keys: Annotated[tuple[JwtSigningKey, ...], NoDecode] = ()
    report_signing_keys_file: Annotated[tuple[JwtSigningKey, ...], NoDecode] = ()

    # S3 dos relatórios (005, design § Configuração). Sem S3_BUCKET, a exportação fica desligada
    # fora de prod; em prod, o acesso é só pelo papel, com ExternalId e chave KMS (R2.9).
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = None  # padrão: S3_ENDPOINT_URL; use `s3_endpoint_publico`
    s3_ca_file: FilePath | None = None
    s3_addressing_style: Literal["virtual", "path"] = "virtual"
    s3_assume_role_arn: str | None = None
    s3_external_id: str | None = None
    s3_kms_key_id: str | None = None
    s3_sse: Literal["aws:kms", "AES256"] = "AES256"
    # Chaves fixas do laboratório, só fora de prod (R2.2).
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    # Variáveis do SDK da AWS, declaradas só para a recusa em prod: o boto3 as leria antes do papel.
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None
    aws_profile: str | None = None
    aws_default_profile: str | None = None  # nome antigo do AWS_PROFILE, ainda lido pelo botocore
    # Guarda dos relatórios no bucket, em dias (G1 da 005).
    report_retention_days: int = Field(default=90, ge=1, le=3650)

    @field_validator(
        "s3_bucket",
        "s3_region",
        "s3_endpoint_url",
        "s3_public_endpoint_url",
        "s3_ca_file",
        "s3_assume_role_arn",
        "s3_external_id",
        "s3_kms_key_id",
        "s3_access_key_id",
        "s3_secret_access_key",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "aws_profile",
        "aws_default_profile",
        mode="before",
    )
    @classmethod
    def _s3_empty_is_unset(cls, value: object) -> object:
        # `S3_ASSUME_ROLE_ARN=` num arquivo de ambiente (como no .env.example) não é um valor.
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def exportacao_ligada(self) -> bool:
        """A exportação de relatórios só funciona com S3_BUCKET; sem ele, as rotas dão 503."""
        return self.s3_bucket is not None

    @property
    def s3_endpoint_publico(self) -> str | None:
        """Endereço das URLs de download (005/R3.6): S3_PUBLIC_ENDPOINT_URL ou o interno."""
        return self.s3_public_endpoint_url or self.s3_endpoint_url

    # Chaves do `FieldCipher` (spec 002, T5): objeto JSON {"<versão>": "<32 bytes em base64>"}
    # em CRYPTO_KEYS ou num arquivo montado (CRYPTO_KEYS_FILE); CRYPTO_ACTIVE_KEY diz qual cifra.
    crypto_keys: Annotated[Mapping[int, SecretBytes], NoDecode] = Field(default_factory=dict)
    crypto_keys_file: Annotated[Mapping[int, SecretBytes], NoDecode] = Field(default_factory=dict)
    crypto_active_key: int | None = None

    # TOTP obrigatório para contas locais (002, design § Decisões); desligável só em dev.
    mfa_obrigatorio: bool = True

    # OIDC (004, design § Configuração). Sem OIDC_ISSUER, o OIDC fica desligado e as demais
    # variáveis OIDC não são conferidas; com ela, `_oidc_problems` confere todas.
    oidc_issuer: str | None = None
    oidc_discovery_url: str | None = None
    oidc_ca_file: Path | None = None  # conferida em `_oidc_problems`, só com o OIDC ligado
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_redirect_uri: str | None = None
    frontend_url: str | None = None
    oidc_groups_claim: str = "groups"
    oidc_required_acr: Annotated[tuple[str, ...], NoDecode] = ()

    # LDAP (004, design § Configuração). Sem LDAP_URL, o LDAP fica desligado e as demais
    # variáveis LDAP não são conferidas; com ela, `_ldap_problems` confere todas.
    ldap_url: str | None = None
    ldap_start_tls: bool = False
    ldap_ca_file: str | None = None
    ldap_bind_dn: str | None = None
    ldap_bind_password: SecretStr | None = None
    ldap_user_base: str | None = None
    ldap_user_filter: str | None = None
    ldap_group_base: str | None = None
    ldap_group_filter: str | None = None
    ldap_attr_login: str = "uid"
    ldap_attr_email: str = "mail"
    ldap_attr_name: str = "cn"
    ldap_attr_id: str = "entryUUID"  # vazio: o DN é o identificador externo (R1.5)
    ldap_attr_member: str = "member"
    ldap_page_size: int = 500
    # Subconjunto de cron no fuso de Recife (R1.12); conferido pela raiz de composição, que usa
    # o analisador do domínio da 004 (design § Agendamento).
    ldap_sync_cron: str | None = None

    @field_validator(
        "ldap_url",
        "ldap_ca_file",
        "ldap_bind_dn",
        "ldap_bind_password",
        "ldap_user_base",
        "ldap_user_filter",
        "ldap_group_base",
        "ldap_group_filter",
        "ldap_sync_cron",
        mode="before",
    )
    @classmethod
    def _ldap_empty_is_unset(cls, value: object) -> object:
        # `LDAP_URL=` num arquivo de ambiente desliga o LDAP, em vez de virar texto vazio.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "oidc_issuer",
        "oidc_discovery_url",
        "oidc_ca_file",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_redirect_uri",
        "frontend_url",
        mode="before",
    )
    @classmethod
    def _oidc_empty_is_unset(cls, value: object) -> object:
        # `OIDC_ISSUER=` num arquivo de ambiente desliga o OIDC, em vez de virar texto vazio.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("oidc_required_acr", mode="before")
    @classmethod
    def _split_acr(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @property
    def oidc_discovery_endpoint(self) -> str | None:
        """OIDC_DISCOVERY_URL ou, sem ela, o documento de descoberta do próprio emissor."""
        if self.oidc_issuer is None:
            return None
        return self.oidc_discovery_url or (
            self.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
        )

    @property
    def chaves_de_cifra(self) -> dict[int, bytes]:
        """As chaves do `FieldCipher`, de CRYPTO_KEYS ou do arquivo, já validadas."""
        origem = self.crypto_keys or self.crypto_keys_file
        return {versao: chave.get_secret_value() for versao, chave in origem.items()}

    @field_validator("crypto_keys", mode="before")
    @classmethod
    def _parse_crypto_keys(cls, value: object) -> object:
        return _parse_crypto_keys(value) if isinstance(value, str) else value

    @field_validator("crypto_keys_file", mode="before")
    @classmethod
    def _read_crypto_keys_file(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            content = Path(value).read_text(encoding="utf-8")
        except OSError:
            raise _crypto_keys_error("arquivo não encontrado ou ilegível") from None
        return _parse_crypto_keys(content)

    @property
    def jwt_signing_keys(self) -> tuple[JwtSigningKey, ...]:
        """Chaves JWT na ordem configurada, da variável ou do arquivo; a primeira assina."""
        return self.jwt_private_keys or self.jwt_private_keys_file

    @property
    def chaves_de_relatorio(self) -> tuple[JwtSigningKey, ...]:
        """Chaves de assinatura dos relatórios, da variável ou do arquivo; a primeira assina."""
        return self.report_signing_keys or self.report_signing_keys_file

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

    @field_validator("jwt_private_keys", "report_signing_keys", mode="before")
    @classmethod
    def _parse_jwt_keys(cls, value: object, info: ValidationInfo) -> object:
        if _is_blank_optional_keys(value, info):
            return ()
        return _parse_jwt_keys(value) if isinstance(value, str) else value

    @field_validator("jwt_private_keys_file", "report_signing_keys_file", mode="before")
    @classmethod
    def _read_jwt_keys_file(cls, value: object, info: ValidationInfo) -> object:
        if _is_blank_optional_keys(value, info):
            return ()
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
        problems.extend(self._report_signing_problems())
        problems.extend(self._s3_problems())
        problems.extend(self._crypto_problems())
        problems.extend(self._oidc_problems())
        problems.extend(self._ldap_problems())
        if not self.mfa_obrigatorio and self.app_env is not AppEnv.DEV:
            problems.append("MFA_OBRIGATORIO: só pode ser desligado em dev")
        if self.app_env is AppEnv.PROD:
            problems.extend(self._production_problems())
        if problems:
            raise PydanticCustomError(
                "configuracao_recusada", "{problemas}", {"problemas": "\n- ".join(problems)}
            )
        return self

    def _crypto_problems(self) -> list[str]:
        if not self.crypto_keys and not self.crypto_keys_file:
            return [
                "CRYPTO_KEYS: variável obrigatória não definida "
                "(ou CRYPTO_KEYS_FILE, com o caminho do arquivo das chaves)"
            ]
        if self.crypto_keys and self.crypto_keys_file:
            return ["CRYPTO_KEYS_FILE: defina as chaves só nela ou só em CRYPTO_KEYS"]
        if self.crypto_active_key is None:
            return ["CRYPTO_ACTIVE_KEY: variável obrigatória não definida"]
        if self.crypto_active_key not in self.chaves_de_cifra:
            return ["CRYPTO_ACTIVE_KEY: não há chave com essa versão em CRYPTO_KEYS"]
        return []

    def _report_signing_problems(self) -> list[str]:
        """REPORT_SIGNING_KEYS(_FILE): uma fonte só, chaves que não são as JWT (005/R5.2) e, em
        prod, nenhuma chave de exemplo (design da 005, § Configuração)."""
        sources = {
            "REPORT_SIGNING_KEYS": self.report_signing_keys,
            "REPORT_SIGNING_KEYS_FILE": self.report_signing_keys_file,
        }
        if all(sources.values()):
            return [
                "REPORT_SIGNING_KEYS_FILE: defina as chaves de relatório só nela "
                "ou só em REPORT_SIGNING_KEYS"
            ]
        jwt_kids = {key.kid for key in self.jwt_signing_keys}
        jwt_points = {_public_point(key) for key in self.jwt_signing_keys}
        problems: list[str] = []
        for name, keys in sources.items():
            problems.extend(
                f"{name}: a chave {key.kid} repete o kid ou a chave pública de uma chave JWT; "
                "use chaves só para os relatórios"
                for key in keys
                if key.kid in jwt_kids or _public_point(key) in jwt_points
            )
            if self.app_env is AppEnv.PROD and any(_is_example(key.kid) for key in keys):
                problems.append(f"{name}: chave de exemplo não é aceita em prod")
        return problems

    def _s3_problems(self) -> list[str]:
        """005/R2.2, R2.7 e R2.9 (design § Configuração). Os endereços valem sempre que definidos;
        o S3 só é obrigatório em prod, onde vale apenas o papel, com ExternalId e chave KMS."""
        urls = {
            "S3_ENDPOINT_URL": self.s3_endpoint_url,
            "S3_PUBLIC_ENDPOINT_URL": self.s3_public_endpoint_url,
        }
        problems = [
            f"{name}: use um endereço https://"
            for name, url in urls.items()
            if url is not None and not is_https_url(url)
        ]
        if self.s3_kms_key_id is not None and not KMS_KEY_ARN.fullmatch(self.s3_kms_key_id):
            # Opcional fora de prod, mas, se vier, como ARN: senão nenhuma gravação confere.
            problems.append(
                "S3_KMS_KEY_ID: use o ARN da chave (arn:aws:kms:<região>:<conta>:key/<id>)"
            )
        if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
            problems.append(
                "S3_SECRET_ACCESS_KEY: defina junto com S3_ACCESS_KEY_ID (as duas ou nenhuma)"
            )
        if self.exportacao_ligada and not self.chaves_de_relatorio:
            # Todo relatório exportado sai assinado (R5.1).
            problems.append(
                "REPORT_SIGNING_KEYS: obrigatória com S3_BUCKET (ou REPORT_SIGNING_KEYS_FILE)"
            )
        if self.app_env is AppEnv.PROD:
            problems.extend(self._s3_production_problems())
        return problems

    def _s3_production_problems(self) -> list[str]:
        """R2.9: sem papel, ExternalId, chave KMS ou `aws:kms`, ou com chave fixa, a API não sobe em
        prod (R2.1 a R2.3). O formato da chave KMS é conferido em `_s3_problems`."""
        required = {
            "S3_BUCKET": self.s3_bucket,
            "S3_ASSUME_ROLE_ARN": self.s3_assume_role_arn,
            "S3_EXTERNAL_ID": self.s3_external_id,
            "S3_KMS_KEY_ID": self.s3_kms_key_id,
        }
        problems = [f"{name}: obrigatória em prod" for name, v in required.items() if v is None]
        if self.s3_sse != "aws:kms":
            problems.append("S3_SSE: prod exige aws:kms")
        static_keys = {
            "S3_ACCESS_KEY_ID": self.s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
            "AWS_ACCESS_KEY_ID": self.aws_access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.aws_secret_access_key,
            "AWS_SESSION_TOKEN": self.aws_session_token,
            "AWS_PROFILE": self.aws_profile,
            "AWS_DEFAULT_PROFILE": self.aws_default_profile,
        }
        problems.extend(
            f"{name}: chave fixa não é aceita em prod; o acesso é pelo papel de S3_ASSUME_ROLE_ARN"
            for name, value in static_keys.items()
            if value is not None
        )
        return problems

    def _oidc_problems(self) -> list[str]:
        """004/R3.2, R3.8 e R5.4 (design § Configuração). Só com o OIDC ligado (OIDC_ISSUER)."""
        if self.oidc_issuer is None:
            return []
        required = {
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
            "OIDC_REDIRECT_URI": self.oidc_redirect_uri,
            "FRONTEND_URL": self.frontend_url,
        }
        problems = [
            f"{name}: obrigatória com OIDC_ISSUER" for name, v in required.items() if v is None
        ]
        urls = {
            "OIDC_ISSUER": self.oidc_issuer,
            "OIDC_DISCOVERY_URL": self.oidc_discovery_url,
            "OIDC_REDIRECT_URI": self.oidc_redirect_uri,
            "FRONTEND_URL": self.frontend_url,
        }
        for name, url in urls.items():
            if url is not None and not is_https_url(url):
                problems.append(f"{name}: use um endereço https://")
        # O `iss` é comparado byte a byte e dá a descoberta padrão; o retorno é o registrado.
        fixed = {"OIDC_ISSUER": self.oidc_issuer, "OIDC_REDIRECT_URI": self.oidc_redirect_uri}
        for name, url in fixed.items():
            if url is not None and ("?" in url or "#" in url):
                problems.append(f"{name}: não use query nem fragmento")
        if self.oidc_ca_file is not None and not self.oidc_ca_file.is_file():
            problems.append("OIDC_CA_FILE: arquivo não encontrado")
        if not self.oidc_groups_claim.strip():
            problems.append("OIDC_GROUPS_CLAIM: informe o nome da claim de grupos do id_token")
        redirect, frontend = self.oidc_redirect_uri, self.frontend_url
        if redirect and is_https_url(redirect) and urlsplit(redirect).path != OIDC_CALLBACK_PATH:
            problems.append(f"OIDC_REDIRECT_URI: o caminho tem de ser {OIDC_CALLBACK_PATH}")
        if frontend and is_https_url(frontend):
            problems.extend(self._frontend_problems(frontend))
            # O link de login é relativo, e os cookies `sgs_oidc` e de refresh valem só no host
            # que os gravou: o callback e o front têm de estar na mesma origem.
            origin = _browser_origin(frontend)
            if redirect and is_https_url(redirect) and _browser_origin(redirect) != origin:
                problems.append(f"OIDC_REDIRECT_URI: use a mesma origem de FRONTEND_URL ({origin})")
        secret = self.oidc_client_secret
        if (
            self.app_env is AppEnv.PROD
            and secret is not None
            and _is_example_secret(secret.get_secret_value())
        ):
            problems.append("OIDC_CLIENT_SECRET: segredo de exemplo não é aceito em prod")
        return problems

    def problemas_do_ldap(self) -> list[str]:
        """As regras LDAP da subida, para conferir valores trocados depois (`sgs-admin diretorio
        testar --url --ca`)."""
        return self._ldap_problems()

    def _ldap_problems(self) -> list[str]:
        """004/R1.2 a R1.5 e R5.4 (design § Configuração). Só com o LDAP ligado (LDAP_URL)."""
        if self.ldap_url is None:
            return []
        problems: list[str] = []
        if not _is_ldap_tls_url(self.ldap_url, start_tls=self.ldap_start_tls):
            problems.append(
                "LDAP_URL: use ldaps://host[:porta], ou ldap://host[:porta] com LDAP_START_TLS=true"
            )
        if self.ldap_start_tls and self.ldap_url.startswith("ldaps://"):
            problems.append("LDAP_START_TLS: só com ldap://; ldaps:// já abre a conexão em TLS")
        required = {
            "LDAP_CA_FILE": self.ldap_ca_file,
            "LDAP_BIND_DN": self.ldap_bind_dn,
            "LDAP_BIND_PASSWORD": self.ldap_bind_password,
            "LDAP_USER_BASE": self.ldap_user_base,
            "LDAP_USER_FILTER": self.ldap_user_filter,
            "LDAP_GROUP_BASE": self.ldap_group_base,
            "LDAP_GROUP_FILTER": self.ldap_group_filter,
        }
        problems.extend(
            f"{name}: obrigatória com LDAP_URL" for name, v in required.items() if v is None
        )
        if self.ldap_ca_file is not None and not Path(self.ldap_ca_file).is_file():
            problems.append("LDAP_CA_FILE: arquivo não encontrado")
        attributes = {
            "LDAP_ATTR_LOGIN": self.ldap_attr_login,
            "LDAP_ATTR_EMAIL": self.ldap_attr_email,
            "LDAP_ATTR_NAME": self.ldap_attr_name,
            "LDAP_ATTR_MEMBER": self.ldap_attr_member,
        }
        if self.ldap_attr_id:  # vazio usa o DN (R1.5)
            attributes["LDAP_ATTR_ID"] = self.ldap_attr_id
        problems.extend(
            f"{name}: nome de atributo inválido; use letras, dígitos e '-', começando por letra"
            for name, value in attributes.items()
            if not LDAP_ATTRIBUTE.fullmatch(value)
        )
        if not 1 <= self.ldap_page_size <= LDAP_PAGE_SIZE_MAX:
            problems.append(f"LDAP_PAGE_SIZE: use de 1 a {LDAP_PAGE_SIZE_MAX}")
        password = self.ldap_bind_password
        if (
            self.app_env is AppEnv.PROD
            and password is not None
            and _is_example_secret(password.get_secret_value())
        ):
            problems.append("LDAP_BIND_PASSWORD: senha de exemplo não é aceita em prod")
        return problems

    def _frontend_problems(self, url: str) -> list[str]:
        """Destino do retorno OIDC: fixo, sem query nem fragmento (sem redirecionamento aberto)."""
        if not url.endswith("/") or "?" in url or "#" in url:
            return ["FRONTEND_URL: termine em / e não use query nem fragmento"]
        origin = _browser_origin(url)
        if origin not in self.cors_origins:
            # O front renova a sessão dali, e o refresh procura o `Origin` que o navegador manda,
            # texto a texto, em CORS_ORIGINS. Por isso só este lado é normalizado.
            return [f"FRONTEND_URL: a origem {origin} precisa estar em CORS_ORIGINS"]
        return []

    def _production_problems(self) -> list[str]:
        problems: list[str] = []
        if any(chave == bytes(CRYPTO_KEY_BYTES) for chave in self.chaves_de_cifra.values()):
            problems.append("CRYPTO_KEYS: chave de exemplo (só zeros) não é aceita em prod")
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


CRYPTO_KEY_BYTES = 32


def _parse_crypto_keys(raw: str) -> dict[int, SecretBytes]:
    """`{"1": "<base64 de 32 bytes>"}` → {1: SecretBytes}. Os valores nunca entram na mensagem."""
    try:
        bruto = json.loads(raw)
    except json.JSONDecodeError:
        raise _crypto_keys_error('use um objeto JSON {"versão": "chave em base64"}') from None
    if not isinstance(bruto, dict) or not bruto:
        raise _crypto_keys_error("use um objeto JSON com ao menos uma chave")
    chaves: dict[int, SecretBytes] = {}
    for versao, valor in bruto.items():
        try:
            numero = int(versao)
            chave = base64.b64decode(str(valor), validate=True)
        except (ValueError, binascii.Error):
            raise _crypto_keys_error("versão inteira e chave em base64") from None
        if numero < 1 or len(chave) != CRYPTO_KEY_BYTES:
            raise _crypto_keys_error(
                f"cada chave precisa de {CRYPTO_KEY_BYTES} bytes e versão >= 1"
            )
        chaves[numero] = SecretBytes(chave)
    return chaves


def _crypto_keys_error(detalhe: str) -> PydanticCustomError:
    return PydanticCustomError("chaves_de_cifra_invalidas", "{detalhe}", {"detalhe": detalhe})


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


# As chaves de relatório são opcionais (sem chave, nada é assinado): `REPORT_SIGNING_KEYS=` num
# arquivo de ambiente vale como não definida, como em `_oidc_empty_is_unset`. As chaves JWT são
# obrigatórias, e a variável vazia continua recusada pelo leitor.
_OPTIONAL_KEY_FIELDS = frozenset({"report_signing_keys", "report_signing_keys_file"})


def _is_blank_optional_keys(value: object, info: ValidationInfo) -> bool:
    return info.field_name in _OPTIONAL_KEY_FIELDS and isinstance(value, str) and not value.strip()


def _jwt_keys_error(detail: str) -> PydanticCustomError:
    return PydanticCustomError("chaves_jwt_invalidas", "{detalhe}", {"detalhe": detail})


def _public_point(key: JwtSigningKey) -> bytes:
    """Chave pública como ponto não comprimido: compara chaves sem expor a privada."""
    public = key.private_key().public_key()
    return public.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


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


def is_https_url(url: str) -> bool:
    """`https://` com host e sem credenciais; vale também para os endereços da descoberta OIDC
    (`identity/infrastructure/authlib_oidc.py`)."""
    try:
        parts = urlsplit(url)
        _ = parts.port  # porta inválida levanta ValueError
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and parts.username is None


def _browser_origin(url: str) -> str:
    """Origem de um endereço https:// como o navegador a manda no `Origin` (RFC 6454 § 6.2):
    esquema e host em minúsculas, sem a porta 443."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:  # IPv6 volta entre colchetes
        host = f"[{host}]"
    port = "" if parts.port in (None, 443) else f":{parts.port}"
    return f"https://{host}{port}"


def _is_ldap_tls_url(url: str, *, start_tls: bool) -> bool:
    """`ldaps://host[:porta]`, ou `ldap://host[:porta]` só com StartTLS (004/R1.2)."""
    try:
        parts = urlsplit(url)
        _ = parts.port  # porta inválida levanta ValueError
    except ValueError:
        return False
    schemes = {"ldaps", "ldap"} if start_tls else {"ldaps"}
    return (
        parts.scheme in schemes
        and bool(parts.hostname)
        and parts.username is None
        and parts.path in {"", "/"}
        and not (parts.query or parts.fragment)
    )


def _uses_example_password(url: str) -> bool:
    password = unquote(urlsplit(url).password or "").lower()
    return password in EXAMPLE_PASSWORDS or _is_example(password)


def _is_example_secret(secret: str) -> bool:
    """A regra de `_uses_example_password` (001/R2.3) para um segredo solto (004/R5.4)."""
    return secret.lower() in EXAMPLE_PASSWORDS or _is_example(secret)


def _is_example(value: str) -> bool:
    return any(marker in value.lower() for marker in EXAMPLE_MARKERS)


_MESSAGES = {
    "missing": "variável obrigatória não definida",
    "bool_parsing": "use true ou false",
    "int_parsing": "use um número inteiro",
    "path_not_file": "arquivo não encontrado",
}
# Erros levantados pelos validadores acima, já com mensagem em português e sem o valor secreto.
_CUSTOM_ERRORS = frozenset(
    {"origem_invalida", "url_banco_invalida", "chaves_jwt_invalidas", "chaves_de_cifra_invalidas"}
)


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
