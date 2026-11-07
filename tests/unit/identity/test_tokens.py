"""TokenService ES256 e JWKS (spec 002, T4; design, § Chaves JWT e § Estratégia de testes)."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.core.ids import uuid7
from src.main import create_app
from src.modules.identity.domain.tokens import (
    AccessTokenClaims,
    InvalidTokenError,
    MfaPurpose,
    MfaTokenClaims,
)
from src.modules.identity.infrastructure.tokens import JwtTokenService, SigningKey
from tests.factories import make_auth_session, make_jwt_private_keys, make_settings

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _chave(kid: str = "2026-11") -> SigningKey:
    return SigningKey(kid=kid, private_key=ec.generate_private_key(ec.SECP256R1()))


def _servico(*chaves: SigningKey, agora: datetime | None = None) -> JwtTokenService:
    instante = agora or datetime.now(UTC)
    return JwtTokenService(chaves or (_chave(),), clock=lambda: instante)


def _claims_sem_verificar(token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(token, options={"verify_signature": False})
    return claims


def test_access_token_e_es256_com_kid_e_as_claims_da_r3_1() -> None:
    """002/R3.1"""
    sessao = make_auth_session(amr="pwd+otp")
    servico = _servico(_chave("2026-11"), agora=AGORA)

    emitido = servico.issue_access_token(sessao)

    assert jwt.get_unverified_header(emitido.token) == {
        "alg": "ES256",
        "kid": "2026-11",
        "typ": "JWT",
    }
    claims = _claims_sem_verificar(emitido.token)
    assert claims == {
        "iss": "sgs-api",
        "aud": "sgs-api",
        "sub": str(sessao.user_id),
        "sid": str(sessao.id),
        "amr": ["pwd", "otp"],
        "iat": int(AGORA.timestamp()),
        "exp": int((AGORA + timedelta(minutes=15)).timestamp()),
    }
    assert emitido.expires_in == 900


def test_access_token_valido_devolve_usuario_e_sessao() -> None:
    """002/R3.1 (é o que o CurrentUser da 003/T4 recebe para carregar a sessão)"""
    chave = _chave()
    sessao = make_auth_session(amr="ldap+otp")
    token = _servico(chave).issue_access_token(sessao).token

    claims = _servico(chave).verify_access_token(token)

    assert claims == AccessTokenClaims(
        user_id=sessao.user_id, session_id=sessao.id, amr=("ldap", "otp")
    )


@pytest.mark.parametrize(
    ("idade", "valido"),
    [(timedelta(minutes=14, seconds=50), True), (timedelta(minutes=15, seconds=10), False)],
    ids=["dentro_dos_15_minutos", "vencido"],
)
def test_access_token_vale_15_minutos(idade: timedelta, valido: bool) -> None:
    """002/R3.1, 002/R3.8"""
    chave = _chave()
    token = _servico(chave, agora=datetime.now(UTC) - idade).issue_access_token(make_auth_session())

    if valido:
        _servico(chave).verify_access_token(token.token)
    else:
        with pytest.raises(InvalidTokenError):
            _servico(chave).verify_access_token(token.token)


def _claims_validas(**alteracoes: Any) -> dict[str, Any]:
    """Claims de um access token válido agora; `None` numa alteração remove a claim."""
    sessao = make_auth_session()
    agora = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {
        "iss": "sgs-api",
        "aud": "sgs-api",
        "sub": str(sessao.user_id),
        "sid": str(sessao.id),
        "amr": ["pwd", "otp"],
        "iat": agora,
        "exp": agora + 15 * 60,
    }
    claims.update(alteracoes)
    return {nome: valor for nome, valor in claims.items() if valor is not None}


def _assinado(chave: SigningKey, claims: dict[str, Any], **cabecalho: Any) -> str:
    return jwt.encode(
        claims, chave.private_key, algorithm="ES256", headers={"kid": chave.kid, **cabecalho}
    )


def _b64url(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def _hs256_com_a_chave_publica(chave: SigningKey) -> str:
    """Confusão de algoritmo: HMAC usando como segredo a chave pública, que é publicada."""
    publica = chave.private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    cabecalho = _b64url(json.dumps({"alg": "HS256", "kid": chave.kid, "typ": "JWT"}).encode())
    corpo = _b64url(json.dumps(_claims_validas(iat=None, exp=None)).encode())
    assinatura = hmac.new(publica, f"{cabecalho}.{corpo}".encode(), hashlib.sha256).digest()
    return f"{cabecalho}.{corpo}.{_b64url(assinatura)}"


def _com_corpo_trocado(token: str) -> str:
    cabecalho, _, assinatura = token.split(".")
    corpo = _b64url(json.dumps(_claims_validas()).encode())
    return f"{cabecalho}.{corpo}.{assinatura}"


CHAVE = _chave("2026-11")
OUTRA_CHAVE_MESMO_KID = _chave("2026-11")

TOKENS_INVALIDOS = {
    "aud_errado": lambda: _assinado(CHAVE, _claims_validas(aud="outra-api")),
    "aud_do_mfa_token": lambda: _assinado(CHAVE, _claims_validas(aud="sgs-mfa")),
    "iss_errado": lambda: _assinado(CHAVE, _claims_validas(iss="https://outro-emissor")),
    "sem_sid": lambda: _assinado(CHAVE, _claims_validas(sid=None)),
    "sem_exp": lambda: _assinado(CHAVE, _claims_validas(exp=None)),
    "sub_que_nao_e_uuid": lambda: _assinado(CHAVE, _claims_validas(sub="maria.silva")),
    "amr_em_texto": lambda: _assinado(CHAVE, _claims_validas(amr="pwd+otp")),
    "assinado_por_outra_chave": lambda: _assinado(OUTRA_CHAVE_MESMO_KID, _claims_validas()),
    "corpo_trocado": lambda: _com_corpo_trocado(_assinado(CHAVE, _claims_validas())),
    "kid_desconhecido": lambda: _assinado(CHAVE, _claims_validas(), kid="2025-01"),
    "chave_e_kid_desconhecidos": lambda: _assinado(_chave("2025-01"), _claims_validas()),
    "sem_kid": lambda: jwt.encode(_claims_validas(), CHAVE.private_key, algorithm="ES256"),
    "alg_none": lambda: jwt.encode(
        _claims_validas(), "", algorithm="none", headers={"kid": CHAVE.kid}
    ),
    "hs256_com_a_chave_publica": lambda: _hs256_com_a_chave_publica(CHAVE),
    "vazio": lambda: "",
    "fora_do_formato": lambda: "nao.e.jwt",
}


@pytest.mark.parametrize("token", TOKENS_INVALIDOS.values(), ids=TOKENS_INVALIDOS.keys())
def test_recusa_access_token_invalido(token: Any) -> None:
    """002/R3.8 (design, § Estratégia de testes: `aud` e `kid` desconhecido)"""
    with pytest.raises(InvalidTokenError) as erro:
        _servico(CHAVE).verify_access_token(token())

    assert erro.value.status == 401
    assert erro.value.detail == "Token inválido ou expirado."
    assert erro.value.__cause__ is None


@pytest.mark.parametrize(
    "chaves", [(), (_chave("2026-11"), _chave("2026-11"))], ids=["sem_chave", "kid_repetido"]
)
def test_servico_exige_chave_e_kid_unico(chaves: tuple[SigningKey, ...]) -> None:
    """002/R3.1 (sem chave não há o que assinar; `kid` repetido tornaria a validação ambígua)"""
    with pytest.raises(ValueError, match="chave"):
        JwtTokenService(chaves)


def test_rotacao_assina_com_a_chave_ativa_e_aceita_token_da_antiga() -> None:
    """002/R3.2 (design, § Chaves JWT: rotação sem derrubar sessões)"""
    antiga, nova = _chave("2026-05"), _chave("2026-11")
    sessao = make_auth_session()
    token_antigo = _servico(antiga).issue_access_token(sessao).token
    depois_da_rotacao = _servico(nova, antiga)

    token_novo = depois_da_rotacao.issue_access_token(sessao).token

    assert jwt.get_unverified_header(token_novo)["kid"] == "2026-11"
    assert depois_da_rotacao.verify_access_token(token_antigo).session_id == sessao.id
    assert depois_da_rotacao.verify_access_token(token_novo).session_id == sessao.id


def test_jwks_publica_as_chaves_publicas_de_todas_as_chaves() -> None:
    """002/R3.2"""
    antiga, nova = _chave("2026-05"), _chave("2026-11")
    servico = _servico(nova, antiga)
    tokens = {
        chave.kid: _servico(chave).issue_access_token(make_auth_session()).token
        for chave in (antiga, nova)
    }

    jwks = servico.public_keys()

    assert [jwk.kid for jwk in jwks] == ["2026-11", "2026-05"]
    for jwk in jwks:
        assert (jwk.kty, jwk.crv, jwk.alg, jwk.use) == ("EC", "P-256", "ES256", "sig")
        # Quem só tem o JWKS confere a assinatura (a chave privada `d` não é publicada).
        publica = jwt.PyJWK({"kty": jwk.kty, "crv": jwk.crv, "x": jwk.x, "y": jwk.y})
        jwt.decode(tokens[jwk.kid], publica, algorithms=["ES256"], audience="sgs-api")


def test_mfa_token_vale_5_minutos_com_purpose_e_jti() -> None:
    """002/R1.1, 002/R1.2 (design, § Chaves JWT: `aud = sgs-mfa`, `purpose` e `jti`)"""
    usuario = uuid7()

    emitido = _servico(agora=AGORA).issue_mfa_token(usuario, MfaPurpose.ENROLL)

    assert emitido.purpose is MfaPurpose.ENROLL
    assert _claims_sem_verificar(emitido.token) == {
        "iss": "sgs-api",
        "aud": "sgs-mfa",
        "sub": str(usuario),
        "purpose": "enroll",
        "jti": str(emitido.jti),
        "iat": int(AGORA.timestamp()),
        "exp": int((AGORA + timedelta(minutes=5)).timestamp()),
    }


def test_cada_mfa_token_tem_jti_proprio_e_valida_para_a_sua_finalidade() -> None:
    """002/R1.1 (o `jti` identifica o desafio cujas tentativas a R2.6 conta)"""
    chave, usuario = _chave(), uuid7()
    primeiro = _servico(chave).issue_mfa_token(usuario, MfaPurpose.VERIFY)
    segundo = _servico(chave).issue_mfa_token(usuario, MfaPurpose.VERIFY)

    claims = _servico(chave).verify_mfa_token(segundo.token, MfaPurpose.VERIFY)

    assert claims == MfaTokenClaims(user_id=usuario, jti=segundo.jti, purpose=MfaPurpose.VERIFY)
    assert primeiro.jti != segundo.jti


def test_mfa_token_de_outra_finalidade_e_recusado() -> None:
    """002/R1.2 (o token de cadastro só cadastra o 2FA)"""
    chave = _chave()
    cadastro = _servico(chave).issue_mfa_token(uuid7(), MfaPurpose.ENROLL)

    with pytest.raises(InvalidTokenError):
        _servico(chave).verify_mfa_token(cadastro.token, MfaPurpose.VERIFY)


def test_mfa_token_vencido_e_recusado() -> None:
    """002/R1.1 (válido por 5 minutos)"""
    chave = _chave()
    antigo = _servico(chave, agora=datetime.now(UTC) - timedelta(minutes=5, seconds=10))
    token = antigo.issue_mfa_token(uuid7(), MfaPurpose.VERIFY).token

    with pytest.raises(InvalidTokenError):
        _servico(chave).verify_mfa_token(token, MfaPurpose.VERIFY)


def test_mfa_token_e_access_token_nao_se_confundem() -> None:
    """002/R1.1 (o `mfa_token` não é token de acesso), 002/R3.8 (`aud` errado)"""
    chave = _chave()
    servico = _servico(chave)
    mfa = servico.issue_mfa_token(uuid7(), MfaPurpose.VERIFY).token
    acesso = servico.issue_access_token(make_auth_session()).token

    with pytest.raises(InvalidTokenError):
        servico.verify_access_token(mfa)
    with pytest.raises(InvalidTokenError):
        servico.verify_mfa_token(acesso, MfaPurpose.VERIFY)


async def test_rota_jwks_publica_as_chaves_sem_autenticacao() -> None:
    """002/R3.2 (rota pública: só traz chaves públicas)"""
    app = create_app(make_settings(jwt_private_keys=make_jwt_private_keys("2026-11", "2026-05")))
    token = app.state.token_service.issue_access_token(make_auth_session()).token
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.get("/.well-known/jwks.json")

    assert resposta.status_code == 200
    chaves = resposta.json()["keys"]
    assert [chave["kid"] for chave in chaves] == ["2026-11", "2026-05"]
    for chave in chaves:
        assert set(chave) == {"kty", "crv", "alg", "use", "kid", "x", "y"}  # sem o `d` privado
    publica = jwt.PyJWK(chaves[0])
    assert jwt.decode(token, publica, algorithms=["ES256"], audience="sgs-api")["iss"] == "sgs-api"
