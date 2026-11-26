"""Adaptador OIDC: URL de autorização, troca do código e validação do `id_token` (spec 004, T6;
design § Portas e adaptadores, `authlib_oidc.py`).

Sem rede: o provedor é falso, servido por `httpx.MockTransport`, e as chaves do JWKS e os
`id_token` são gerados no próprio teste.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from src.core.errors import ServiceUnavailable
from src.modules.identity.domain.oidc import OidcIdentity, OidcRejected
from src.modules.identity.infrastructure.authlib_oidc import AuthlibOidc
from tests.factories import make_settings

EMISSOR = "https://idp.teste/realms/sgs"
DESCOBERTA = "https://idp-interno.teste/realms/sgs/.well-known/openid-configuration"
AUTORIZACAO = "https://idp.teste/realms/sgs/protocol/openid-connect/auth"
TROCA = "https://idp-interno.teste/realms/sgs/protocol/openid-connect/token"
JWKS = "https://idp-interno.teste/realms/sgs/protocol/openid-connect/certs"
CLIENTE = "sgs-api"
SEGREDO = "segredo-do-cliente-de-teste"
RETORNO = "https://sgs.teste/api/v1/auth/oidc/callback"
NONCE = "nonce-do-pedido-de-login"
SUB = "6f1c2a9e-0d4b-4c55-9a3e-2f5b8c7d1e20"
AUSENTE = object()
JSON = {"Content-Type": "application/json"}


@cache
def _rsa() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@cache
def _ec() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@dataclass(frozen=True)
class Chave:
    """Chave de assinatura do provedor falso; o JWKS publica só a parte pública."""

    kid: str
    alg: str
    privada: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey = field(repr=False)

    def jwk(self) -> dict[str, Any]:
        publica = self.privada.public_key()
        if isinstance(publica, rsa.RSAPublicKey):
            dados = RSAAlgorithm.to_jwk(publica, as_dict=True)
        else:
            dados = ECAlgorithm.to_jwk(publica, as_dict=True)
        return dados | {"kid": self.kid, "alg": self.alg, "use": "sig"}

    def assinar(self, claims: dict[str, Any], *, kid: str | None = None) -> str:
        return jwt.encode(
            claims, self.privada, algorithm=self.alg, headers={"kid": kid or self.kid}
        )


def _chave_rsa(kid: str = "rsa-1", privada: rsa.RSAPrivateKey | None = None) -> Chave:
    return Chave(kid, "RS256", privada or _rsa())


def _chave_ec(kid: str = "ec-1") -> Chave:
    return Chave(kid, "ES256", _ec())


def _claims(**mudancas: object) -> dict[str, Any]:
    """Claims de um `id_token` válido; `AUSENTE` tira a claim."""
    agora = int(time.time())
    claims: dict[str, Any] = {
        "iss": EMISSOR,
        "aud": CLIENTE,
        "azp": CLIENTE,
        "sub": SUB,
        "iat": agora,
        "exp": agora + 300,
        "nonce": NONCE,
        "preferred_username": "Maria.Silva",
        "name": "Maria Silva",
        "email": "Maria.Silva@Example.org",
        "email_verified": True,
        "groups": ["/sgs/gestores", "/sgs/vigilancia"],
    }
    for nome, valor in mudancas.items():
        if valor is AUSENTE:
            claims.pop(nome, None)
        else:
            claims[nome] = valor
    return claims


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def _jwt_montado(cabecalho: dict[str, Any], claims: dict[str, Any], segredo: bytes | None) -> str:
    """JWT montado à mão, para os algoritmos que o PyJWT se recusa a produzir aqui."""
    entrada = f"{_b64(json.dumps(cabecalho).encode())}.{_b64(json.dumps(claims).encode())}"
    if segredo is None:
        return f"{entrada}."
    return f"{entrada}.{_b64(hmac.new(segredo, entrada.encode(), hashlib.sha256).digest())}"


class ProvedorFalso:
    """Provedor OIDC em memória: descoberta, JWKS e token endpoint."""

    def __init__(
        self, *chaves: Chave, emissor: str = EMISSOR, descoberta: str = DESCOBERTA
    ) -> None:
        self.chaves = list(chaves)
        self.jwks_extra: list[dict[str, Any]] = []  # entradas publicadas além das chaves
        self.emissor = emissor
        self.descoberta = descoberta
        self.id_token: str | None = None
        self.descoberta_extra: dict[str, Any] = {}  # campos trocados no documento de descoberta
        self.token_extra: dict[str, Any] = {}  # campos a mais na resposta do token endpoint
        self.resposta_do_token: Callable[[httpx.Request], httpx.Response] | None = None
        # Resposta trocada por endereço (descoberta, JWKS ou token endpoint).
        self.respostas: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.atraso_do_jwks = 0.0  # segundos até o JWKS responder
        self.pedidos: list[httpx.Request] = []

    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._responder_com_atraso)

    async def _responder_com_atraso(self, pedido: httpx.Request) -> httpx.Response:
        if self.atraso_do_jwks and str(pedido.url.copy_with(query=None)) == JWKS:
            await asyncio.sleep(self.atraso_do_jwks)
        return self._responder(pedido)

    def pedidos_a(self, endereco: str) -> list[httpx.Request]:
        return [p for p in self.pedidos if str(p.url.copy_with(query=None)) == endereco]

    def _responder(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        endereco = str(pedido.url.copy_with(query=None))
        if endereco in self.respostas:
            return self.respostas[endereco](pedido)
        if endereco == self.descoberta:
            return httpx.Response(
                200,
                json={
                    "issuer": self.emissor,
                    "authorization_endpoint": AUTORIZACAO,
                    "token_endpoint": TROCA,
                    "jwks_uri": JWKS,
                }
                | self.descoberta_extra,
            )
        if endereco == JWKS:
            chaves = [chave.jwk() for chave in self.chaves] + self.jwks_extra
            return httpx.Response(200, json={"keys": chaves})
        if endereco == TROCA and pedido.method == "POST":
            if self.resposta_do_token is not None:
                return self.resposta_do_token(pedido)
            corpo = {"access_token": "opaco", "token_type": "Bearer", "id_token": self.id_token}
            # `json.dumps` aceita NaN e infinito, como um provedor fora do padrão mandaria.
            conteudo = json.dumps(corpo | self.token_extra).encode()
            return httpx.Response(200, content=conteudo, headers=JSON)
        return httpx.Response(404)


class Relogio:
    """Relógio monotônico controlado pelo teste (recarga do JWKS no máximo uma vez por minuto)."""

    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


def _adaptador(
    provedor: ProvedorFalso, *, acr: tuple[str, ...] = (), relogio: Relogio | None = None
) -> AuthlibOidc:
    return AuthlibOidc(
        issuer=EMISSOR,
        discovery_url=DESCOBERTA,
        client_id=CLIENTE,
        client_secret=SEGREDO,
        redirect_uri=RETORNO,
        required_acr=acr,
        transport=provedor.transporte(),
        monotonic=relogio or Relogio(),
    )


async def _trocar(adaptador: AuthlibOidc, provedor: ProvedorFalso, id_token: str) -> OidcIdentity:
    provedor.id_token = id_token
    return await adaptador.exchange("codigo-do-provedor", code_verifier="v" * 64, nonce=NONCE)


async def _motivo_da_recusa(adaptador: AuthlibOidc, provedor: ProvedorFalso, id_token: str) -> str:
    with pytest.raises(OidcRejected) as recusa:
        await _trocar(adaptador, provedor, id_token)
    # Só o motivo, sem token, código ou segredo, e sem a exceção original encadeada.
    assert str(recusa.value) == recusa.value.motivo
    assert recusa.value.__cause__ is None
    return recusa.value.motivo


async def test_url_de_autorizacao_usa_pkce_s256_nonce_e_retorno_da_configuracao() -> None:
    """004/R3.1, R3.8 (Authorization Code com PKCE S256, `state` e `nonce`; `redirect_uri`
    só da configuração)"""
    provedor = ProvedorFalso(_chave_rsa())

    url = await _adaptador(provedor).authorization_url(
        state="estado-1", nonce=NONCE, code_challenge="desafio-s256"
    )

    partes = urlsplit(url)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == AUTORIZACAO
    assert parse_qs(partes.query) == {
        "response_type": ["code"],
        "client_id": [CLIENTE],
        "redirect_uri": [RETORNO],
        "scope": ["openid profile email"],
        "state": ["estado-1"],
        "nonce": [NONCE],
        "code_challenge": ["desafio-s256"],
        "code_challenge_method": ["S256"],
    }


async def test_url_de_autorizacao_pede_os_acr_exigidos() -> None:
    """004/R3.6 (OIDC_REQUIRED_ACR vai também em `acr_values` no pedido)"""
    provedor = ProvedorFalso(_chave_rsa())

    url = await _adaptador(provedor, acr=("mfa", "gold")).authorization_url(
        state="estado-1", nonce=NONCE, code_challenge="desafio-s256"
    )

    assert parse_qs(urlsplit(url).query)["acr_values"] == ["mfa gold"]


async def test_descoberta_de_outro_emissor_nao_usa_o_provedor() -> None:
    """004/R3.2 (o `issuer` da descoberta tem de ser igual a OIDC_ISSUER)"""
    provedor = ProvedorFalso(_chave_rsa(), emissor="https://idp.teste/realms/outro")
    adaptador = _adaptador(provedor)

    with pytest.raises(ServiceUnavailable):
        await adaptador.authorization_url(state="e", nonce=NONCE, code_challenge="d")
    assert await _motivo_da_recusa(adaptador, provedor, _chave_rsa().assinar(_claims())) == "troca"
    assert provedor.pedidos_a(TROCA) == []


@pytest.mark.parametrize("chave", [_chave_rsa(), _chave_ec()], ids=["RS256", "ES256"])
async def test_troca_o_codigo_e_devolve_a_identidade_do_id_token(chave: Chave) -> None:
    """004/R3.2 (troca com `client_secret_basic` e o `code_verifier`; `id_token` conferido)"""
    provedor = ProvedorFalso(_chave_rsa("outra"), chave)

    identidade = await _trocar(_adaptador(provedor), provedor, chave.assinar(_claims()))

    assert identidade == OidcIdentity(
        sub=SUB,
        username="maria.silva",
        email="maria.silva@example.org",
        display_name="Maria Silva",
        groups=("/sgs/gestores", "/sgs/vigilancia"),
        acr=None,
    )
    [pedido] = provedor.pedidos_a(TROCA)
    credencial = base64.b64encode(f"{CLIENTE}:{SEGREDO}".encode()).decode()
    assert pedido.headers["Authorization"] == f"Basic {credencial}"
    assert parse_qs(pedido.content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["codigo-do-provedor"],
        "code_verifier": ["v" * 64],
        "redirect_uri": [RETORNO],
    }


async def test_email_nao_verificado_fica_de_fora() -> None:
    """004/R3.2 (D004-12: e-mail do OIDC só com `email_verified = true`)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)

    identidade = await _trocar(
        _adaptador(provedor), provedor, chave.assinar(_claims(email_verified=False))
    )

    assert identidade.email is None


