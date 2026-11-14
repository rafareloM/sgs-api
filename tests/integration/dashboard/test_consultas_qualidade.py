"""Consultas de qualidade do cadastro pela API (spec 011, R2; design § Rotas e § Consultas).

Cada teste semeia o próprio cadastro, direto no banco pelo dono, e confere que a rota devolve
exatamente os casos semeados. O escopo de leitura vem das atribuições do usuário (spec 003).
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.core.ids import uuid7
from src.main import create_app
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor
from tests.integration.registry.cadastro import (
    inserir_equipamento,
    inserir_servico,
    inserir_unidade,
)

UNIDADES_SEM_SERVICO = "/api/v1/dashboard/consultas/unidades-sem-servico"
CONCILIACAO = "/api/v1/dashboard/consultas/conciliacao-unidade-equipamento"

# Id de referência no formato certo que não existe (a 0006 semeia 8 distritos e 7 tipos).
INEXISTENTE = 999


@pytest.fixture
async def app(banco: BancoDeTeste) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(database_url=SecretStr(banco.url_api)))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def cliente(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente


@pytest.fixture
async def sessoes(banco: BancoDeTeste) -> AsyncIterator[Sessoes]:
    """Sessões com o login da API (papel sgs_app), para criar usuários e atribuições."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def dono(banco: BancoDeTeste) -> AsyncIterator[AsyncConnection]:
    """Conexão do dono do banco (superusuário), para semear o cadastro e papéis de teste. O teste
    confirma com `commit()` antes de chamar a API."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        yield conexao
    await engine.dispose()


# Na matriz semeada (0003), todo papel com `dashboard:read` o tem com escopo máximo global, e
# escopo global vale em todo lugar, seja qual for o da atribuição (padrão da 003/T3). Para exercitar
# o escopo de leitura nas consultas (011/R2.5), o teste cria um papel com `dashboard:read` limitado
# ao distrito da atribuição.
PAINEL_DISTRITAL = "PAINEL_DISTRITAL_TESTE"


async def _criar_painel_distrital(dono: AsyncConnection) -> None:
    papel = uuid7()
    await dono.execute(
        text(
            "INSERT INTO roles (id, code, name, description)"
            " VALUES (:id, :codigo, 'Painel distrital (teste)', 'Dashboard do próprio distrito.')"
        ),
        {"id": papel, "codigo": PAINEL_DISTRITAL},
    )
    await dono.execute(
        text(
            "INSERT INTO role_permissions (role_id, permission_id, max_scope)"
            " SELECT :papel, id, 'distrito' FROM permissions WHERE code = 'dashboard:read'"
        ),
        {"papel": papel},
    )


def _resumo(
    id_: UUID, nome: str, tipo: str, distrito: str, cnes: str | None = None
) -> dict[str, Any]:
    return {"id": str(id_), "nome": nome, "cnes": cnes, "tipo": tipo, "distrito": distrito}


async def _inativar(dono: AsyncConnection, unidade: UUID) -> None:
    await dono.execute(
        text("UPDATE health_units SET status = 'inativa' WHERE id = :id"), {"id": unidade}
    )


async def _em_implantacao(dono: AsyncConnection, unidade: UUID) -> None:
    await dono.execute(
        text("UPDATE health_units SET status = 'em_implantacao' WHERE id = :id"), {"id": unidade}
    )


async def test_unidades_sem_servico_lista_as_unidades_nao_inativas_sem_nenhum_servico(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.1: anti join; unidade inativa fica de fora e serviço solto não conta para ninguém.

    "Ativas" segue o design (§ Consultas): `status <> 'inativa'`, então a unidade em implantação
    entra.
    """
    com_servico = await inserir_unidade(dono, "CAPS Espaço Azul", distrito="DS-I")
    await inserir_servico(dono, com_servico)
    sem_servico = await inserir_unidade(dono, "CAPS David Capistrano", cnes="2711907")
    usf = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    implantacao = await inserir_unidade(dono, "CAPS AD Novo", distrito="DS-III", tipo="CAPS_AD")
    await _em_implantacao(dono, implantacao)
    inativa = await inserir_unidade(dono, "CAPS Fechado", distrito="DS-III")
    await _inativar(dono, inativa)
    await inserir_servico(dono, None, nome="Sala de Vacinação do Shopping", tipo="SALA_VACINA")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(UNIDADES_SEM_SERVICO, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    assert resposta.json() == {
        "itens": [
            _resumo(
                sem_servico,
                "CAPS David Capistrano",
                "CAPS II",
                "Distrito Sanitário I",
                cnes="2711907",
            ),
            _resumo(implantacao, "CAPS AD Novo", "CAPS AD", "Distrito Sanitário III"),
            _resumo(usf, "USF Ibura", "Unidade de Saúde da Família", "Distrito Sanitário III"),
        ],
        "total": 3,
        "pagina": 1,
        "tamanho": 20,
    }


async def test_unidades_sem_servico_com_escopo_distrital_lista_so_as_do_distrito(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.5: o escopo de leitura do usuário (spec 003) limita a consulta."""
    await inserir_unidade(dono, "CAPS David Capistrano", distrito="DS-I")
    usf = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    await _criar_painel_distrital(dono)
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    await dono.commit()
    tecnico = await logado(sessoes, (PAINEL_DISTRITAL, ("distrito", str(ds3))))

    resposta = await cliente.get(UNIDADES_SEM_SERVICO, headers=bearer(app, tecnico))

    assert resposta.status_code == 200
    assert resposta.json()["itens"] == [
        _resumo(usf, "USF Ibura", "Unidade de Saúde da Família", "Distrito Sanitário III")
    ]
    assert resposta.json()["total"] == 1


async def test_unidades_sem_servico_filtra_por_distrito_e_por_tipo(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.7: filtro por distrito e por tipo de unidade, combináveis."""
    await inserir_unidade(dono, "CAPS David Capistrano", distrito="DS-I")
    usf_ds1 = await inserir_unidade(dono, "USF Coque", distrito="DS-I", tipo="USF")
    caps_ds3 = await inserir_unidade(dono, "CAPS Galdino Loreto", distrito="DS-III")
    usf_ds3 = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    usf = await id_pelo_codigo(sessoes, "tipo_unidade", "USF")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    async def ids(**filtros: int) -> list[str]:
        resposta = await cliente.get(
            UNIDADES_SEM_SERVICO, params=filtros, headers=bearer(app, gestor)
        )
        assert resposta.status_code == 200
        return [item["id"] for item in resposta.json()["itens"]]

    assert await ids(distrito=ds3) == [str(caps_ds3), str(usf_ds3)]
    assert await ids(tipo=usf) == [str(usf_ds1), str(usf_ds3)]
    assert await ids(distrito=ds3, tipo=usf) == [str(usf_ds3)]


# Testes negativos de segurança das rotas (steering/testing.md): cada rota tem os seus, com o
# corpo comum nas funções abaixo.


async def _sem_token_responde_401(cliente: httpx.AsyncClient, rota: str) -> None:
    resposta = await cliente.get(rota)

    assert resposta.status_code == 401
    assert resposta.headers["content-type"] == "application/problem+json"


async def _sem_dashboard_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, rota: str
) -> None:
    # AUDITOR tem escopo global, mas não tem `dashboard:read` (matriz da 0003).
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(rota, headers=bearer(app, auditor))

    assert resposta.status_code == 403
    assert resposta.headers["content-type"] == "application/problem+json"


async def _referencia_inexistente_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, rota: str
) -> None:
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(
        rota, params={"distrito": INEXISTENTE, "tipo": INEXISTENTE}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 422
    assert resposta.headers["content-type"] == "application/problem+json"
    assert resposta.json()["errors"] == [
        {"campo": "distrito", "mensagem": "Distrito inexistente."},
        {"campo": "tipo", "mensagem": "Tipo de unidade inexistente."},
    ]


# Formato errado (011/R2.9): não é inteiro, fora do intervalo do id (`smallint`) ou da página.
MAL_FORMADOS = [
    ({"distrito": "DS-III"}, "distrito"),
    ({"tipo": "0"}, "tipo"),
    ({"distrito": "40000"}, "distrito"),
    ({"pagina": "0"}, "pagina"),
    ({"tamanho": "101"}, "tamanho"),
]


async def _filtro_mal_formado_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    rota: str,
    params: dict[str, str],
    campo: str,
) -> None:
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(rota, params=params, headers=bearer(app, gestor))

    assert resposta.status_code == 422
    assert [erro["campo"] for erro in resposta.json()["errors"]] == [campo]


