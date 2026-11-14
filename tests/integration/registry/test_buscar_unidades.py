"""`GET /api/v1/unidades` e `GET /api/v1/unidades/{id}`: listar, buscar, filtrar, ordenar e
detalhar unidades no escopo de leitura do usuário (006/T4).

Design da 006 § Rotas e § Busca. Cada teste semeia o próprio cadastro direto no banco, pelo dono,
e confere a resposta da API. O desempenho da busca (R2.7) é da 006/T10.
"""

from collections.abc import AsyncIterator
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

LISTA = "/api/v1/unidades"


def _detalhe(unidade: UUID) -> str:
    return f"{LISTA}/{unidade}"


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
    """Conexão do dono do banco, para semear o cadastro e papéis de teste. O teste confirma com
    `commit()` antes de chamar a API."""
    engine = motor(banco.url_dono)
    async with engine.connect() as conexao:
        yield conexao
    await engine.dispose()


async def _atualizar(dono: AsyncConnection, unidade: UUID, atribuicoes: str) -> None:
    await dono.execute(
        text(f"UPDATE health_units SET {atribuicoes} WHERE id = :id"),  # noqa: S608 (texto fixo)
        {"id": unidade},
    )


# Na matriz semeada (0003), todo papel com `unidade:read` o tem com escopo global. Para exercitar
# o escopo de leitura (R2.6), o teste cria um papel com `unidade:read` limitado ao distrito.
LEITOR_DISTRITAL = "LEITOR_DISTRITAL_TESTE"


async def _criar_leitor_distrital(dono: AsyncConnection) -> None:
    papel = uuid7()
    await dono.execute(
        text(
            "INSERT INTO roles (id, code, name, description)"
            " VALUES (:id, :codigo, 'Leitor distrital (teste)', 'Unidades do próprio distrito.')"
        ),
        {"id": papel, "codigo": LEITOR_DISTRITAL},
    )
    await dono.execute(
        text(
            "INSERT INTO role_permissions (role_id, permission_id, max_scope)"
            " SELECT :papel, id, 'distrito' FROM permissions WHERE code = 'unidade:read'"
        ),
        {"papel": papel},
    )


async def _cabecalhos(app: FastAPI, sessoes: Sessoes) -> dict[str, str]:
    """Token de um usuário com `unidade:read` global (todo papel de negócio o tem)."""
    return bearer(app, await logado(sessoes, ("AUDITOR", GLOBAL)))


def _nomes(corpo: dict[str, object]) -> list[str]:
    itens = corpo["itens"]
    assert isinstance(itens, list)
    return [item["nome"] for item in itens]


