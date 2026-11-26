"""Peças puras do login OIDC: PKCE S256 e hash do `state` (004/T7; R3.1, R3.7)."""

from src.modules.identity.domain.oidc import code_challenge_s256, hash_do_valor, mesmo_valor


def test_code_challenge_s256_do_exemplo_da_rfc_7636() -> None:
    """004/R3.1 (RFC 7636, apêndice B)"""
    verificador = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert code_challenge_s256(verificador) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_hash_do_state_e_sha256_em_hex() -> None:
    """004/R3.7 (só o hash fica no banco)"""
    valor = hash_do_valor("abc")

    assert valor == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert mesmo_valor(valor, hash_do_valor("abc"))
    assert not mesmo_valor(valor, hash_do_valor("abd"))