async def test_unidades_sem_servico_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """011/R2.8; 003/R4.1: rota protegida."""
    await _sem_token_responde_401(cliente, UNIDADES_SEM_SERVICO)


async def test_unidades_sem_servico_sem_dashboard_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.8"""
    await _sem_dashboard_read_responde_403(app, cliente, sessoes, UNIDADES_SEM_SERVICO)


async def test_unidades_sem_servico_com_distrito_ou_tipo_inexistente_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.9: distrito ou tipo que não existe nas referências (design: conferido pela
    application antes da consulta)."""
    await _referencia_inexistente_responde_422(app, cliente, sessoes, UNIDADES_SEM_SERVICO)


@pytest.mark.parametrize(("params", "campo"), MAL_FORMADOS)
async def test_unidades_sem_servico_com_filtro_mal_formado_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    params: dict[str, str],
    campo: str,
) -> None:
    """011/R2.9: formato inválido vem do schema da rota."""
    await _filtro_mal_formado_responde_422(
        app, cliente, sessoes, UNIDADES_SEM_SERVICO, params, campo
    )


async def test_unidades_sem_servico_pagina_o_resultado(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.1; design § Rotas: `PaginaOut` com o total da consulta inteira, também numa página
    depois da última."""
    await inserir_unidade(dono, "CAPS A", distrito="DS-I")
    segunda = await inserir_unidade(dono, "CAPS B", distrito="DS-I")
    await inserir_unidade(dono, "CAPS C", distrito="DS-I")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    async def pagina(numero: int) -> dict[str, Any]:
        resposta = await cliente.get(
            UNIDADES_SEM_SERVICO,
            params={"pagina": numero, "tamanho": 1},
            headers=bearer(app, gestor),
        )
        assert resposta.status_code == 200
        corpo: dict[str, Any] = resposta.json()
        return corpo

    assert await pagina(2) == {
        "itens": [_resumo(segunda, "CAPS B", "CAPS II", "Distrito Sanitário I")],
        "total": 3,
        "pagina": 2,
        "tamanho": 1,
    }
    assert await pagina(9) == {"itens": [], "total": 3, "pagina": 9, "tamanho": 1}


def _conciliacao(
    situacao: str,
    unidade: tuple[UUID, str, str] | None = None,
    equipamento: tuple[UUID, str, str] | None = None,
) -> dict[str, Any]:
    """Item esperado da conciliação: `unidade` = (id, nome, distrito); `equipamento` = (id, nome,
    tipo)."""
    unidade_id, unidade_nome, distrito = unidade or (None, None, None)
    equipamento_id, equipamento_nome, equipamento_tipo = equipamento or (None, None, None)
    return {
        "unidade_id": str(unidade_id) if unidade_id else None,
        "unidade_nome": unidade_nome,
        "distrito": distrito,
        "equipamento_id": str(equipamento_id) if equipamento_id else None,
        "equipamento_nome": equipamento_nome,
        "equipamento_tipo": equipamento_tipo,
        "situacao": situacao,
    }


async def test_conciliacao_lista_pares_unidades_sem_equipamento_e_equipamentos_sem_unidade(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.2, R2.6: full outer join; com escopo global, o equipamento sem unidade aparece."""
    caps = await inserir_unidade(dono, "CAPS David Capistrano", distrito="DS-I")
    lessa = await inserir_unidade(
        dono, "Policlínica Lessa de Andrade", distrito="DS-I", tipo="POLICLINICA"
    )
    maternidade = await inserir_equipamento(dono, lessa, nome="Maternidade Bandeira Filho")
    policlinica = await inserir_equipamento(
        dono, lessa, nome="Policlínica Lessa de Andrade", tipo="POLICLINICA"
    )
    usf = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    samu = await inserir_equipamento(dono, None, nome="UTI móvel SAMU 01", tipo="UTI_MOVEL")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(CONCILIACAO, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    ds1, ds3 = "Distrito Sanitário I", "Distrito Sanitário III"
    lessa_ = (lessa, "Policlínica Lessa de Andrade", ds1)
    assert resposta.json() == {
        "itens": [
            _conciliacao("unidade_sem_equipamento", (caps, "CAPS David Capistrano", ds1)),
            _conciliacao("par", lessa_, (maternidade, "Maternidade Bandeira Filho", "Maternidade")),
            _conciliacao(
                "par", lessa_, (policlinica, "Policlínica Lessa de Andrade", "Policlínica")
            ),
            _conciliacao("unidade_sem_equipamento", (usf, "USF Ibura", ds3)),
            _conciliacao(
                "equipamento_sem_unidade",
                equipamento=(samu, "UTI móvel SAMU 01", "UTI móvel"),
            ),
        ],
        "total": 5,
        "pagina": 1,
        "tamanho": 20,
    }


async def test_conciliacao_com_escopo_distrital_nao_mostra_equipamento_de_fora_nem_sem_unidade(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.5, R2.6: os dois lados são filtrados antes da junção; o equipamento de uma unidade
    de outro distrito não volta como "sem unidade", e o sem unidade exige escopo global."""
    lessa = await inserir_unidade(
        dono, "Policlínica Lessa de Andrade", distrito="DS-I", tipo="POLICLINICA"
    )
    await inserir_equipamento(dono, lessa, nome="Maternidade Bandeira Filho")
    usf = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    barros_lima = await inserir_unidade(
        dono, "Policlínica Barros Lima", distrito="DS-III", tipo="POLICLINICA"
    )
    policlinica = await inserir_equipamento(
        dono, barros_lima, nome="Policlínica Barros Lima", tipo="POLICLINICA"
    )
    await inserir_equipamento(dono, None, nome="UTI móvel SAMU 01", tipo="UTI_MOVEL")
    await _criar_painel_distrital(dono)
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    await dono.commit()
    tecnico = await logado(sessoes, (PAINEL_DISTRITAL, ("distrito", str(ds3))))

    resposta = await cliente.get(CONCILIACAO, headers=bearer(app, tecnico))

    assert resposta.status_code == 200
    ds3_ = "Distrito Sanitário III"
    assert resposta.json()["itens"] == [
        _conciliacao(
            "par",
            (barros_lima, "Policlínica Barros Lima", ds3_),
            (policlinica, "Policlínica Barros Lima", "Policlínica"),
        ),
        _conciliacao("unidade_sem_equipamento", (usf, "USF Ibura", ds3_)),
    ]
    assert resposta.json()["total"] == 2


async def test_conciliacao_com_filtro_nao_mostra_equipamento_sem_unidade(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.6, R2.7: mesmo com escopo global, o equipamento sem unidade não tem distrito nem
    tipo de unidade, então nenhum filtro o seleciona (design § Consultas)."""
    caps = await inserir_unidade(dono, "CAPS David Capistrano", distrito="DS-I")
    usf = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    await inserir_equipamento(dono, None, nome="UTI móvel SAMU 01", tipo="UTI_MOVEL")
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    tipo_usf = await id_pelo_codigo(sessoes, "tipo_unidade", "USF")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    async def itens(**filtros: int) -> list[dict[str, Any]]:
        resposta = await cliente.get(CONCILIACAO, params=filtros, headers=bearer(app, gestor))
        assert resposta.status_code == 200
        itens: list[dict[str, Any]] = resposta.json()["itens"]
        return itens

    ds1_, ds3_ = "Distrito Sanitário I", "Distrito Sanitário III"
    assert await itens(distrito=ds1) == [
        _conciliacao("unidade_sem_equipamento", (caps, "CAPS David Capistrano", ds1_))
    ]
    assert await itens(tipo=tipo_usf) == [
        _conciliacao("unidade_sem_equipamento", (usf, "USF Ibura", ds3_))
    ]


async def test_conciliacao_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """011/R2.8; 003/R4.1: rota protegida."""
    await _sem_token_responde_401(cliente, CONCILIACAO)


async def test_conciliacao_sem_dashboard_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.8"""
    await _sem_dashboard_read_responde_403(app, cliente, sessoes, CONCILIACAO)


async def test_conciliacao_com_distrito_ou_tipo_inexistente_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.9: distrito ou tipo que não existe nas referências."""
    await _referencia_inexistente_responde_422(app, cliente, sessoes, CONCILIACAO)


@pytest.mark.parametrize(("params", "campo"), MAL_FORMADOS)
async def test_conciliacao_com_filtro_mal_formado_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    params: dict[str, str],
    campo: str,
) -> None:
    """011/R2.9: formato inválido vem do schema da rota."""
    await _filtro_mal_formado_responde_422(app, cliente, sessoes, CONCILIACAO, params, campo)


DISTRITOS_CNES = "/api/v1/dashboard/consultas/distritos-cnes-acima-da-media"


async def _semear_cnes_por_distrito(dono: AsyncConnection) -> None:
    """DS-I: 3 de 4 sem CNES (75%); DS-II: 0 de 2 (0%); DS-III: 2 de 2 (100%). Rede: 5 de 8
    (62,5%)."""
    await inserir_unidade(dono, "CAPS A", distrito="DS-I")
    await inserir_unidade(dono, "CAPS B", distrito="DS-I")
    await inserir_unidade(dono, "CAPS C", distrito="DS-I")
    await inserir_unidade(dono, "CAPS D", distrito="DS-I", cnes="0000001")
    await inserir_unidade(dono, "CAPS E", distrito="DS-II", cnes="0000002")
    await inserir_unidade(dono, "CAPS F", distrito="DS-II", cnes="0000003")
    await inserir_unidade(dono, "CAPS G", distrito="DS-III")
    await inserir_unidade(dono, "CAPS H", distrito="DS-III")


def _distrito(id_: int, nome: str, total: int, sem_cnes: int, percentual: float) -> dict[str, Any]:
    return {
        "id": id_,
        "nome": nome,
        "total_unidades": total,
        "sem_cnes": sem_cnes,
        "percentual": percentual,
    }


async def test_distritos_cnes_lista_os_distritos_acima_do_percentual_da_rede(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.3: subconsulta escalar no HAVING; só os distritos com percentual de unidades sem
    CNES maior que o da rede, do maior para o menor percentual."""
    await _semear_cnes_por_distrito(dono)
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(DISTRITOS_CNES, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    assert resposta.json() == {
        "percentual_rede": 62.5,
        "distritos": [
            _distrito(ds3, "Distrito Sanitário III", 2, 2, 100.0),
            _distrito(ds1, "Distrito Sanitário I", 4, 3, 75.0),
        ],
    }


async def test_distritos_cnes_com_escopo_distrital_a_rede_e_so_o_escopo(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.3, R2.5: com escopo em DS-I e DS-II, a rede são as 6 unidades deles (3 sem CNES,
    50%), não as 8 da rede inteira (62,5%); DS-III, fora do escopo, não aparece."""
    await _semear_cnes_por_distrito(dono)
    await _criar_painel_distrital(dono)
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    ds2 = await id_pelo_codigo(sessoes, "distrito", "DS-II")
    await dono.commit()
    tecnico = await logado(
        sessoes,
        (PAINEL_DISTRITAL, ("distrito", str(ds1))),
        (PAINEL_DISTRITAL, ("distrito", str(ds2))),
    )

    resposta = await cliente.get(DISTRITOS_CNES, headers=bearer(app, tecnico))

    assert resposta.status_code == 200
    assert resposta.json() == {
        "percentual_rede": 50.0,
        "distritos": [_distrito(ds1, "Distrito Sanitário I", 4, 3, 75.0)],
    }


async def test_distritos_cnes_com_escopo_de_um_distrito_nao_lista_nenhum(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.5: com um distrito só, a rede é o próprio distrito, que não fica acima de si
    mesmo; na rede inteira, DS-I (75%) estaria acima de 62,5%."""
    await _semear_cnes_por_distrito(dono)
    await _criar_painel_distrital(dono)
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    await dono.commit()
    tecnico = await logado(sessoes, (PAINEL_DISTRITAL, ("distrito", str(ds1))))

    resposta = await cliente.get(DISTRITOS_CNES, headers=bearer(app, tecnico))

    assert resposta.status_code == 200
    assert resposta.json() == {"percentual_rede": 75.0, "distritos": []}


async def test_distritos_cnes_sem_unidades_no_escopo_nao_tem_percentual_da_rede(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.3: sem unidade nenhuma, não há percentual da rede a comparar."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(DISTRITOS_CNES, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    assert resposta.json() == {"percentual_rede": None, "distritos": []}


async def test_distritos_cnes_filtra_por_tipo_na_rede_e_nos_distritos(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.7: o filtro de tipo vale para os distritos e para a rede. Só USF: DS-I 0 de 1,
    DS-II 1 de 2, DS-III 1 de 1; rede 2 de 4 (50%). Os CAPS sem CNES não contam."""
    await _semear_cnes_por_distrito(dono)
    await inserir_unidade(dono, "USF Coque", distrito="DS-I", tipo="USF", cnes="0000004")
    await inserir_unidade(dono, "USF Iputinga", distrito="DS-II", tipo="USF")
    await inserir_unidade(dono, "USF Caxangá", distrito="DS-II", tipo="USF", cnes="0000005")
    await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    usf = await id_pelo_codigo(sessoes, "tipo_unidade", "USF")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(DISTRITOS_CNES, params={"tipo": usf}, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    assert resposta.json() == {
        "percentual_rede": 50.0,
        "distritos": [_distrito(ds3, "Distrito Sanitário III", 1, 1, 100.0)],
    }


async def test_distritos_cnes_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """011/R2.8; 003/R4.1: rota protegida."""
    await _sem_token_responde_401(cliente, DISTRITOS_CNES)


async def test_distritos_cnes_sem_dashboard_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.8"""
    await _sem_dashboard_read_responde_403(app, cliente, sessoes, DISTRITOS_CNES)


async def test_distritos_cnes_com_tipo_inexistente_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.9: tipo que não existe nas referências. A consulta não tem filtro de distrito
    (design § Rotas: só `tipo?`)."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(
        DISTRITOS_CNES, params={"tipo": INEXISTENTE}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 422
    assert resposta.headers["content-type"] == "application/problem+json"
    assert resposta.json()["errors"] == [
        {"campo": "tipo", "mensagem": "Tipo de unidade inexistente."}
    ]


@pytest.mark.parametrize("valor", ["USF", "0", "40000"])
async def test_distritos_cnes_com_tipo_mal_formado_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, valor: str
) -> None:
    """011/R2.9: formato inválido vem do schema da rota."""
    await _filtro_mal_formado_responde_422(
        app, cliente, sessoes, DISTRITOS_CNES, {"tipo": valor}, "tipo"
    )


FORA_CNES = "/api/v1/dashboard/consultas/unidades-servico-fora-cnes"


async def _semear_servicos_fora_cnes(dono: AsyncConnection) -> dict[str, UUID]:
    """CAPS A (DS-I): 1 serviço fora e 1 no CNES; CAPS B (DS-I): 2 fora; CAPS C (DS-I): só no
    CNES; USF Ibura (DS-III): 1 fora; CAPS D (DS-III): sem serviço; e um serviço solto fora do
    CNES."""
    caps_a = await inserir_unidade(dono, "CAPS A", distrito="DS-I", cnes="0000001")
    await inserir_servico(dono, caps_a, nome="Farmácia do CAPS A")
    await inserir_servico(
        dono, caps_a, nome="Espaço Mãe Coruja", tipo="ESPACO_MAE_CORUJA", no_cnes=True
    )
    caps_b = await inserir_unidade(dono, "CAPS B", distrito="DS-I")
    await inserir_servico(dono, caps_b, nome="Farmácia do CAPS B")
    await inserir_servico(dono, caps_b, nome="Farmácia da Família", tipo="FARMACIA_FAMILIA")
    caps_c = await inserir_unidade(dono, "CAPS C", distrito="DS-I")
    await inserir_servico(dono, caps_c, nome="Farmácia do CAPS C", no_cnes=True)
    usf = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    await inserir_servico(dono, usf, nome="Sala de vacina da USF", tipo="SALA_VACINA")
    await inserir_unidade(dono, "CAPS D", distrito="DS-III")
    await inserir_servico(dono, None, nome="Sala de Vacinação do Shopping", tipo="SALA_VACINA")
    return {"caps_a": caps_a, "caps_b": caps_b, "usf": usf}


def _fora_cnes(
    id_: UUID, nome: str, tipo: str, distrito: str, servicos: int, cnes: str | None = None
) -> dict[str, Any]:
    return {**_resumo(id_, nome, tipo, distrito, cnes=cnes), "servicos_fora_cnes": servicos}


async def test_fora_cnes_lista_as_unidades_com_servico_fora_do_cnes_e_a_contagem(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.4: subconsulta EXISTS; só unidades com ao menos um serviço fora do CNES, com a
    quantidade desses serviços. Serviço solto não é de unidade nenhuma."""
    unidades = await _semear_servicos_fora_cnes(dono)
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(FORA_CNES, headers=bearer(app, gestor))

    assert resposta.status_code == 200
    ds1, ds3 = "Distrito Sanitário I", "Distrito Sanitário III"
    assert resposta.json() == {
        "itens": [
            _fora_cnes(unidades["caps_a"], "CAPS A", "CAPS II", ds1, 1, cnes="0000001"),
            _fora_cnes(unidades["caps_b"], "CAPS B", "CAPS II", ds1, 2),
            _fora_cnes(unidades["usf"], "USF Ibura", "Unidade de Saúde da Família", ds3, 1),
        ],
        "total": 3,
        "pagina": 1,
        "tamanho": 20,
    }


async def test_fora_cnes_com_escopo_distrital_lista_so_as_do_distrito(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.5: o escopo de leitura do usuário limita a consulta."""
    unidades = await _semear_servicos_fora_cnes(dono)
    await _criar_painel_distrital(dono)
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    await dono.commit()
    tecnico = await logado(sessoes, (PAINEL_DISTRITAL, ("distrito", str(ds3))))

    resposta = await cliente.get(FORA_CNES, headers=bearer(app, tecnico))

    assert resposta.status_code == 200
    assert resposta.json()["itens"] == [
        _fora_cnes(
            unidades["usf"], "USF Ibura", "Unidade de Saúde da Família", "Distrito Sanitário III", 1
        )
    ]
    assert resposta.json()["total"] == 1


async def test_fora_cnes_filtra_por_distrito_e_por_tipo(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.7: filtro por distrito e por tipo de unidade."""
    unidades = await _semear_servicos_fora_cnes(dono)
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    usf = await id_pelo_codigo(sessoes, "tipo_unidade", "USF")
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    async def ids(**filtros: int) -> list[str]:
        resposta = await cliente.get(FORA_CNES, params=filtros, headers=bearer(app, gestor))
        assert resposta.status_code == 200
        return [item["id"] for item in resposta.json()["itens"]]

    assert await ids(distrito=ds1) == [str(unidades["caps_a"]), str(unidades["caps_b"])]
    assert await ids(tipo=usf) == [str(unidades["usf"])]
    assert await ids(distrito=ds1, tipo=usf) == []


async def test_fora_cnes_pagina_o_resultado(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    dono: AsyncConnection,
) -> None:
    """011/R2.4; design § Rotas: `PaginaOut` com o total da consulta inteira."""
    unidades = await _semear_servicos_fora_cnes(dono)
    await dono.commit()
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))

    resposta = await cliente.get(
        FORA_CNES, params={"pagina": 2, "tamanho": 1}, headers=bearer(app, gestor)
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "itens": [_fora_cnes(unidades["caps_b"], "CAPS B", "CAPS II", "Distrito Sanitário I", 2)],
        "total": 3,
        "pagina": 2,
        "tamanho": 1,
    }


async def test_fora_cnes_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """011/R2.8; 003/R4.1: rota protegida."""
    await _sem_token_responde_401(cliente, FORA_CNES)


async def test_fora_cnes_sem_dashboard_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.8"""
    await _sem_dashboard_read_responde_403(app, cliente, sessoes, FORA_CNES)


async def test_fora_cnes_com_distrito_ou_tipo_inexistente_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R2.9: distrito ou tipo que não existe nas referências."""
    await _referencia_inexistente_responde_422(app, cliente, sessoes, FORA_CNES)


@pytest.mark.parametrize(("params", "campo"), MAL_FORMADOS)
async def test_fora_cnes_com_filtro_mal_formado_responde_422(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    params: dict[str, str],
    campo: str,
) -> None:
    """011/R2.9: formato inválido vem do schema da rota."""
    await _filtro_mal_formado_responde_422(app, cliente, sessoes, FORA_CNES, params, campo)
