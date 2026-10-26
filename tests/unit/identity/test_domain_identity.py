"""Testes unitários das entidades de domínio de identidade (Perfil, Usuario)."""

import pytest

from src.core.errors import DomainValidationError
from src.modules.identity.domain.perfil import Perfil
from src.modules.identity.domain.usuario import Usuario

VALID_HASH = "$2b$12$GkQ1zKVQJcF9m6mB0KKxvu3fd8m2fGXQxmz9g8rM3S5uW1aQw9J3."


def test_perfil_valido() -> None:
    perfil = Perfil(nome_perfil="Gestor de Dados", permissoes="gestao_dados;auditoria")
    assert perfil.nome_perfil == "Gestor de Dados"
    assert perfil.permissoes == "gestao_dados;auditoria"


@pytest.mark.parametrize("nome", ["", "   "])
def test_perfil_recusa_nome_vazio(nome: str) -> None:
    with pytest.raises(DomainValidationError) as exc:
        Perfil(nome_perfil=nome, permissoes="gestao_dados")
    assert any(err.campo == "nome_perfil" for err in exc.value.errors)


@pytest.mark.parametrize("permissoes", ["", "   "])
def test_perfil_recusa_permissoes_vazias(permissoes: str) -> None:
    with pytest.raises(DomainValidationError) as exc:
        Perfil(nome_perfil="Gestor", permissoes=permissoes)
    assert any(err.campo == "permissoes" for err in exc.value.errors)


def test_usuario_valido_sem_2fa() -> None:
    usuario = Usuario(
        nome="Bruno Costa",
        email="bruno.costa@sauderecife.pe.gov.br",
        senha_hash=VALID_HASH,
        id_perfil=1,
    )
    assert usuario.nome == "Bruno Costa"
    assert usuario.dois_fator_habilitado is False
    assert usuario.dois_fator_segredo is None


def test_usuario_valido_com_2fa() -> None:
    usuario = Usuario(
        nome="Ana Paula",
        email="ana.paula@sauderecife.pe.gov.br",
        senha_hash=VALID_HASH,
        id_perfil=1,
        dois_fator_habilitado=True,
        dois_fator_segredo="GDD-01-TOTP",
    )
    assert usuario.dois_fator_habilitado is True
    assert usuario.dois_fator_segredo == "GDD-01-TOTP"


@pytest.mark.parametrize("email", ["invalido", "teste@", "@saude.pe", "teste@.com"])
def test_usuario_recusa_email_invalido(email: str) -> None:
    with pytest.raises(DomainValidationError) as exc:
        Usuario(
            nome="Usuario Teste",
            email=email,
            senha_hash=VALID_HASH,
            id_perfil=1,
        )
    assert any(err.campo == "email" for err in exc.value.errors)


def test_usuario_recusa_senha_curta() -> None:
    with pytest.raises(DomainValidationError) as exc:
        Usuario(
            nome="Usuario Teste",
            email="teste@sauderecife.pe.gov.br",
            senha_hash="hash_muito_curto",
            id_perfil=1,
        )
    assert any(err.campo == "senha_hash" for err in exc.value.errors)


@pytest.mark.parametrize("segredo", [None, "", "   "])
def test_usuario_recusa_2fa_habilitado_sem_segredo(segredo: str | None) -> None:
    with pytest.raises(DomainValidationError) as exc:
        Usuario(
            nome="Usuario Teste",
            email="teste@sauderecife.pe.gov.br",
            senha_hash=VALID_HASH,
            id_perfil=1,
            dois_fator_habilitado=True,
            dois_fator_segredo=segredo,
        )
    assert any(err.campo == "dois_fator_segredo" for err in exc.value.errors)
