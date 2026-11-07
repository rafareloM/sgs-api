"""`pode()` contra a matriz de papéis e permissões (003/T2).

A matriz é a de docs/architecture/arquitetura-conceitual.md § 4, e o escopo típico de cada papel
vem do § 2. Cada célula vira um caso: um usuário só com aquele papel, no escopo típico, tenta a
permissão sem alvo e em quatro unidades.
"""

from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.modules.access.domain.authorization import (
    Alvo,
    Area,
    Distrito,
    Escopo,
    Global,
    PermissoesEfetivas,
    Unidade,
    pode,
)

PAPEIS = (
    "ADMIN_TI",
    "GESTOR_DADOS",
    "COORD_TECNICO",
    "TECNICO_DISTRITAL",
    "GESTOR_UNIDADE",
    "DIRETORIA",
    "AUDITOR",
)

# G = global · A = na sua área técnica · D = no seu distrito · U = na sua unidade
# - = sem permissão. Colunas na ordem de PAPEIS. O AUDITOR exporta "só auditoria": restrição do
# tipo de relatório (spec 005), não de escopo.
MATRIZ: dict[str, tuple[str, ...]] = {
    "unidade:read":           ("-", "G", "G", "G", "G", "G", "G"),
    "unidade:create":         ("-", "G", "A", "-", "-", "-", "-"),
    "unidade:update":         ("-", "G", "A", "D", "U", "-", "-"),
    "unidade:deactivate":     ("-", "G", "-", "-", "-", "-", "-"),
    "equipamento:write":      ("-", "G", "A", "D", "U", "-", "-"),
    "servico:write":          ("-", "G", "A", "D", "U", "-", "-"),
    "alteracao:propor":       ("-", "G", "A", "D", "U", "-", "-"),
    "alteracao:validar":      ("-", "G", "A", "-", "-", "-", "-"),
    "regra_validacao:manage": ("-", "G", "-", "-", "-", "-", "-"),
    "auditoria:read":         ("-", "G", "A", "D", "U", "-", "G"),
    "auditoria:read_acessos": ("G", "-", "-", "-", "-", "-", "G"),
    "dashboard:read":         ("-", "G", "G", "G", "G", "G", "-"),
    "relatorio:export":       ("-", "G", "A", "-", "-", "G", "G"),
    "relatorio:download":     ("-", "G", "A", "-", "-", "G", "G"),
    "usuario:manage":         ("G", "-", "-", "-", "-", "-", "-"),
    "papel:assign":           ("G", "-", "-", "-", "-", "-", "-"),
    "diretorio:sync":         ("G", "-", "-", "-", "-", "-", "-"),
}  # fmt: skip

SAUDE_MENTAL, APS = 1, 2
DS_III, DS_V = 3, 5

# O usuário de cada caso trabalha num CAPS (Saúde Mental) do DS III: é a área do coordenador, o
# distrito do técnico e a unidade do gestor.
CAPS_DS_III = Alvo(
    unidade_id=UUID("01970000-0000-7000-8000-000000000001"),
    distrito_id=DS_III,
    area_id=SAUDE_MENTAL,
)
ALVOS: dict[str, Alvo | None] = {
    "sem alvo": None,
    "a própria unidade": CAPS_DS_III,
    "outra unidade do distrito": Alvo(
        unidade_id=UUID("01970000-0000-7000-8000-000000000002"), distrito_id=DS_III, area_id=APS
    ),
    "outra unidade da área": Alvo(
        unidade_id=UUID("01970000-0000-7000-8000-000000000003"),
        distrito_id=DS_V,
        area_id=SAUDE_MENTAL,
    ),
    "unidade de fora": Alvo(
        unidade_id=UUID("01970000-0000-7000-8000-000000000004"), distrito_id=DS_V, area_id=APS
    ),
}

# Onde cada tipo de célula autoriza, pela regra do design (§ Verificação).
AUTORIZA_EM: dict[str, set[str]] = {
    "G": set(ALVOS),
    "A": {"sem alvo", "a própria unidade", "outra unidade da área"},
    "D": {"sem alvo", "a própria unidade", "outra unidade do distrito"},
    "U": {"sem alvo", "a própria unidade"},
    "-": set(),
}

ESCOPO_TIPICO: dict[str, Escopo] = {
    "G": Global(),
    "A": Area(SAUDE_MENTAL),
    "D": Distrito(DS_III),
    "U": Unidade(CAPS_DS_III.unidade_id),
}


def permissoes_do_papel(papel: str) -> PermissoesEfetivas:
    """Permissões efetivas de quem tem só esse papel, atribuído no escopo típico."""
    coluna = PAPEIS.index(papel)
    return {
        perm: [ESCOPO_TIPICO[linha[coluna]]]
        for perm, linha in MATRIZ.items()
        if linha[coluna] != "-"
    }


CELULAS = [
    pytest.param(papel, perm, linha[coluna], id=f"{papel}-{perm}")
    for perm, linha in MATRIZ.items()
    for coluna, papel in enumerate(PAPEIS)
]


@pytest.mark.parametrize(("papel", "perm", "celula"), CELULAS)
def test_cada_papel_so_pode_o_que_a_matriz_da_no_seu_escopo(
    papel: str, perm: str, celula: str
) -> None:
    """003/R4.2, 003/R4.3"""
    perms = permissoes_do_papel(papel)

    autorizados = {nome for nome, alvo in ALVOS.items() if pode(perms, perm, alvo)}

    assert autorizados == AUTORIZA_EM[celula]


def test_com_dois_papeis_basta_um_escopo_cobrir_a_unidade() -> None:
    """003/R4.3: técnico do DS III que também é gestor de uma unidade do DS V (arquitetura § 2)."""
    unidade_gerida_no_ds_v = ALVOS["outra unidade da área"]
    assert unidade_gerida_no_ds_v is not None
    perms: PermissoesEfetivas = {
        "unidade:update": [Distrito(DS_III), Unidade(unidade_gerida_no_ds_v.unidade_id)]
    }

    autorizados = {nome for nome, alvo in ALVOS.items() if pode(perms, "unidade:update", alvo)}

    assert autorizados == {
        "sem alvo",
        "a própria unidade",
        "outra unidade do distrito",
        "outra unidade da área",
    }


# Poucos ids, para os escopos sorteados acertarem os alvos com frequência.
_IDS_DE_UNIDADE = [alvo.unidade_id for alvo in ALVOS.values() if alvo is not None]
_ESCOPOS = st.one_of(
    st.just(Global()),
    st.builds(Area, st.sampled_from([SAUDE_MENTAL, APS])),
    st.builds(Distrito, st.sampled_from([DS_III, DS_V])),
    st.builds(Unidade, st.sampled_from(_IDS_DE_UNIDADE)),
)
_PERMISSOES = st.dictionaries(st.sampled_from(list(MATRIZ)), st.lists(_ESCOPOS, max_size=4))


@given(
    maiores=_PERMISSOES,
    perm=st.sampled_from(list(MATRIZ)),
    alvo=st.sampled_from(list(ALVOS.values())),
    data=st.data(),
)
def test_tirar_escopos_nunca_aumenta_o_acesso(
    maiores: dict[str, list[Escopo]], perm: str, alvo: Alvo | None, data: st.DataObject
) -> None:
    """003/R4.3: design § Estratégia de testes, remover uma atribuição nunca aumenta permissões."""
    menores = {
        codigo: [escopo for escopo in escopos if data.draw(st.booleans())]
        for codigo, escopos in maiores.items()
        if data.draw(st.booleans())
    }

    assert not pode(menores, perm, alvo) or pode(maiores, perm, alvo)
