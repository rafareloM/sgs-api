"""Menu e telas por papel, só com as permissões existentes (spec 012, T5: R3.1 a R3.5; DF8).

O menu esperado é o da tabela de perfis do design (§ Perfis), com os rótulos de R10.1 e R12.2.
"""

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

MENUS = {
    "GESTOR_DADOS": [
        "Início",
        "Unidades",
        "Cadastrar unidade",
        "Validações",
        "Qualidade dos dados",
        "Histórico de alterações",
        "Relatórios",  # spec 014, R1.1: relatorio:export
        "Tabelas de referência",  # R16.1 (emenda funcional 2): regra_validacao:manage global
        "Importar planilha",
    ],
    "TECNICO_DISTRITAL": [
        "Início",
        "Unidades",
        "Solicitar cadastro",
        "Solicitações",
        "Qualidade dos dados",
        "Histórico de alterações",
    ],
    "GESTOR_UNIDADE": ["Minha unidade", "Minhas solicitações", "Histórico da unidade"],
    "COORD_TECNICO": [
        "Início",
        "Unidades",
        "Validações",
        "Qualidade dos dados",
        "Histórico de alterações",
        "Relatórios",
    ],
    "DIRETORIA": ["Início", "Unidades", "Qualidade dos dados", "Relatórios"],
    "AUDITOR": ["Unidades", "Histórico geral", "Verificação da cadeia", "Relatórios"],
    "ADMIN_TI": ["Diretório", "Papéis e atribuições", "Usuários"],  # spec 014, R4.1
}

INICIOS = {
    "GESTOR_DADOS": "#/inicio",
    "TECNICO_DISTRITAL": "#/inicio",
    "COORD_TECNICO": "#/inicio",
    "DIRETORIA": "#/inicio",
    "AUDITOR": "#/historico",
    "ADMIN_TI": "#/diretorio/execucoes",  # spec 014, P3: primeira tela do menu
}

# Itens sem backend: visíveis e marcados "em desenvolvimento" (R10.1, R13.1, R12.2).
EM_DESENVOLVIMENTO = {
    "GESTOR_DADOS": {"Validações", "Importar planilha"},
    "TECNICO_DISTRITAL": {"Solicitar cadastro", "Solicitações", "Histórico de alterações"},
    "GESTOR_UNIDADE": {"Minhas solicitações"},
    "COORD_TECNICO": {"Validações", "Histórico de alterações"},
    "DIRETORIA": set(),
    "AUDITOR": set(),
    "ADMIN_TI": {"Usuários"},
}


def _menu(pagina: Page) -> list[str]:
    return [t.strip() for t in pagina.locator(".nav a").all_inner_texts()]


@pytest.mark.parametrize("papel", list(MENUS))
def test_menu_vem_das_permissoes_do_papel(sessao_de: Callable[[str], Page], papel: str) -> None:
    """R3.1, R3.2 (DF8)"""
    pagina = sessao_de(papel)
    assert _menu(pagina) == MENUS[papel]
    marcados = {
        t.strip() for t in pagina.locator(".nav a[data-em-desenvolvimento]").all_inner_texts()
    }
    assert marcados == EM_DESENVOLVIMENTO[papel]


@pytest.mark.parametrize("papel", list(INICIOS))
def test_inicio_do_papel(sessao_de: Callable[[str], Page], papel: str) -> None:
    """R3.5, R4.1: sem dashboard:read, o início é a primeira tela útil do menu."""
    pagina = sessao_de(papel)
    pagina.goto("/#/")
    expect(pagina).to_have_url(f"https://localhost:18444/{INICIOS[papel]}")


def test_gestor_de_unidade_comeca_na_propria_ficha(sessao_de: Callable[[str], Page]) -> None:
    """R3.5: o início do Gestor de Unidade é a ficha da unidade do escopo dele."""
    pagina = sessao_de("GESTOR_UNIDADE")
    me = pagina.evaluate("""async () => {
      const h = {'X-Requested-With': 'sgs'};
      const r = await fetch('/api/v1/auth/refresh', {method: 'POST', headers: h});
      const t = (await r.json()).access_token;
      return (await fetch('/api/v1/me', {headers: {Authorization: 'Bearer ' + t}})).json();
    }""")
    unidade = next(a["escopo_id"] for a in me["papeis"] if a["papel"] == "GESTOR_UNIDADE")
    pagina.goto("/#/")
    expect(pagina).to_have_url(f"https://localhost:18444/#/unidade/{unidade}")


@pytest.mark.parametrize(
    ("papel", "rota", "api"),
    [
        ("DIRETORIA", "#/historico", "/api/v1/auditoria/eventos"),
        ("ADMIN_TI", "#/unidades", "/api/v1/unidades"),
        ("TECNICO_DISTRITAL", "#/importar", None),
    ],
)
def test_rota_de_outro_perfil_mostra_sem_acesso_e_a_api_nega(
    sessao_de: Callable[[str], Page], papel: str, rota: str, api: str | None
) -> None:
    """R3.3, R3.4: a tela diz "sem acesso" e a própria API responde 403."""
    pagina = sessao_de(papel)
    pagina.goto(f"/{rota}")
    expect(pagina.locator("[data-estado=sem-acesso]")).to_be_visible()
    if api is not None:
        status = pagina.evaluate(
            """async (url) => {
              const h = {'X-Requested-With': 'sgs'};
      const r = await fetch('/api/v1/auth/refresh', {method: 'POST', headers: h});
              const t = (await r.json()).access_token;
              return (await fetch(url, {headers: {Authorization: 'Bearer ' + t}})).status;
            }""",
            api,
        )
        assert status == 403


def test_tecnico_distrital_nao_ve_controles_de_escrita_no_menu(
    sessao_de: Callable[[str], Page],
) -> None:
    """R3.4, R7.4: "Solicitar cadastro" aparece só como em desenvolvimento, sem formulário."""
    pagina = sessao_de("TECNICO_DISTRITAL")
    pagina.goto("/#/nova")
    expect(pagina.locator("[data-estado=em-desenvolvimento]")).to_be_visible()
    expect(pagina.locator("#view form")).to_have_count(0)
