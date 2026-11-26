"""Rota pública das chaves de verificação dos relatórios (005/T9; design § Rotas e § Assinatura)."""

import base64
import hashlib

import httpx
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import FastAPI

from src.main import create_app
from tests.factories import make_jwt_private_keys, make_settings

ROTA = "/.well-known/relatorios-jwks.json"
CONTEUDO = "cnes;nome\r\n1000001;USF Alto do Céu\r\n".encode()


async def _get(app: FastAPI, caminho: str) -> httpx.Response:
    """Sem `Authorization`: quem confere um relatório não tem conta na plataforma."""
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        return await cliente.get(caminho)


def _base64url(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


async def test_rota_publica_traz_a_chave_ativa_e_as_anteriores_sem_material_privado() -> None:
    """005/R5.4, 005/R5.5"""
    app = create_app(
        make_settings(report_signing_keys=make_jwt_private_keys("rel-2026-11", "rel-2026-05"))
    )
    assinatura = app.state.assinador_de_relatorio.assinar(hashlib.sha256(CONTEUDO).digest())

    resposta = await _get(app, ROTA)

    assert resposta.status_code == 200
    chaves = resposta.json()["keys"]
    assert [chave["kid"] for chave in chaves] == ["rel-2026-11", "rel-2026-05"]
    for chave in chaves:
        assert set(chave) == {"kty", "crv", "alg", "use", "kid", "x", "y"}  # sem o `d` privado
        assert (chave["kty"], chave["crv"], chave["alg"], chave["use"]) == (
            "EC",
            "P-256",
            "ES256",
            "sig",
        )
    assert "PRIVATE" not in resposta.text
    # Uma biblioteca de JWK qualquer (aqui, a do PyJWT) lê a chave publicada e confere o arquivo.
    publica = jwt.PyJWK(chaves[0]).key
    assert isinstance(publica, ec.EllipticCurvePublicKey)
    r_s = _base64url(assinatura.valor)
    der = encode_dss_signature(int.from_bytes(r_s[:32]), int.from_bytes(r_s[32:]))
    publica.verify(der, CONTEUDO, ec.ECDSA(hashes.SHA256()))


async def test_chaves_dos_relatorios_nao_sao_as_dos_tokens() -> None:
    """005/R5.2 (as duas rotas publicam chaves diferentes)"""
    app = create_app(make_settings(report_signing_keys=make_jwt_private_keys("rel-2026-11")))

    relatorios = (await _get(app, ROTA)).json()["keys"]
    tokens = (await _get(app, "/.well-known/jwks.json")).json()["keys"]

    assert relatorios
    assert tokens
    assert {c["kid"] for c in relatorios}.isdisjoint({c["kid"] for c in tokens})
    assert {(c["x"], c["y"]) for c in relatorios}.isdisjoint({(c["x"], c["y"]) for c in tokens})


async def test_sem_chave_configurada_a_rota_publica_lista_vazia() -> None:
    """005/R5.4 (sem REPORT_SIGNING_KEYS nada é assinado, e não há chave a publicar)"""
    resposta = await _get(create_app(make_settings()), ROTA)

    assert resposta.status_code == 200
    assert resposta.json() == {"keys": []}
