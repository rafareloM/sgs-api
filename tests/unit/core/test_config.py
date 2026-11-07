"""Configuração por ambiente (spec 001, R2), com as chaves JWT da spec 002 (T4)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

from src.core.config import AppEnv, Settings, SettingsError, load_settings
from src.tools import jwt_keys
from tests.factories import make_jwt_private_keys, make_pem_privado

type DefinirAmbiente = Callable[[dict[str, str]], None]

VARIAVEIS_DEV = {
    "APP_ENV": "dev",
    "DATABASE_URL": "postgresql+asyncpg://sgs_api:sgs_api@db:5432/sgs",
    "DATABASE_MIGRATION_URL": "postgresql+asyncpg://sgs:sgs@db:5432/sgs",
    "DATABASE_SSL_MODE": "disable",
    "JWT_PRIVATE_KEYS": make_jwt_private_keys("dev"),
}

VARIAVEIS_PROD = {
    "APP_ENV": "prod",
    "DATABASE_URL": "postgresql+asyncpg://sgs_api:Kx9-segredo-de-verdade@db.interno:5432/sgs",
    "DATABASE_SSL_MODE": "verify-full",
    "JWT_PRIVATE_KEYS": make_jwt_private_keys("2026-11"),
}


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> DefinirAmbiente:
    """Apaga as variáveis conhecidas e devolve uma função que define as do teste."""
    for campo in Settings.model_fields:
        monkeypatch.delenv(campo.upper(), raising=False)

    def definir(variaveis: dict[str, str]) -> None:
        for nome, valor in variaveis.items():
            monkeypatch.setenv(nome, valor)

    return definir


def test_le_a_configuracao_das_variaveis_de_ambiente(ambiente: DefinirAmbiente) -> None:
    """001/R2.1"""
    ambiente(
        {
            **VARIAVEIS_DEV,
            "CORS_ORIGINS": "https://localhost:3000, https://sgs.localhost",
            "LOG_LEVEL": "DEBUG",
            "DATABASE_POOL_SIZE": "3",
        }
    )

    settings = load_settings()

    assert settings.app_env is AppEnv.DEV
    assert settings.cors_origins == ("https://localhost:3000", "https://sgs.localhost")
    assert settings.log_level == "DEBUG"
    assert settings.database_pool_size == 3
    assert settings.database_url.get_secret_value() == VARIAVEIS_DEV["DATABASE_URL"]


@pytest.mark.parametrize("app_env", ["dev", "test", "prod"])
def test_aceita_os_tres_ambientes(ambiente: DefinirAmbiente, app_env: str) -> None:
    """001/R2.1"""
    variaveis = VARIAVEIS_PROD if app_env == "prod" else VARIAVEIS_DEV
    ambiente({**variaveis, "APP_ENV": app_env})

    assert load_settings().app_env == app_env


@pytest.mark.parametrize(
    "variavel", ["APP_ENV", "DATABASE_URL", "DATABASE_MIGRATION_URL", "JWT_PRIVATE_KEYS"]
)
def test_recusa_iniciar_sem_variavel_obrigatoria_e_nomeia_a_variavel(
    ambiente: DefinirAmbiente, variavel: str
) -> None:
    """001/R2.2 (a URL de migração é obrigatória em dev por causa de 001/R1.2; as chaves JWT,
    pela 002/R3.1)"""
    ambiente({nome: valor for nome, valor in VARIAVEIS_DEV.items() if nome != variavel})

    with pytest.raises(SettingsError, match=variavel):
        load_settings()


@pytest.mark.parametrize(
    ("variavel", "valor"),
    [
        ("APP_ENV", "homologacao"),
        ("DEBUG", "talvez"),
        ("DATABASE_URL", "mysql://sgs_api:sgs_api@db:3306/sgs"),
        ("DATABASE_URL", "postgresql+asyncpg://sgs_api:sgs_api@db:5432/sgs?ssl=disable"),
        ("DATABASE_MIGRATION_URL", "postgresql+asyncpg://sgs:sgs@db:5432"),
        ("DATABASE_SSL_MODE", "prefer"),
        ("DATABASE_POOL_SIZE", "0"),
        ("CORS_ORIGINS", "*"),
        ("CORS_ORIGINS", "https://localhost:3000/caminho"),
    ],
)
def test_recusa_iniciar_com_variavel_invalida_e_nomeia_a_variavel(
    ambiente: DefinirAmbiente, variavel: str, valor: str
) -> None:
    """001/R2.2"""
    ambiente({**VARIAVEIS_DEV, variavel: valor})

    with pytest.raises(SettingsError, match=variavel):
        load_settings()


def _pem_publico() -> str:
    chave = load_pem_private_key(make_pem_privado().encode(), password=None)
    return chave.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


CHAVES_JWT_INVALIDAS = {
    "fora_de_json": "kid=1;pem=nao-e-json",
    "lista_vazia": "[]",
    "objeto_em_vez_de_lista": json.dumps({"kid": "1", "pem": make_pem_privado()}),
    "sem_pem": json.dumps([{"kid": "1"}]),
    "sem_kid": json.dumps([{"pem": make_pem_privado()}]),
    "kid_vazio": json.dumps([{"kid": "", "pem": make_pem_privado()}]),
    "kid_com_espaco": json.dumps([{"kid": "chave 1", "pem": make_pem_privado()}]),
    "pem_ilegivel": json.dumps([{"kid": "1", "pem": "nao-e-um-pem"}]),
    "chave_publica": json.dumps([{"kid": "1", "pem": _pem_publico()}]),
    "curva_p384": json.dumps([{"kid": "1", "pem": make_pem_privado(ec.SECP384R1())}]),
    "kid_repetido": json.dumps(
        [{"kid": "1", "pem": make_pem_privado()}, {"kid": "1", "pem": make_pem_privado()}]
    ),
}


@pytest.mark.parametrize("valor", CHAVES_JWT_INVALIDAS.values(), ids=CHAVES_JWT_INVALIDAS.keys())
def test_recusa_iniciar_com_chaves_jwt_invalidas_e_nomeia_a_variavel(
    ambiente: DefinirAmbiente, valor: str
) -> None:
    """001/R2.2; 002/R3.1 (só chave privada EC P-256 assina em ES256, com `kid` único)"""
    ambiente({**VARIAVEIS_DEV, "JWT_PRIVATE_KEYS": valor})

    with pytest.raises(SettingsError, match="JWT_PRIVATE_KEYS") as erro:
        load_settings()

    assert "PRIVATE KEY" not in str(erro.value)


def test_le_as_chaves_jwt_na_ordem_e_a_primeira_assina(ambiente: DefinirAmbiente) -> None:
    """002/R3.1 (design, § Chaves JWT: a chave ativa assina, as demais seguem no JWKS)"""
    ambiente({**VARIAVEIS_DEV, "JWT_PRIVATE_KEYS": make_jwt_private_keys("2026-11", "2026-05")})

    settings = load_settings()

    assert [chave.kid for chave in settings.jwt_signing_keys] == ["2026-11", "2026-05"]


def _sem_jwt_private_keys(variaveis: dict[str, str]) -> dict[str, str]:
    return {nome: valor for nome, valor in variaveis.items() if nome != "JWT_PRIVATE_KEYS"}


def test_le_as_chaves_jwt_de_arquivo_montado(ambiente: DefinirAmbiente, tmp_path: Path) -> None:
    """001/R2.1; design da 002, § Chaves JWT (variável de ambiente ou arquivo montado)"""
    arquivo = tmp_path / "jwt-keys.json"
    arquivo.write_text(make_jwt_private_keys("2026-11"), encoding="utf-8")
    ambiente({**_sem_jwt_private_keys(VARIAVEIS_DEV), "JWT_PRIVATE_KEYS_FILE": str(arquivo)})

    settings = load_settings()

    assert [chave.kid for chave in settings.jwt_signing_keys] == ["2026-11"]


@pytest.mark.parametrize("conteudo", [None, "[]", json.dumps([{"kid": "1", "pem": "nao-e-pem"}])])
def test_recusa_iniciar_com_arquivo_de_chaves_jwt_ausente_ou_invalido(
    ambiente: DefinirAmbiente, tmp_path: Path, conteudo: str | None
) -> None:
    """001/R2.2"""
    arquivo = tmp_path / "jwt-keys.json"
    if conteudo is not None:
        arquivo.write_text(conteudo, encoding="utf-8")
    ambiente({**_sem_jwt_private_keys(VARIAVEIS_DEV), "JWT_PRIVATE_KEYS_FILE": str(arquivo)})

    with pytest.raises(SettingsError, match="JWT_PRIVATE_KEYS_FILE"):
        load_settings()


def test_recusa_iniciar_com_chaves_jwt_na_variavel_e_no_arquivo(
    ambiente: DefinirAmbiente, tmp_path: Path
) -> None:
    """001/R2.2 (duas fontes para a mesma chave deixariam dúvida sobre qual assina)"""
    arquivo = tmp_path / "jwt-keys.json"
    arquivo.write_text(make_jwt_private_keys("arquivo"), encoding="utf-8")
    ambiente({**VARIAVEIS_DEV, "JWT_PRIVATE_KEYS_FILE": str(arquivo)})

    with pytest.raises(SettingsError, match="JWT_PRIVATE_KEYS_FILE"):
        load_settings()


def test_chave_gerada_pela_ferramenta_e_aceita_em_prod(
    ambiente: DefinirAmbiente, capsys: pytest.CaptureFixture[str]
) -> None:
    """002/R3.1 (`python -m src.tools.jwt_keys` gera JWT_PRIVATE_KEYS no formato esperado)"""
    jwt_keys.main(["--kid", "2026-11"])
    ambiente({**VARIAVEIS_PROD, "JWT_PRIVATE_KEYS": capsys.readouterr().out})

    assert [chave.kid for chave in load_settings().jwt_signing_keys] == ["2026-11"]


def test_ferramenta_grava_arquivo_de_chaves_jwt_para_montar(
    ambiente: DefinirAmbiente, tmp_path: Path
) -> None:
    """002/R3.1 (arquivo para JWT_PRIVATE_KEYS_FILE, sem depender da codificação do shell)"""
    arquivo = tmp_path / "jwt-keys.json"
    jwt_keys.main(["--kid", "dev", "--output", str(arquivo)])
    ambiente({**_sem_jwt_private_keys(VARIAVEIS_DEV), "JWT_PRIVATE_KEYS_FILE": str(arquivo)})

    assert [chave.kid for chave in load_settings().jwt_signing_keys] == ["dev"]


def test_prod_com_configuracao_segura_inicia(ambiente: DefinirAmbiente) -> None:
    """001/R2.3"""
    ambiente(VARIAVEIS_PROD)

    assert load_settings().app_env is AppEnv.PROD


@pytest.mark.parametrize(
    ("variavel", "valor"),
    [
        ("DEBUG", "true"),
        ("DATABASE_SSL_MODE", "disable"),
        ("DATABASE_SSL_MODE", "require"),
        ("DATABASE_URL", "postgresql+asyncpg://sgs_api:sgs_api@db.interno:5432/sgs"),
        ("DATABASE_URL", "postgresql+asyncpg://app:troque-por-uma-senha@db.interno:5432/sgs"),
        ("DATABASE_MIGRATION_URL", "postgresql+asyncpg://sgs:sgs@db.interno:5432/sgs"),
    ],
)
def test_prod_recusa_iniciar_com_debug_sem_tls_ou_segredo_de_exemplo(
    ambiente: DefinirAmbiente, variavel: str, valor: str
) -> None:
    """001/R2.3"""
    ambiente({**VARIAVEIS_PROD, variavel: valor})

    with pytest.raises(SettingsError, match=variavel):
        load_settings()


@pytest.mark.parametrize(
    "kids", [("exemplo",), ("2026-11", "troque-esta-chave")], ids=["ativa", "antiga"]
)
def test_prod_recusa_iniciar_com_chave_jwt_de_exemplo(
    ambiente: DefinirAmbiente, kids: tuple[str, ...]
) -> None:
    """001/R2.3 (a chave de exemplo se reconhece pelo `kid`, como as senhas de exemplo)"""
    ambiente({**VARIAVEIS_PROD, "JWT_PRIVATE_KEYS": make_jwt_private_keys(*kids)})

    with pytest.raises(SettingsError, match="JWT_PRIVATE_KEYS: chave de exemplo"):
        load_settings()


def test_prod_recusa_chave_jwt_de_exemplo_vinda_de_arquivo(
    ambiente: DefinirAmbiente, tmp_path: Path
) -> None:
    """001/R2.3"""
    arquivo = tmp_path / "jwt-keys.json"
    arquivo.write_text(make_jwt_private_keys("chave-de-exemplo"), encoding="utf-8")
    ambiente({**_sem_jwt_private_keys(VARIAVEIS_PROD), "JWT_PRIVATE_KEYS_FILE": str(arquivo)})

    with pytest.raises(SettingsError, match="JWT_PRIVATE_KEYS_FILE"):
        load_settings()


def test_chave_jwt_de_exemplo_vale_fora_de_prod(ambiente: DefinirAmbiente) -> None:
    """001/R2.3 (a recusa de segredo de exemplo vale só em prod)"""
    ambiente({**VARIAVEIS_DEV, "JWT_PRIVATE_KEYS": make_jwt_private_keys("exemplo")})

    assert [chave.kid for chave in load_settings().jwt_signing_keys] == ["exemplo"]


def test_erro_de_configuracao_nao_expoe_o_valor_recebido(ambiente: DefinirAmbiente) -> None:
    """001/R2.2"""
    senha = "troque-esta-senha-secreta"
    ambiente({**VARIAVEIS_PROD, "DATABASE_URL": f"postgresql+asyncpg://app:{senha}@db/sgs"})

    with pytest.raises(SettingsError) as erro:
        load_settings()

    assert senha not in str(erro.value)
    assert erro.value.__cause__ is None
    assert erro.value.__suppress_context__