async def test_exp_vencido_dentro_da_tolerancia_de_60s_e_aceito() -> None:
    """004/R3.2 (`exp` e `iat` com tolerância de 60 s)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    agora = int(time.time())

    identidade = await _trocar(
        _adaptador(provedor), provedor, chave.assinar(_claims(iat=agora - 600, exp=agora - 30))
    )

    assert identidade.sub == SUB


def _id_token_invalido(caso: str) -> str:
    chave = _chave_rsa()
    agora = int(time.time())
    match caso:
        case "outra_chave_com_o_mesmo_kid":
            return Chave(chave.kid, "RS256", rsa.generate_private_key(65537, 2048)).assinar(
                _claims()
            )
        case "alg_do_cabecalho_diferente_da_chave":
            return chave.assinar(_claims(), kid=_chave_ec().kid)
        case "kid_desconhecido":
            return chave.assinar(_claims(), kid="sem-chave")
        case "malformado":
            return "nao.e.um-jwt"
        case "outro_emissor":
            return chave.assinar(_claims(iss="https://idp.teste/realms/outro"))
        case "outra_audiencia":
            return chave.assinar(_claims(aud="outro-cliente", azp="outro-cliente"))
        case "varias_audiencias_sem_azp":
            return chave.assinar(_claims(aud=[CLIENTE, "outro-cliente"], azp=AUSENTE))
        case "azp_de_outro_cliente":
            return chave.assinar(_claims(aud=[CLIENTE, "outro-cliente"], azp="outro-cliente"))
        case "vencido":
            return chave.assinar(_claims(iat=agora - 600, exp=agora - 120))
        case "emitido_no_futuro":
            return chave.assinar(_claims(iat=agora + 600, exp=agora + 900))
        case "outro_nonce":
            return chave.assinar(_claims(nonce="nonce-de-outro-pedido"))
        case _:
            claim = caso.removeprefix("sem_")
            return chave.assinar(_claims(**{claim: AUSENTE}))


CASOS_INVALIDOS = {
    "outra_chave_com_o_mesmo_kid": "assinatura",
    "alg_do_cabecalho_diferente_da_chave": "assinatura",
    "kid_desconhecido": "assinatura",
    "malformado": "assinatura",
    "outro_emissor": "iss",
    "sem_iss": "iss",
    "outra_audiencia": "aud",
    "sem_aud": "aud",
    "varias_audiencias_sem_azp": "aud",
    "azp_de_outro_cliente": "aud",
    "vencido": "exp",
    "sem_exp": "exp",
    "emitido_no_futuro": "exp",
    "sem_iat": "exp",
    "outro_nonce": "nonce",
    "sem_nonce": "nonce",
    "sem_sub": "claims",
    "sem_preferred_username": "claims",
}


@pytest.mark.parametrize(("caso", "motivo"), CASOS_INVALIDOS.items(), ids=CASOS_INVALIDOS.keys())
async def test_id_token_invalido_e_recusado_com_o_motivo(caso: str, motivo: str) -> None:
    """004/R3.2 (assinatura, `iss`, `aud`/`azp`, `exp`/`iat` e `nonce`, com motivo de lista
    fechada para a auditoria)"""
    provedor = ProvedorFalso(_chave_rsa(), _chave_ec())

    assert await _motivo_da_recusa(_adaptador(provedor), provedor, _id_token_invalido(caso)) == (
        motivo
    )


@pytest.mark.parametrize(
    "mudancas",
    [
        {"preferred_username": "m" * 101},
        {"preferred_username": "   "},
        {"preferred_username": 42},
        {"groups": "/sgs/gestores"},
        {"groups": ["/sgs/gestores", 7]},
    ],
    ids=["username_longo", "username_vazio", "username_nao_texto", "grupos_texto", "grupo_numero"],
)
async def test_claims_fora_do_formato_sao_recusadas(mudancas: dict[str, object]) -> None:
    """004/R3.2 (motivo `claims`: `preferred_username` ausente ou longo demais e claim de grupos
    que não é lista de textos; design § Fluxo, Login OIDC, passo 3)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)

    assert (
        await _motivo_da_recusa(_adaptador(provedor), provedor, chave.assinar(_claims(**mudancas)))
        == "claims"
    )


