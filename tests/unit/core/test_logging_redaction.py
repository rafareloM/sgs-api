"""Filtro de dados sensíveis nos logs (spec 001, R4.3)."""

import json
import logging

import pytest

from src.core.logging import REDACTED, configure_logging, redact_sensitive


@pytest.mark.parametrize(
    "chave",
    [
        "password",
        "senha",
        "nova_senha",
        "access_token",
        "refresh_token",
        "mfa_token",
        "cookie",
        "Set-Cookie",
        "Authorization",
        "client_secret",
        "segredo_totp",
        "otp",
        "code",
        "codigo",
    ],
)
def test_mascara_chaves_sensiveis(chave: str) -> None:
    """001/R4.3"""
    evento = redact_sensitive(None, "info", {"event": "login", chave: "valor-secreto"})

    assert evento[chave] == REDACTED


def test_mascara_chaves_sensiveis_em_estruturas_aninhadas() -> None:
    """001/R4.3"""
    evento = redact_sensitive(
        None,
        "info",
        {"event": "x", "headers": {"Authorization": "Bearer abc"}, "itens": [{"senha": "123"}]},
    )

    assert evento["headers"] == {"Authorization": REDACTED}
    assert evento["itens"] == [{"senha": REDACTED}]


def test_mascara_tokens_dentro_de_textos() -> None:
    """001/R4.3"""
    jwt = "eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiIxIn0.assinatura-do-token"
    evento = redact_sensitive(
        None, "error", {"event": f"falha com Bearer abc.def e token {jwt}", "detalhe": [jwt]}
    )

    texto = json.dumps(evento)
    assert "abc.def" not in texto
    assert jwt not in texto


def test_preserva_campos_que_nao_sao_sensiveis() -> None:
    """001/R4.3"""
    original = {"event": "requisicao", "method": "GET", "route": "/health/live", "status": 200}

    assert redact_sensitive(None, "info", dict(original)) == original


def test_log_de_acesso_do_uvicorn_fica_desligado() -> None:
    """001/R4.3 (o log de acesso do uvicorn traz a query string; o da API não traz)"""
    configure_logging("INFO")

    assert not logging.getLogger("uvicorn.access").hasHandlers()


def test_logs_de_bibliotecas_tambem_saem_em_json_e_filtrados(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """001/R4.1, 001/R4.3"""
    configure_logging("INFO")

    logging.getLogger("uvicorn.error").warning("falha ao autenticar", extra={"password": "123"})

    linha = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert linha["event"] == "falha ao autenticar"
    assert linha["level"] == "warning"
    assert linha["password"] == REDACTED