async def test_lista_pagina_com_20_por_padrao_e_total(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.1: paginação com 20 itens por padrão e o total da listagem inteira."""
    for numero in range(25):
        await inserir_unidade(dono, f"USF {numero:02d}", distrito="DS-III", tipo="USF")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)

    primeira = await cliente.get(LISTA, headers=cabecalhos)
    segunda = await cliente.get(LISTA, params={"pagina": 2}, headers=cabecalhos)
    depois_da_ultima = await cliente.get(LISTA, params={"pagina": 9}, headers=cabecalhos)

    assert primeira.status_code == 200
    corpo = primeira.json()
    assert (corpo["total"], corpo["pagina"], corpo["tamanho"]) == (25, 1, 20)
    assert _nomes(corpo) == [f"USF {numero:02d}" for numero in range(20)]
    assert _nomes(segunda.json()) == [f"USF {numero:02d}" for numero in range(20, 25)]
    assert depois_da_ultima.json() | {"itens": None} == {
        "itens": None,
        "total": 25,
        "pagina": 9,
        "tamanho": 20,
    }
    assert depois_da_ultima.json()["itens"] == []


async def test_item_da_lista_nao_traz_o_gestor_nem_o_telefone_e_o_detalhe_traz(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """steering/security.md § LGPD (na dúvida, o mais restritivo): o item da listagem é um resumo
    sem `nome_gestor` nem `telefone`; o detalhe da unidade que a pessoa abriu continua com os
    dois (006/R2.1, R2.5; pergunta da 006/T4 resolvida na revisão)."""
    unidade = await inserir_unidade(dono, "CAPS Espaço Azul", cnes="2711907")
    await _atualizar(dono, unidade, "manager_name = 'Ana Souza', phone = '8133551234'")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)

    lista = await cliente.get(LISTA, headers=cabecalhos)
    detalhe = await cliente.get(_detalhe(unidade), headers=cabecalhos)

    [item] = lista.json()["itens"]
    assert item["id"] == str(unidade)
    assert "nome_gestor" not in item
    assert "telefone" not in item
    corpo = detalhe.json()
    assert (corpo["nome_gestor"], corpo["telefone"]) == ("Ana Souza", "8133551234")


async def test_tamanho_vai_ate_100(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R2.1: no máximo 100 itens por página; acima disso, 422."""
    cabecalhos = await _cabecalhos(app, sessoes)

    cem = await cliente.get(LISTA, params={"tamanho": 100}, headers=cabecalhos)
    acima = await cliente.get(LISTA, params={"tamanho": 101}, headers=cabecalhos)

    assert cem.status_code == 200
    assert cem.json()["tamanho"] == 100
    assert acima.status_code == 422


async def test_busca_por_nome_ignora_acento_caixa_e_espacos(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.2: o texto livre acha o trecho do nome sem acento, caixa nem espaços repetidos."""
    await inserir_unidade(dono, "CAPS Espaço Azul")
    await inserir_unidade(dono, "Policlínica Espaçosa", tipo="POLICLINICA")
    await inserir_unidade(dono, "CAPS Galdino Loreto")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)

    resposta = await cliente.get(LISTA, params={"q": "  ESPACO  "}, headers=cabecalhos)

    assert resposta.status_code == 200
    assert sorted(_nomes(resposta.json())) == ["CAPS Espaço Azul", "Policlínica Espaçosa"]
    assert resposta.json()["total"] == 2
    trecho = await cliente.get(LISTA, params={"q": "galdino   lorETO"}, headers=cabecalhos)
    assert _nomes(trecho.json()) == ["CAPS Galdino Loreto"]


async def test_busca_por_cnes(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.2: o texto livre também acha a unidade pelo CNES, inteiro ou por trecho."""
    await inserir_unidade(dono, "CAPS Espaço Azul", cnes="2711907")
    await inserir_unidade(dono, "CAPS Galdino Loreto", cnes="2345678")
    await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)

    inteiro = await cliente.get(LISTA, params={"q": "2711907"}, headers=cabecalhos)
    trecho = await cliente.get(LISTA, params={"q": "4567"}, headers=cabecalhos)

    assert _nomes(inteiro.json()) == ["CAPS Espaço Azul"]
    assert _nomes(trecho.json()) == ["CAPS Galdino Loreto"]


async def test_curinga_do_like_no_texto_e_literal(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.2: `%` e `_` no texto livre são procurados como caracteres, não casam com tudo."""
    await inserir_unidade(dono, "CAPS Espaço Azul")
    await inserir_unidade(dono, "USF 100% Ibura", distrito="DS-III", tipo="USF")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)

    porcento = await cliente.get(LISTA, params={"q": "%"}, headers=cabecalhos)
    sublinhado = await cliente.get(LISTA, params={"q": "_"}, headers=cabecalhos)

    assert _nomes(porcento.json()) == ["USF 100% Ibura"]
    assert _nomes(sublinhado.json()) == []


async def test_filtros_combinados(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.3: tipo, área técnica, distrito, status e `com_pendencias`, cada um e combinados."""
    caps_ds1 = await inserir_unidade(dono, "CAPS DS1 pendente")
    await _atualizar(dono, caps_ds1, "pending_issues = 2")
    await inserir_unidade(dono, "CAPS DS1 sem pendencia")
    caps_ds3 = await inserir_unidade(dono, "CAPS DS3 inativo", distrito="DS-III")
    await _atualizar(dono, caps_ds3, "status = 'inativa', pending_issues = 1")
    await inserir_unidade(dono, "USF DS3", distrito="DS-III", tipo="USF")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)
    ds1 = await id_pelo_codigo(sessoes, "distrito", "DS-I")
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    caps = await id_pelo_codigo(sessoes, "tipo_unidade", "CAPS_II")
    usf = await id_pelo_codigo(sessoes, "tipo_unidade", "USF")
    saude_mental = await id_pelo_codigo(sessoes, "area", "SAUDE_MENTAL")

    async def nomes(**filtros: int | str) -> list[str]:
        resposta = await cliente.get(LISTA, params=filtros, headers=cabecalhos)
        assert resposta.status_code == 200, resposta.text
        return _nomes(resposta.json())

    assert await nomes(tipo=usf) == ["USF DS3"]
    assert await nomes(area=saude_mental) == [
        "CAPS DS1 pendente",
        "CAPS DS1 sem pendencia",
        "CAPS DS3 inativo",
    ]
    assert await nomes(distrito=ds3) == ["CAPS DS3 inativo", "USF DS3"]
    assert await nomes(status="inativa") == ["CAPS DS3 inativo"]
    assert await nomes(com_pendencias="true") == ["CAPS DS1 pendente", "CAPS DS3 inativo"]
    assert await nomes(com_pendencias="false") == ["CAPS DS1 sem pendencia", "USF DS3"]
    assert await nomes(tipo=caps, distrito=ds1, com_pendencias="true") == ["CAPS DS1 pendente"]
    assert await nomes(area=saude_mental, status="ativa", distrito=ds3) == []


async def test_filtro_invalido_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R2.3, R2.4: status, ordenação ou id de referência fora do formato dão 422."""
    cabecalhos = await _cabecalhos(app, sessoes)

    for params in ({"status": "fechada"}, {"ordenar": "cnes"}, {"distrito": 0}, {"tipo": "x"}):
        resposta = await cliente.get(LISTA, params=params, headers=cabecalhos)
        assert resposta.status_code == 422, params


async def test_ordena_por_nome_distrito_ou_atualizacao(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.4: por nome (padrão), por distrito (e nome dentro dele) ou pela data de atualização,
    a mais recente primeiro."""
    beta = await inserir_unidade(dono, "Beta", distrito="DS-I")
    alfa = await inserir_unidade(dono, "Alfa", distrito="DS-III")
    gama = await inserir_unidade(dono, "Gama", distrito="DS-I")
    await _atualizar(dono, alfa, "updated_at = now() - interval '2 days'")
    await _atualizar(dono, beta, "updated_at = now() - interval '1 day'")
    await _atualizar(dono, gama, "updated_at = now() - interval '3 days'")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)

    async def nomes(**params: str) -> list[str]:
        return _nomes((await cliente.get(LISTA, params=params, headers=cabecalhos)).json())

    assert await nomes() == ["Alfa", "Beta", "Gama"]
    assert await nomes(ordenar="nome") == ["Alfa", "Beta", "Gama"]
    assert await nomes(ordenar="distrito") == ["Beta", "Gama", "Alfa"]
    assert await nomes(ordenar="atualizacao") == ["Beta", "Alfa", "Gama"]