@pytest.mark.parametrize(
    "grupos",
    [[""], ["/sgs/gestores", "   "], ["g" * 256]],
    ids=["grupo_vazio", "grupo_so_com_espacos", "grupo_com_256_caracteres"],
)
async def test_grupo_vazio_ou_longo_demais_e_recusado(grupos: list[str]) -> None:
    """004/R3.2, R3.3 (motivo `claims`: cada grupo vira `external_id` e nome do grupo espelhado,
    com até 255 caracteres; design § Fluxo, Login OIDC, passo 4)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)

    assert (
        await _motivo_da_recusa(
            _adaptador(provedor), provedor, chave.assinar(_claims(groups=grupos))
        )
        == "claims"
    )


async def test_grupo_com_255_caracteres_e_aceito() -> None:
    """004/R3.3 (o limite do nome do grupo espelhado é 255 caracteres)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)

    identidade = await _trocar(
        _adaptador(provedor), provedor, chave.assinar(_claims(groups=["g" * 255]))
    )

    assert identidade.groups == ("g" * 255,)


@pytest.mark.parametrize(
    "email",
    ["m" * 243 + "@example.org", "maria.silva", "maria@localhost", "maria silva@example.org"],
    ids=["com_255_caracteres", "sem_arroba", "sem_dominio_de_topo", "com_espaco"],
)
async def test_email_que_a_conta_nao_aceita_fica_de_fora(email: str) -> None:
    """004/R3.2, R3.3 (e-mail verificado que `User` recusaria vira ausência de e-mail, sem
    recusar o login nem quebrar o provisionamento)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)

    identidade = await _trocar(_adaptador(provedor), provedor, chave.assinar(_claims(email=email)))

    assert identidade.email is None
    assert identidade.username == "maria.silva"


async def test_alg_none_e_hs256_sao_recusados_mesmo_com_kid_publicado() -> None:
    """004/R3.2 (algoritmos fixos RS256 e ES256: nunca `none` nem `HS*`, nem a confusão de
    algoritmo com a chave pública RSA usada como segredo HMAC)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    # Um JWKS que publica também uma chave simétrica não abre a porta para o HS256.
    provedor.jwks_extra = [{"kty": "oct", "kid": "hmac-1", "k": _b64(b"s" * 32), "alg": "HS256"}]
    adaptador = _adaptador(provedor)
    pem_publico = chave.privada.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )

    tokens = [
        _jwt_montado({"alg": "none", "typ": "JWT", "kid": chave.kid}, _claims(), None),
        _jwt_montado({"alg": "HS256", "typ": "JWT", "kid": chave.kid}, _claims(), pem_publico),
        _jwt_montado({"alg": "HS256", "typ": "JWT", "kid": "hmac-1"}, _claims(), b"s" * 32),
    ]
    for token in tokens:
        assert await _motivo_da_recusa(adaptador, provedor, token) == "assinatura"


