"""As rotas da Etapa 03 são JSON e estão no contrato da API."""

from src.main import create_app
from tests.factories import make_settings


def test_openapi_expoe_crud_etapa3_e_dashboard() -> None:
    contrato = create_app(make_settings()).openapi()

    assert "post" in contrato["paths"]["/api/v1/unidades"]
    assert "patch" in contrato["paths"]["/api/v1/unidades/{unidade_id}"]
    assert "post" in contrato["paths"]["/api/v1/unidades/{unidade_id}/equipamentos"]
    assert "get" in contrato["paths"]["/api/v1/unidades/{unidade_id}/equipamentos"]
    assert "get" in contrato["paths"]["/api/v1/equipamentos"]
    assert "post" in contrato["paths"]["/api/v1/equipamentos"]
    assert "get" in contrato["paths"]["/api/v1/equipamentos/{equipamento_id}"]
    assert "patch" in contrato["paths"]["/api/v1/equipamentos/{equipamento_id}"]
    assert "delete" in contrato["paths"]["/api/v1/equipamentos/{equipamento_id}"]
    assert "get" in contrato["paths"]["/api/v1/dashboard/resumo"]
