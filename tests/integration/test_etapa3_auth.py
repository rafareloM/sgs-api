"""O identificador temporário de usuário nunca autentica requests em produção."""

from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.core.config import AppEnv, DatabaseSslMode
from src.main import create_app
from tests.factories import make_settings


def test_producao_recusa_x_user_id_como_autenticacao() -> None:
    app = create_app(
        make_settings(
            app_env=AppEnv.PROD,
            database_ssl_mode=DatabaseSslMode.VERIFY_FULL,
            database_url=SecretStr(
                "postgresql+asyncpg://app:prod-secret-864abcb@db.interno:5432/sgs"
            ),
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/dashboard/resumo",
            headers={"X-User-Id": "1"},
        )

    assert response.status_code == 401