async def test_kid_desconhecido_recarrega_o_jwks_no_maximo_uma_vez_por_minuto() -> None:
    """004/R3.2 (rotação de chave no provedor: um `kid` desconhecido recarrega o JWKS uma vez,
    no máximo uma vez por minuto)"""
    antiga, nova = _chave_rsa("2026-10"), _chave_ec("2026-11")
    provedor = ProvedorFalso(antiga)
    relogio = Relogio()
    adaptador = _adaptador(provedor, relogio=relogio)

    await _trocar(adaptador, provedor, antiga.assinar(_claims()))
    await _trocar(adaptador, provedor, antiga.assinar(_claims()))
    assert len(provedor.pedidos_a(JWKS)) == 1  # em cache

    # O provedor troca a chave. Antes de um minuto, o `kid` novo não provoca recarga.
    provedor.chaves = [nova]
    relogio.agora += 30
    assert await _motivo_da_recusa(adaptador, provedor, nova.assinar(_claims())) == "assinatura"
    assert len(provedor.pedidos_a(JWKS)) == 1

    # Passado um minuto da última carga, recarrega uma vez e aceita.
    relogio.agora += 31
    assert (await _trocar(adaptador, provedor, nova.assinar(_claims()))).sub == SUB
    assert len(provedor.pedidos_a(JWKS)) == 2

    # Um `kid` que nem o JWKS novo tem recarrega uma vez só, e só depois de outro minuto.
    relogio.agora += 61
    desconhecido = _chave_rsa("sem-chave")
    for _ in range(3):
        assert await _motivo_da_recusa(adaptador, provedor, desconhecido.assinar(_claims())) == (
            "assinatura"
        )
    assert len(provedor.pedidos_a(JWKS)) == 3


