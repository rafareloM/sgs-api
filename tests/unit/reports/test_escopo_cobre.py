"""Comparação de escopos para o download por outra pessoa (005/T12; design § Escopo dos
relatórios, R3.3)."""

import json
from uuid import UUID, uuid4

import pytest

from src.modules.access.domain.authorization import EscopoLeitura
from src.modules.reports.domain.escopo import (
    EscopoGravado,
    escopo_cobre,
    escopo_gravado,
    escopo_para_gravar,
)

U1 = UUID("018f0000-0000-7000-8000-000000000001")
U2 = UUID("018f0000-0000-7000-8000-000000000002")

GLOBAL = EscopoGravado(global_=True)


@pytest.mark.parametrize(
    "gravado",
    [
        GLOBAL,
        EscopoGravado(areas=(1, 2)),
        EscopoGravado(distritos=(4,), unidades=(U1,)),
    ],
)
def test_global_cobre_tudo(gravado: EscopoGravado) -> None:
    """005/R3.3: quem tem escopo global cobre qualquer relatório."""
    assert escopo_cobre(GLOBAL, gravado)


@pytest.mark.parametrize(
    "usuario",
    [
        EscopoGravado(areas=(1, 2, 3), distritos=(1, 2, 3, 4, 5, 6, 7, 8)),
        EscopoGravado(unidades=(U1, U2)),
    ],
)
def test_so_global_cobre_global(usuario: EscopoGravado) -> None:
    """005/R3.3: um relatório gerado no escopo global só é coberto por outro global."""
    assert not escopo_cobre(usuario, GLOBAL)


@pytest.mark.parametrize(
    ("usuario", "gravado"),
    [
        (EscopoGravado(areas=(1, 2)), EscopoGravado(areas=(2,))),
        (EscopoGravado(distritos=(3,)), EscopoGravado(distritos=(3,))),
        (
            EscopoGravado(areas=(1,), distritos=(2, 3), unidades=(U1, U2)),
            EscopoGravado(areas=(1,), distritos=(3,), unidades=(U2,)),
        ),
        (EscopoGravado(areas=(2, 1)), EscopoGravado(areas=(1, 2, 1))),
    ],
)
def test_cobre_quando_cada_conjunto_esta_contido(
    usuario: EscopoGravado, gravado: EscopoGravado
) -> None:
    """005/R3.3: escopo igual ou maior, conjunto a conjunto, sem importar ordem nem repetição."""
    assert escopo_cobre(usuario, gravado)


@pytest.mark.parametrize(
    ("usuario", "gravado"),
    [
        (EscopoGravado(areas=(1,)), EscopoGravado(areas=(1, 2))),
        (EscopoGravado(areas=(1, 2)), EscopoGravado(areas=(1,), unidades=(U1,))),
        (EscopoGravado(unidades=(U1,)), EscopoGravado(unidades=(U2,))),
    ],
)
def test_nao_cobre_quando_falta_algum_item(usuario: EscopoGravado, gravado: EscopoGravado) -> None:
    """005/R3.3: basta um item do relatório fora do escopo do usuário."""
    assert not escopo_cobre(usuario, gravado)


@pytest.mark.parametrize(
    ("usuario", "gravado"),
    [
        (EscopoGravado(distritos=(4,)), EscopoGravado(unidades=(U1,))),
        (EscopoGravado(areas=(1,)), EscopoGravado(distritos=(4,))),
        (EscopoGravado(areas=(1,)), EscopoGravado(unidades=(U1,))),
    ],
)
def test_comparacao_conservadora_entre_niveis(
    usuario: EscopoGravado, gravado: EscopoGravado
) -> None:
    """005/R3.3 (design § Escopo dos relatórios): um nível não cobre outro, mesmo que as
    unidades do relatório estejam no distrito ou na área do usuário. A função não consulta o
    banco para saber onde cada unidade fica."""
    assert not escopo_cobre(usuario, gravado)


@pytest.mark.parametrize(
    "gravado", [EscopoGravado(), EscopoGravado(areas=(1,)), GLOBAL], ids=["vazio", "area", "global"]
)
def test_escopo_vazio_nao_cobre_nada(gravado: EscopoGravado) -> None:
    """005/R3.3, deny by default: sem a permissão de dados, o escopo de leitura sai vazio
    (`escopo_de_leitura`). Vazio não cobre nada, nem outro vazio."""
    assert not escopo_cobre(EscopoGravado(), gravado)


@pytest.mark.parametrize(
    "usuario",
    [EscopoGravado(areas=(1,)), EscopoGravado(unidades=(U1,))],
    ids=["area", "unidade"],
)
def test_escopo_gravado_vazio_so_e_coberto_por_global(usuario: EscopoGravado) -> None:
    """005/R3.3, deny by default: um pedido não deveria ter escopo vazio (pedir exige a
    permissão de dados). Se tiver, o vazio fica dos dois lados: só o global o cobre, e a
    conta "vazio está contido em tudo" não libera o download."""
    assert not escopo_cobre(usuario, EscopoGravado())
    assert escopo_cobre(GLOBAL, EscopoGravado())


def test_aceita_o_escopo_de_leitura_do_modulo_de_acesso() -> None:
    """005/R3.3: a rota compara o `EscopoLeitura` de quem baixa com o escopo gravado."""
    usuario = EscopoLeitura(areas=(1,), distritos=(2,), unidades=(U1,))

    assert escopo_cobre(usuario, EscopoGravado(distritos=(2,)))
    assert not escopo_cobre(usuario, EscopoGravado(distritos=(3,)))


# `scope_snapshot` ↔ `EscopoGravado` (nota da T12 para a T5 e a T6): sem a volta exata, um
# download legítimo daria 403, e a geração leria outro escopo.


def test_escopo_gravado_volta_igual_ao_que_foi_gravado() -> None:
    """005/R1.3, R3.3"""
    for escopo in (
        EscopoGravado(global_=True),
        EscopoGravado(areas=(2, 1), distritos=(3,), unidades=(uuid4(), uuid4())),
        EscopoGravado(),
    ):
        snapshot = json.loads(json.dumps(escopo_para_gravar(escopo)))
        volta = escopo_gravado(snapshot)

        assert volta.global_ is escopo.global_
        assert set(volta.areas) == set(escopo.areas)
        assert set(volta.distritos) == set(escopo.distritos)
        assert set(volta.unidades) == set(escopo.unidades)
        assert escopo_cobre(volta, escopo) is escopo_cobre(escopo, escopo)


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"global": "sim", "areas": [], "distritos": [], "unidades": []},
        {"global": False, "areas": ["1"], "distritos": [], "unidades": []},
        {"global": False, "areas": [True], "distritos": [], "unidades": []},
        {"global": False, "areas": [], "distritos": [], "unidades": ["nao-e-uuid"]},
        {"global": False, "areas": [], "distritos": [], "unidades": [], "extra": 1},
        {"global": False, "areas": 1, "distritos": [], "unidades": []},
    ],
)
def test_escopo_gravado_fora_do_formato_falha_fechado(snapshot: dict[str, object]) -> None:
    """005/R1.3 (deny by default: nada vira escopo maior)"""
    with pytest.raises(ValueError, match="fora do formato"):
        escopo_gravado(snapshot)