async def test_com_texto_livre_ordena_por_semelhanca_se_nao_pedir_ordem(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.2, R2.4 (design § Busca): com `q` e sem `ordenar`, a mais parecida vem primeiro;
    com `ordenar`, vale a ordem pedida."""
    await inserir_unidade(dono, "Academia da Cidade Ibura de Baixo", tipo="USF")
    await inserir_unidade(dono, "Ibura", tipo="USF", distrito="DS-III")
    await dono.commit()
    cabecalhos = await _cabecalhos(app, sessoes)

    relevancia = await cliente.get(LISTA, params={"q": "ibura"}, headers=cabecalhos)
    por_nome = await cliente.get(
        LISTA, params={"q": "ibura", "ordenar": "nome"}, headers=cabecalhos
    )

    assert _nomes(relevancia.json()) == ["Ibura", "Academia da Cidade Ibura de Baixo"]
    assert _nomes(por_nome.json()) == ["Academia da Cidade Ibura de Baixo", "Ibura"]


async def test_lista_so_o_escopo_de_leitura(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.6, 003/R4.4: a listagem traz só as unidades no escopo de leitura do usuário, e o
    total conta só elas."""
    await _criar_leitor_distrital(dono)
    await inserir_unidade(dono, "CAPS DS1")
    await inserir_unidade(dono, "USF DS3", distrito="DS-III", tipo="USF")
    await dono.commit()
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    leitor = await logado(sessoes, (LEITOR_DISTRITAL, ("distrito", str(ds3))))

    resposta = await cliente.get(LISTA, headers=bearer(app, leitor))

    assert resposta.status_code == 200
    assert _nomes(resposta.json()) == ["USF DS3"]
    assert resposta.json()["total"] == 1


async def test_detalhe_traz_equipamentos_e_servicos_vinculados(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.5: a unidade, com o `ETag` da versão, e os equipamentos e serviços dela; os de
    outra unidade, o equipamento sem unidade e o serviço solto ficam de fora."""
    unidade = await inserir_unidade(dono, "CAPS Espaço Azul", cnes="2711907")
    outra = await inserir_unidade(dono, "USF Ibura", distrito="DS-III", tipo="USF")
    equipamento = await inserir_equipamento(dono, unidade, nome="Policlínica Boa Vista")
    servico = await inserir_servico(
        dono, unidade, equipamento=equipamento, nome="Farmácia do CAPS", no_cnes=True
    )
    await inserir_equipamento(dono, outra, nome="Policlínica Torre")
    await inserir_servico(dono, outra, nome="Sala de vacina da USF")
    await inserir_equipamento(dono, None, nome="UTI móvel Norte", tipo="UTI_MOVEL")
    await inserir_servico(dono, None, nome="Sala de Vacinação do Shopping", tipo="SALA_VACINA")
    await dono.commit()
    farmacia = await id_pelo_codigo_servico(dono, "FARMACIA")

    resposta = await cliente.get(_detalhe(unidade), headers=await _cabecalhos(app, sessoes))

    assert resposta.status_code == 200
    assert resposta.headers["etag"] == '"1"'
    corpo = resposta.json()
    assert (corpo["id"], corpo["nome"], corpo["cnes"], corpo["versao"]) == (
        str(unidade),
        "CAPS Espaço Azul",
        "2711907",
        1,
    )
    assert corpo["equipamentos"] == [
        {
            "id": str(equipamento),
            "nome": "Policlínica Boa Vista",
            "cnes": None,
            "tipo_equipamento": "MATERNIDADE",
            "quantidade": 1,
            "status": "ativo",
        }
    ]
    assert corpo["servicos"] == [
        {
            "id": str(servico),
            "nome": "Farmácia do CAPS",
            "tipo_servico_id": farmacia,
            "equipamento_id": str(equipamento),
            "no_cnes": True,
            "status": "ativo",
        }
    ]


async def id_pelo_codigo_servico(dono: AsyncConnection, codigo: str) -> int:
    id_ = await dono.scalar(text("SELECT id FROM service_types WHERE code = :c"), {"c": codigo})
    assert id_ is not None
    return int(id_)


async def test_detalhe_sem_equipamento_nem_servico_traz_listas_vazias(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.5: unidade sem vínculo nenhum responde com as listas vazias."""
    unidade = await inserir_unidade(dono, "CAPS Galdino Loreto")
    await dono.commit()

    resposta = await cliente.get(_detalhe(unidade), headers=await _cabecalhos(app, sessoes))

    assert resposta.status_code == 200
    assert (resposta.json()["equipamentos"], resposta.json()["servicos"]) == ([], [])


async def test_detalhe_de_unidade_inexistente_responde_404(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R2.5, 003/R4.3: com permissão global, unidade que não existe dá 404."""
    resposta = await cliente.get(_detalhe(uuid7()), headers=await _cabecalhos(app, sessoes))

    assert resposta.status_code == 404


async def test_detalhe_fora_do_escopo_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, dono: AsyncConnection
) -> None:
    """006/R2.6, 003/R4.3: a unidade de outro distrito não é mostrada a quem lê só o seu."""
    await _criar_leitor_distrital(dono)
    fora = await inserir_unidade(dono, "CAPS DS1")
    dentro = await inserir_unidade(dono, "USF DS3", distrito="DS-III", tipo="USF")
    await dono.commit()
    ds3 = await id_pelo_codigo(sessoes, "distrito", "DS-III")
    leitor = bearer(app, await logado(sessoes, (LEITOR_DISTRITAL, ("distrito", str(ds3)))))

    assert (await cliente.get(_detalhe(dentro), headers=leitor)).status_code == 200
    assert (await cliente.get(_detalhe(fora), headers=leitor)).status_code == 403


async def test_sem_token_responde_401(cliente: httpx.AsyncClient) -> None:
    """003/R4.1: listagem e detalhe exigem login."""
    assert (await cliente.get(LISTA)).status_code == 401
    assert (await cliente.get(_detalhe(uuid7()))).status_code == 401


async def test_sem_unidade_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """006/R2.6, 003/R4.2: usuário sem `unidade:read` não lista nem detalha."""
    sem_papel = bearer(app, await logado(sessoes))

    assert (await cliente.get(LISTA, headers=sem_papel)).status_code == 403
    assert (await cliente.get(_detalhe(uuid7()), headers=sem_papel)).status_code == 403