async def test_trocas_simultaneas_durante_a_carga_do_jwks_conferem_com_a_mesma_carga() -> None:
    """004/R3.2 (a troca que chega enquanto outra carrega o JWKS espera essa carga, em vez de
    recusar um `id_token` válido por `assinatura`; a recarga continua no máximo uma por minuto)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    provedor.atraso_do_jwks = 0.2  # a primeira troca ainda espera o JWKS quando a segunda chega
    relogio = Relogio()
    adaptador = _adaptador(provedor, relogio=relogio)

    async def trocar(id_token: str) -> OidcIdentity:
        provedor.id_token = id_token
        return await adaptador.exchange("codigo", code_verifier="v" * 64, nonce=NONCE)

    identidades = await asyncio.gather(*(trocar(chave.assinar(_claims())) for _ in range(2)))

    assert [identidade.sub for identidade in identidades] == [SUB, SUB]
    assert len(provedor.pedidos_a(JWKS)) == 1

    # Um `kid` desconhecido em trocas simultâneas também recarrega uma vez só.
    relogio.agora += 61
    desconhecido = _chave_rsa("sem-chave").assinar(_claims())
    recusas = await asyncio.gather(
        *(trocar(desconhecido) for _ in range(2)), return_exceptions=True
    )

    assert [getattr(recusa, "motivo", recusa) for recusa in recusas] == ["assinatura"] * 2
    assert len(provedor.pedidos_a(JWKS)) == 2


async def test_jwks_fora_do_ar_e_recusado_como_troca_sem_esperar_um_minuto() -> None:
    """004/R3.2, R3.5 (provedor fora do ar é motivo `troca` na auditoria, nunca `assinatura`;
    a busca que falhou não conta como recarga, e o login volta assim que o provedor volta)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    provedor.respostas[JWKS] = lambda _: httpx.Response(503, text="fora do ar")
    adaptador = _adaptador(provedor, relogio=Relogio())  # o relógio não anda neste teste
    id_token = chave.assinar(_claims())

    assert await _motivo_da_recusa(adaptador, provedor, id_token) == "troca"
    assert await _motivo_da_recusa(adaptador, provedor, id_token) == "troca"

    del provedor.respostas[JWKS]
    assert (await _trocar(adaptador, provedor, id_token)).sub == SUB
    assert len(provedor.pedidos_a(JWKS)) == 3


