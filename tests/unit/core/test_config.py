"""Configuração por ambiente (spec 001, R2)."""

from collections.abc import Callable

import pytest

from sgs_api.core.config import AppEnv, Settings, SettingsError, load_settings

type DefinirAmbiente = Callable[[dict[str, str]], None]

VARIAVEIS_DEV = {
    "APP_ENV": "dev",
    "DATABASE_URL": "postgresql+asyncpg://sgs_api:sgs_api@db:5432/sgs",
    "DATABASE_MIGRATION_URL": "postgresql+asyncpg://sgs:sgs@db:5432/sgs",
    "DATABASE_SSL_MODE": "disable",
}

VARIAVEIS_PROD = {
    "APP_ENV": "prod",
    "DATABASE_URL": "postgresql+asyncpg://sgs_api:Kx9-segredo-de-verdade@db.interno:5432/sgs",
    "DATABASE_SSL_MODE": "verify-full",
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


@pytest.mark.parametrize("variavel", ["APP_ENV", "DATABASE_URL", "DATABASE_MIGRATION_URL"])
def test_recusa_iniciar_sem_variavel_obrigatoria_e_nomeia_a_variavel(
    ambiente: DefinirAmbiente, variavel: str
) -> None:
    """001/R2.2 (a URL de migração é obrigatória em dev por causa de 001/R1.2)"""
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


def test_erro_de_configuracao_nao_expoe_o_valor_recebido(ambiente: DefinirAmbiente) -> None:
    """001/R2.2"""
    senha = "troque-esta-senha-secreta"
    ambiente({**VARIAVEIS_PROD, "DATABASE_URL": f"postgresql+asyncpg://app:{senha}@db/sgs"})

    with pytest.raises(SettingsError) as erro:
        load_settings()

    assert senha not in str(erro.value)
    assert erro.value.__cause__ is None
    assert erro.value.__suppress_context__
