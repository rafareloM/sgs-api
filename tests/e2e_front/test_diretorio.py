"""Tela Diretório (spec 014, R4 e R5; design § Diretório): execuções da sincronização LDAP e
mapeamentos grupo→papel, contra o compose com o `slapd` de laboratório."""

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect


def test_abas_conforme_permissao(sessao_de: Callable[[str], Page]) -> None:
    """R4.1: o Admin TI vê Execuções e Grupos; `#/diretorio` abre a primeira aba."""
    pagina = sessao_de("ADMIN_TI")
    pagina.goto("/#/diretorio")
    expect(pagina).to_have_url("https://localhost:18444/#/diretorio/execucoes")
    abas = pagina.locator("nav.tabs a")
    expect(abas).to_have_text(["Execuções", "Grupos"])
    expect(pagina.locator("nav.tabs a.on")).to_have_attribute("data-aba", "execucoes")
    pagina.click("nav.tabs a[data-aba=grupos]")
    expect(pagina.locator("nav.tabs a.on")).to_have_attribute("data-aba", "grupos")


@pytest.mark.parametrize("papel", ["GESTOR_DADOS", "AUDITOR"])
def test_sem_permissao_do_diretorio_mostra_sem_acesso(
    sessao_de: Callable[[str], Page], papel: str
) -> None:
    """R4.1: sem `diretorio:sync` nem `papel:assign`, a tela diz "sem acesso"."""
    pagina = sessao_de(papel)
    pagina.goto("/#/diretorio/grupos")
    expect(pagina.locator("[data-estado=sem-acesso]")).to_be_visible()
