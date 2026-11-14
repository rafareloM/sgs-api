"""Escopo de uma permissão limitado pelo `max_scope` dela no papel (003/T3, design § Resolução).

Os casos típicos (cada papel no seu escopo) estão em
tests/integration/access/test_permissoes_efetivas.py. Aqui ficam as atribuições num escopo
diferente do máximo, com o padrão registrado em "Perguntas em aberto" da 003: o escopo da
atribuição vale se estiver contido no máximo; senão, a atribuição não dá aquela permissão.
"""

from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.modules.access.domain.authorization import (
    Area,
    Concessao,
    Distrito,
    Escopo,
    Global,
    Unidade,
    escopo_de,
    permissoes_efetivas,
)

SAUDE_MENTAL, DS_III = 1, 3
CAPS = UUID("01970000-0000-7000-8000-000000000001")

ESCOPOS: dict[str, Escopo] = {
    "global": Global(),
    "area": Area(SAUDE_MENTAL),
    "distrito": Distrito(DS_III),
    "unidade": Unidade(CAPS),
}

# (escopo da atribuição, escopo máximo da permissão) → escopo efetivo; None = sem a permissão.
CASOS: list[tuple[str, str, Escopo | None]] = [
    # Máximo global é a letra G da matriz: vale em todo lugar.
    ("area", "global", Global()),
    ("distrito", "global", Global()),
    ("unidade", "global", Global()),
    # Mesmo nível: o escopo da atribuição.
    ("area", "area", Area(SAUDE_MENTAL)),
    ("distrito", "distrito", Distrito(DS_III)),
    ("unidade", "unidade", Unidade(CAPS)),
    # A unidade está dentro da sua área e do seu distrito.
    ("unidade", "area", Unidade(CAPS)),
    ("unidade", "distrito", Unidade(CAPS)),
    # Mais amplo que o máximo, ou do outro eixo (área e distrito não se contêm): nega.
    ("global", "area", None),
    ("global", "distrito", None),
    ("global", "unidade", None),
    ("area", "distrito", None),
    ("area", "unidade", None),
    ("distrito", "area", None),
    ("distrito", "unidade", None),
]


@pytest.mark.parametrize(
    ("atribuicao", "maximo", "efetivo"),
    CASOS,
    ids=[f"{atribuicao}-ate-{maximo}" for atribuicao, maximo, _ in CASOS],
)
def test_escopo_da_atribuicao_fica_dentro_do_maximo(
    atribuicao: str, maximo: str, efetivo: Escopo | None
) -> None:
    """003/R1.2: `max_scope` limita o escopo com que o papel exerce a permissão."""
    concessao = Concessao("unidade:update", escopo_maximo=maximo, escopo=ESCOPOS[atribuicao])

    permissoes = permissoes_efetivas([concessao])

    esperado = {} if efetivo is None else {"unidade:update": (efetivo,)}
    assert dict(permissoes) == esperado


def test_escopos_repetidos_aparecem_uma_vez() -> None:
    """003/R4.3: dois papéis que dão a mesma permissão no mesmo escopo."""
    concessoes = [
        Concessao("unidade:read", escopo_maximo="global", escopo=Area(SAUDE_MENTAL)),
        Concessao("unidade:read", escopo_maximo="global", escopo=Distrito(DS_III)),
        Concessao("unidade:update", escopo_maximo="area", escopo=Area(SAUDE_MENTAL)),
        Concessao("unidade:update", escopo_maximo="distrito", escopo=Distrito(DS_III)),
    ]

    permissoes = permissoes_efetivas(concessoes)

    assert {codigo: set(escopos) for codigo, escopos in permissoes.items()} == {
        "unidade:read": {Global()},
        "unidade:update": {Area(SAUDE_MENTAL), Distrito(DS_III)},
    }
    assert len(permissoes["unidade:read"]) == 1


@pytest.mark.parametrize(
    ("nivel", "id_do_escopo"),
    [("global", "3"), ("unidade", None), ("area", "saude-mental"), ("estado", "3")],
    ids=["global-com-id", "unidade-sem-id", "area-sem-numero", "nivel-desconhecido"],
)
def test_atribuicao_com_escopo_mal_formado_falha_em_vez_de_conceder(
    nivel: str, id_do_escopo: str | None
) -> None:
    """003/R4.2: deny by default, também diante de um dado corrompido no banco."""
    with pytest.raises(ValueError, match="escopo de atribuição inválido"):
        escopo_de(nivel, id_do_escopo)


_CONCESSOES = st.lists(
    st.builds(
        Concessao,
        permissao=st.sampled_from(["unidade:read", "unidade:update", "auditoria:read"]),
        escopo_maximo=st.sampled_from(list(ESCOPOS)),
        escopo=st.one_of(
            st.just(Global()),
            st.builds(Area, st.sampled_from([1, 2])),
            st.builds(Distrito, st.sampled_from([3, 5])),
            st.builds(Unidade, st.just(CAPS)),
        ),
    ),
    max_size=6,
)


@given(concessoes=_CONCESSOES, data=st.data())
def test_tirar_atribuicoes_nunca_aumenta_as_permissoes(
    concessoes: list[Concessao], data: st.DataObject
) -> None:
    """003/R4.5: design § Estratégia de testes, remover uma atribuição nunca aumenta permissões."""
    restantes = [concessao for concessao in concessoes if data.draw(st.booleans())]

    todas = permissoes_efetivas(concessoes)
    menos = permissoes_efetivas(restantes)

    for codigo, escopos in menos.items():
        assert set(escopos) <= set(todas[codigo])