async def test_acr_fora_dos_exigidos_e_recusado() -> None:
    """004/R3.6 (com OIDC_REQUIRED_ACR, `acr` ausente ou fora da lista é recusado)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    adaptador = _adaptador(provedor, acr=("mfa", "gold"))

    for acr in (AUSENTE, "basic", ["mfa"]):
        token = chave.assinar(_claims(acr=acr))
        assert await _motivo_da_recusa(adaptador, provedor, token) == "acr"

    identidade = await _trocar(adaptador, provedor, chave.assinar(_claims(acr="gold")))
    assert identidade.acr == "gold"


async def test_acr_nao_e_exigido_sem_configuracao() -> None:
    """004/R3.6 (só ONDE OIDC_REQUIRED_ACR estiver configurado)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)

    identidade = await _trocar(_adaptador(provedor), provedor, chave.assinar(_claims(acr="1")))

    assert identidade.acr == "1"


def _erro_de_rede(pedido: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("recusada", request=pedido)


RESPOSTAS_DE_TROCA_COM_FALHA: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "codigo_recusado": lambda _: httpx.Response(400, json={"error": "invalid_grant"}),
    "erro_do_servidor": lambda _: httpx.Response(503, text="fora do ar"),
    "sem_id_token": lambda _: httpx.Response(
        200, json={"access_token": "opaco", "token_type": "Bearer"}
    ),
    "resposta_nao_json": lambda _: httpx.Response(200, text="<html>"),
    "erro_de_rede": _erro_de_rede,
}


