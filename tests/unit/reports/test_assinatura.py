"""Assinatura dos relatórios (005/T9; design § Assinatura): ES256 sobre o SHA-256 do arquivo."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from pydantic import SecretStr, ValidationError

from src.core.config import AppEnv, DatabaseSslMode
from src.modules.reports.domain.assinatura import Assinatura, PublicJwk
from src.modules.reports.infrastructure.assinatura import Es256AssinadorDeRelatorio
from src.tools import jwt_keys
from tests.factories import make_jwt_private_keys, make_pem_privado, make_settings

# Um CSV qualquer, maior que um bloco do SHA-256: quem confere lê o arquivo inteiro.
CONTEUDO = "cnes;nome;distrito\r\n1000001;USF Alto do Céu;DS II\r\n".encode() * 500

PROD: dict[str, object] = {
    "app_env": AppEnv.PROD,
    "database_url": SecretStr(
        "postgresql+asyncpg://sgs_api:Kx9-segredo-de-verdade@db.interno:5432/sgs"
    ),
    "database_ssl_mode": DatabaseSslMode.VERIFY_FULL,
    # Sem o S3 por papel, ExternalId e chave KMS, a API não sobe em prod (005/R2.9, T4).
    "s3_bucket": "sgs-relatorios",
    "s3_assume_role_arn": "arn:aws:iam::123456789012:role/sgs-relatorios",
    "s3_external_id": "sgs-relatorios-7f3a9c",
    "s3_kms_key_id": "arn:aws:kms:sa-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab",
    "s3_sse": "aws:kms",
}


def _chave(kid: str) -> dict[str, str]:
    return {"kid": kid, "pem": make_pem_privado()}


def _assinador(*chaves: dict[str, str]) -> Es256AssinadorDeRelatorio:
    """Assinador montado como na subida: REPORT_SIGNING_KEYS lido e validado pelo `Settings`."""
    settings = make_settings(report_signing_keys=json.dumps(list(chaves)))
    assinador = Es256AssinadorDeRelatorio.from_settings(settings)
    assert assinador is not None
    return assinador


def _recusa(**overrides: object) -> str:
    """Mensagens da recusa da subida, sem o valor recebido (como `load_settings` as mostra)."""
    with pytest.raises(ValidationError) as erro:
        make_settings(**overrides)
    itens = erro.value.errors(include_input=False, include_url=False)
    return "\n".join(f"{item['loc']} {item['msg']}" for item in itens)


def _base64url(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _conferir(jwk: PublicJwk, assinatura: Assinatura, conteudo: bytes) -> None:
    """O que quem recebe o relatório faz fora da API: só a JWK publicada e o arquivo inteiro."""
    publica = ec.EllipticCurvePublicNumbers(
        int.from_bytes(_base64url(jwk.x)), int.from_bytes(_base64url(jwk.y)), ec.SECP256R1()
    ).public_key()
    r_s = _base64url(assinatura.valor)
    der = encode_dss_signature(int.from_bytes(r_s[:32]), int.from_bytes(r_s[32:]))
    publica.verify(der, conteudo, ec.ECDSA(hashes.SHA256()))


def test_assina_o_sha256_e_confere_so_com_a_jwk_publicada_sobre_o_arquivo_inteiro() -> None:
    """005/R5.1, 005/R5.4"""
    assinador = _assinador(_chave("rel-2026-11"))

    assinatura = assinador.assinar(hashlib.sha256(CONTEUDO).digest())

    assert (assinatura.kid, assinatura.algoritmo) == ("rel-2026-11", "ES256")
    assert len(_base64url(assinatura.valor)) == 64  # r‖s, RFC 7518 § 3.4
    assert set(assinatura.valor) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )  # base64url, sem `=`
    [jwk] = assinador.chaves_publicas()
    assert (jwk.kid, jwk.kty, jwk.crv, jwk.alg, jwk.use) == (
        "rel-2026-11",
        "EC",
        "P-256",
        "ES256",
        "sig",
    )
    _conferir(jwk, assinatura, CONTEUDO)
    with pytest.raises(InvalidSignature):
        _conferir(jwk, assinatura, CONTEUDO + b"\r\n")  # arquivo alterado depois


@pytest.mark.parametrize("tamanho", [0, 31, 33, 64])
def test_so_assina_um_sha256_de_32_bytes(tamanho: int) -> None:
    """005/R5.1 (assina o hash SHA-256 do arquivo, não outra coisa)"""
    with pytest.raises(ValueError, match="SHA-256"):
        _assinador(_chave("rel-2026-11")).assinar(bytes(tamanho))


def test_assinatura_antiga_confere_depois_da_rotacao() -> None:
    """005/R5.5"""
    antiga, nova = _chave("rel-2026-05"), _chave("rel-2026-11")
    sha256 = hashlib.sha256(CONTEUDO).digest()
    assinada_antes = _assinador(antiga).assinar(sha256)

    depois_da_rotacao = _assinador(nova, antiga)  # a nova entra no início da lista
    assinada_depois = depois_da_rotacao.assinar(sha256)
    publicadas = {jwk.kid: jwk for jwk in depois_da_rotacao.chaves_publicas()}

    assert list(publicadas) == ["rel-2026-11", "rel-2026-05"]
    assert assinada_depois.kid == "rel-2026-11"
    _conferir(publicadas[assinada_antes.kid], assinada_antes, CONTEUDO)
    _conferir(publicadas[assinada_depois.kid], assinada_depois, CONTEUDO)


def test_sem_chave_de_relatorio_nao_ha_assinador() -> None:
    """005/R5.1 (sem REPORT_SIGNING_KEYS nada é assinado; a exportação fica desligada)"""
    assert Es256AssinadorDeRelatorio.from_settings(make_settings()) is None


@pytest.mark.parametrize("repete", ["kid", "chave"])
def test_chave_de_relatorio_igual_a_uma_chave_jwt_recusa_a_subida(repete: str) -> None:
    """005/R5.2 (vale também para a chave JWT anterior, ainda publicada)"""
    jwt_ativa, jwt_antiga = _chave("2026-11"), _chave("2026-05")
    igual = (
        {"kid": jwt_antiga["kid"], "pem": make_pem_privado()}
        if repete == "kid"
        else {"kid": "rel-2026-11", "pem": jwt_antiga["pem"]}
    )

    mensagem = _recusa(
        jwt_private_keys=json.dumps([jwt_ativa, jwt_antiga]),
        report_signing_keys=json.dumps([_chave("rel-2026-12"), igual]),
    )

    assert f"REPORT_SIGNING_KEYS: a chave {igual['kid']} repete" in mensagem
    assert "chave JWT" in mensagem
    assert "rel-2026-12" not in mensagem  # só a chave repetida é citada
    assert "PRIVATE KEY" not in mensagem


def test_chave_de_relatorio_gerada_pela_ferramenta_e_lida_de_arquivo(tmp_path: Path) -> None:
    """005/R5.1, 005/R5.2 (`src.tools.jwt_keys` gera o arquivo; a chave não é a dos tokens)"""
    arquivo = tmp_path / "report-keys.json"
    jwt_keys.main(["--kid", "rel-2026-11", "--output", str(arquivo)])

    settings = make_settings(**PROD, report_signing_keys_file=str(arquivo))

    assert [chave.kid for chave in settings.chaves_de_relatorio] == ["rel-2026-11"]
    assert {chave.kid for chave in settings.jwt_signing_keys}.isdisjoint({"rel-2026-11"})


def test_recusa_chave_de_relatorio_igual_a_jwt_vinda_de_arquivo(tmp_path: Path) -> None:
    """005/R5.2"""
    jwt = _chave("2026-11")
    arquivo = tmp_path / "report-keys.json"
    arquivo.write_text(json.dumps([{"kid": "rel-2026-11", "pem": jwt["pem"]}]), encoding="utf-8")

    mensagem = _recusa(jwt_private_keys=json.dumps([jwt]), report_signing_keys_file=str(arquivo))

    assert "REPORT_SIGNING_KEYS_FILE: a chave rel-2026-11 repete" in mensagem


def test_recusa_chaves_de_relatorio_na_variavel_e_no_arquivo(tmp_path: Path) -> None:
    """005/R5.1 (duas fontes deixariam dúvida sobre qual chave assina)"""
    arquivo = tmp_path / "report-keys.json"
    arquivo.write_text(make_jwt_private_keys("rel-arquivo"), encoding="utf-8")

    mensagem = _recusa(
        report_signing_keys=make_jwt_private_keys("rel-variavel"),
        report_signing_keys_file=str(arquivo),
    )

    assert "REPORT_SIGNING_KEYS_FILE: defina" in mensagem


@pytest.mark.parametrize("vazio", ["", "   "], ids=["vazia", "so_espacos"])
def test_variavel_de_chave_de_relatorio_vazia_vale_como_nao_definida(
    tmp_path: Path, vazio: str
) -> None:
    """005/R5.1 (design § Configuração: sem chave, nada é assinado; `REPORT_SIGNING_KEYS=` num
    arquivo de ambiente não impede a subida)"""
    sem_chave = make_settings(report_signing_keys=vazio, report_signing_keys_file=vazio)
    assert sem_chave.chaves_de_relatorio == ()
    assert Es256AssinadorDeRelatorio.from_settings(sem_chave) is None

    arquivo = tmp_path / "report-keys.json"
    arquivo.write_text(make_jwt_private_keys("rel-arquivo"), encoding="utf-8")
    do_arquivo = make_settings(report_signing_keys=vazio, report_signing_keys_file=str(arquivo))
    assert [chave.kid for chave in do_arquivo.chaves_de_relatorio] == ["rel-arquivo"]

    da_variavel = make_settings(
        report_signing_keys=make_jwt_private_keys("rel-variavel"), report_signing_keys_file=vazio
    )
    assert [chave.kid for chave in da_variavel.chaves_de_relatorio] == ["rel-variavel"]


def test_chave_de_relatorio_ilegivel_recusa_a_subida_sem_expor_o_valor() -> None:
    """005/R5.1 (mesmo leitor das chaves JWT: erro pela posição e pelo kid, nunca pelo PEM)"""
    publica = make_pem_privado().replace("PRIVATE", "PUBLIC")

    mensagem = _recusa(report_signing_keys=json.dumps([{"kid": "rel-2026-11", "pem": publica}]))

    assert mensagem.startswith("('report_signing_keys',) chave rel-2026-11: use uma chave privada")
    assert "PUBLIC KEY" not in mensagem


@pytest.mark.parametrize(
    "kids", [("rel-exemplo",), ("rel-2026-11", "rel-troque-esta")], ids=["ativa", "antiga"]
)
def test_prod_recusa_chave_de_relatorio_de_exemplo(kids: tuple[str, ...]) -> None:
    """005/R5.1 (design § Configuração: chave de exemplo recusada em prod, pelo `kid`)"""
    mensagem = _recusa(**PROD, report_signing_keys=make_jwt_private_keys(*kids))

    assert "REPORT_SIGNING_KEYS: chave de exemplo não é aceita em prod" in mensagem


def test_chave_de_relatorio_de_exemplo_vale_fora_de_prod() -> None:
    """005/R5.1 (a recusa de segredo de exemplo vale só em prod)"""
    settings = make_settings(report_signing_keys=make_jwt_private_keys("rel-exemplo"))

    assert [chave.kid for chave in settings.chaves_de_relatorio] == ["rel-exemplo"]
