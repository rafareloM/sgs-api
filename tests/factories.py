"""Fábricas de objetos usados nos testes (steering/testing.md: funções make_*)."""

from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from sgs_api.core.config import AppEnv, DatabaseSslMode, Settings

# Banco fictício: os testes que precisam de banco de verdade usam tests/integration/conftest.py.
URL_SEM_BANCO = "postgresql+asyncpg://sgs_api:sgs_api@127.0.0.1:1/sgs"


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


def make_settings(**overrides: Any) -> Settings:
    valores: dict[str, Any] = {
        "app_env": AppEnv.TEST,
        "database_url": SecretStr(URL_SEM_BANCO),
        "database_ssl_mode": DatabaseSslMode.DISABLE,
    }
    return _SettingsSemAmbiente(**(valores | overrides))