@pytest.mark.parametrize(
    "resposta", RESPOSTAS_DE_TROCA_COM_FALHA.values(), ids=RESPOSTAS_DE_TROCA_COM_FALHA.keys()
)
async def test_falha_na_troca_do_codigo_e_recusada_com_motivo_troca(
    resposta: Callable[[httpx.Request], httpx.Response],
) -> None:
    """004/R3.2 (a troca do código pelo token falhou)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    provedor.resposta_do_token = resposta

    assert await _motivo_da_recusa(_adaptador(provedor), provedor, chave.assinar(_claims())) == (
        "troca"
    )


ENDERECOS_INVALIDOS = {
    "ipv6_sem_colchete": "https://[::1/certs",
    "porta_fora_da_faixa": "https://idp.teste:99999/certs",
    "controle_no_host": "https://idp\x00.teste/certs",
    "controle_no_caminho": "https://idp.teste/\x7fcerts",
}


@pytest.mark.parametrize("campo", ["authorization_endpoint", "token_endpoint", "jwks_uri"])
@pytest.mark.parametrize("endereco", ENDERECOS_INVALIDOS.values(), ids=ENDERECOS_INVALIDOS.keys())
async def test_descoberta_com_endereco_invalido_nao_usa_o_provedor(
    campo: str, endereco: str
) -> None:
    """004/R3.2, R3.5 (endereço da descoberta que não é um `https://` válido: 503 no início do
    login e motivo `troca` no callback, sem exceção crua)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    provedor.descoberta_extra = {campo: endereco}
    adaptador = _adaptador(provedor)

    with pytest.raises(ServiceUnavailable):
        await adaptador.authorization_url(state="e", nonce=NONCE, code_challenge="d")
    assert await _motivo_da_recusa(adaptador, provedor, chave.assinar(_claims())) == "troca"
    assert provedor.pedidos_a(TROCA) == []


@pytest.mark.parametrize(
    "extra",
    [
        {"expires_in": ["300"]},
        {"expires_in": {"segundos": 300}},
        {"expires_in": float("inf")},
        {"expires_at": [1]},
    ],
    ids=["expires_in_lista", "expires_in_objeto", "expires_in_infinito", "expires_at_lista"],
)
async def test_resposta_do_token_fora_do_padrao_e_recusada_com_motivo_troca(
    extra: dict[str, object],
) -> None:
    """004/R3.2, R3.5 (a Authlib levanta `TypeError` ou `OverflowError` com um `expires_in`
    estranho: é falha da troca, motivo `troca`)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    provedor.token_extra = extra

    assert await _motivo_da_recusa(_adaptador(provedor), provedor, chave.assinar(_claims())) == (
        "troca"
    )


def _json_aninhado_demais(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"[" * 100_000 + b"]" * 100_000, headers=JSON)


@pytest.mark.parametrize("endereco", [DESCOBERTA, TROCA, JWKS], ids=["descoberta", "token", "jwks"])
async def test_json_aninhado_demais_do_provedor_e_recusado_com_motivo_troca(endereco: str) -> None:
    """004/R3.2, R3.5 (resposta que o `json` não consegue ler, por `RecursionError`, é falha do
    provedor, motivo `troca`)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave)
    provedor.respostas[endereco] = _json_aninhado_demais

    assert await _motivo_da_recusa(_adaptador(provedor), provedor, chave.assinar(_claims())) == (
        "troca"
    )


async def test_adaptador_montado_pela_configuracao_usa_a_descoberta_padrao() -> None:
    """004/R3.2, R3.8 (emissor, cliente, retorno e `acr` vêm de `Settings`)"""
    chave = _chave_rsa()
    provedor = ProvedorFalso(chave, descoberta=f"{EMISSOR}/.well-known/openid-configuration")
    settings = make_settings(
        oidc_issuer=EMISSOR,
        oidc_client_id=CLIENTE,
        oidc_client_secret=SEGREDO,
        oidc_redirect_uri=RETORNO,
        frontend_url="https://sgs.teste/",
        cors_origins=("https://sgs.teste",),
        oidc_required_acr="mfa",
    )
    adaptador = AuthlibOidc.from_settings(settings, transport=provedor.transporte())

    url = await adaptador.authorization_url(state="e", nonce=NONCE, code_challenge="d")
    identidade = await _trocar(adaptador, provedor, chave.assinar(_claims(acr="mfa")))

    assert parse_qs(urlsplit(url).query)["acr_values"] == ["mfa"]
    assert identidade.username == "maria.silva"
