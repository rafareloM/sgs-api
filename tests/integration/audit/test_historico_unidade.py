"""`GET /api/v1/unidades/{id}/historico`: histórico da unidade pela `vw_unit_history` (011/T14).

Rota da 008/R1, adiantada pela 011 (R4.5); design da 011 § Rotas e § Consultas de
`audit/infrastructure/sql/`. Matriz da arquitetura-conceitual.md § 4: `auditoria:read` é global
para `AUDITOR` e `GESTOR_DADOS`, por área para `COORD_TECNICO`, por distrito para
`TECNICO_DISTRITAL` e por unidade para `GESTOR_UNIDADE`; `DIRETORIA` não tem.

As unidades e os eventos de equipamento e serviço entram como na 006: a unidade pela rota de
criação (que grava `unidade.criada`) ou direto no banco, e os eventos pelo `audit.registrar`, no
nível da unidade (006/R5.3).
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.main import create_app
from src.modules.audit.application.registrar import Ator, Entidade, Mudanca, registrar
from src.modules.audit.domain.entry import AuditEntry
from src.modules.audit.infrastructure.repository import SqlAuditStore
from tests.factories import make_settings
from tests.integration.acesso import GLOBAL, Sessoes, bearer, eventos, id_pelo_codigo, logado
from tests.integration.postgres import BancoDeTeste, motor


def _rota(unidade: UUID | str) -> str:
    return f"/api/v1/unidades/{unidade}/historico"


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
    """Sessões com o login da API (papel sgs_app), para preparar e conferir os dados."""
    engine = motor(banco.url_api)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _criar_unidade(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    nome: str,
    *,
    distrito: str = "DS-I",
    tipo: str = "CAPS_II",
) -> UUID:
    """Unidade criada pela rota da 006, por um `GESTOR_DADOS`: grava `unidade.criada`."""
    gestor = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    resposta = await cliente.post(
        "/api/v1/unidades",
        json={
            "nome": nome,
            "tipo_unidade_id": await id_pelo_codigo(sessoes, "tipo_unidade", tipo),
            "distrito_id": await id_pelo_codigo(sessoes, "distrito", distrito),
            "cep": "50010100",
            "endereco": "Rua do Sol, 150",
            "status": "ativa",
        },
        headers=bearer(app, gestor),
    )
    assert resposta.status_code == 201, resposta.text
    return UUID(resposta.json()["id"])


async def _registrar(
    sessoes: Sessoes,
    acao: str,
    ator: Ator,
    unidade: UUID | None,
    mudancas: Sequence[Mudanca] = (),
    metadados: dict[str, Any] | None = None,
    *,
    quando: datetime | None = None,
) -> AuditEntry:
    """Evento gravado pelo `audit.registrar` no nível da unidade, como a 006 faz (R5.3); com
    `quando`, nessa data e hora."""
    async with sessoes() as sessao, sessao.begin():
        return await registrar(
            SqlAuditStore(sessao),
            acao=acao,
            ator=ator,
            entidade=None if unidade is None else Entidade(tipo="unidade", id=str(unidade)),
            mudancas=mudancas,
            metadados=metadados,
            **({} if quando is None else {"agora": lambda: quando}),
        )


async def test_historico_traz_eventos_da_unidade_de_equipamentos_e_servicos_com_autor(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """011/R4.5, 011/R4.4, 008/R1.1: o histórico sai da view, com os eventos da unidade e os de
    seus equipamentos e serviços, cada um com data, autor, ação e {campo, de, para}, do mais
    recente ao mais antigo; eventos de outra unidade ficam de fora."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    usf = await _criar_unidade(app, cliente, sessoes, "USF Ibura", distrito="DS-VI", tipo="USF")
    autora_sessao = await logado(sessoes, ("GESTOR_DADOS", GLOBAL))
    autora = Ator(user_id=autora_sessao.user_id, papeis=("GESTOR_DADOS",))
    equipamento = await _registrar(
        sessoes,
        "unidade.equipamento_criado",
        autora,
        caps,
        [Mudanca("equipamento.nome", None, "Maternidade")],
        {"equipamento_id": "0197a000-0000-7000-8000-000000000001"},
    )
    servico = await _registrar(
        sessoes,
        "unidade.servico_criado",
        autora,
        caps,
        [Mudanca("servico.nome", None, "Farmácia do CAPS")],
        {"servico_id": "0197a000-0000-7000-8000-000000000002"},
    )
    # Sem autor (tarefa do sistema): continua no histórico, com o autor nulo.
    sistema = await _registrar(
        sessoes, "unidade.atualizada", Ator(), caps, [Mudanca("pendencias", 0, 1)]
    )
    await _registrar(sessoes, "unidade.atualizada", autora, usf, [Mudanca("phone", None, "81")])
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(_rota(caps), headers=bearer(app, auditor))

    assert resposta.status_code == 200, resposta.text
    pagina = resposta.json()
    assert {chave: pagina[chave] for chave in ("total", "pagina", "tamanho")} == {
        "total": 4,
        "pagina": 1,
        "tamanho": 20,
    }
    itens = pagina["itens"]
    assert [item["acao"] for item in itens] == [
        "unidade.atualizada",
        "unidade.servico_criado",
        "unidade.equipamento_criado",
        "unidade.criada",
    ]
    assert itens[0] == {
        "id": itens[0]["id"],
        "ocorrido_em": sistema.occurred_at.isoformat().replace("+00:00", "Z"),
        "acao": "unidade.atualizada",
        "autor_id": None,
        "autor_nome": None,
        "autor_papeis": [],
        "mudancas": [{"campo": "pendencias", "de": 0, "para": 1}],
        "metadados": {},
    }
    pela_autora = {
        "autor_id": str(autora_sessao.user_id),
        "autor_nome": "Maria Silva",
        "autor_papeis": ["GESTOR_DADOS"],
    }
    assert {k: v for k, v in itens[1].items() if k != "id"} == {
        "ocorrido_em": servico.occurred_at.isoformat().replace("+00:00", "Z"),
        "acao": "unidade.servico_criado",
        **pela_autora,
        "mudancas": [{"campo": "servico.nome", "de": None, "para": "Farmácia do CAPS"}],
        "metadados": {"servico_id": "0197a000-0000-7000-8000-000000000002"},
    }
    assert {k: v for k, v in itens[2].items() if k != "id"} == {
        "ocorrido_em": equipamento.occurred_at.isoformat().replace("+00:00", "Z"),
        "acao": "unidade.equipamento_criado",
        **pela_autora,
        "mudancas": [{"campo": "equipamento.nome", "de": None, "para": "Maternidade"}],
        "metadados": {"equipamento_id": "0197a000-0000-7000-8000-000000000001"},
    }
    # O evento da criação pela rota da 006: o autor é quem criou, e a lista tem o nome.
    criada = itens[3]
    assert criada["autor_nome"] == "Maria Silva"
    assert criada["autor_id"] is not None
    assert {"campo": "name", "de": None, "para": "CAPS Esperança"} in criada["mudancas"]


async def test_evento_gravado_pela_rota_leva_os_papeis_do_autor(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """008/R1.2, modelo-dados.md (`actor_roles`): o evento que a rota grava leva os códigos dos
    papéis vigentes de quem fez a ação, e o histórico os devolve em `autor_papeis` (011/T14,
    resolvido na revisão)."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(_rota(caps), headers=bearer(app, auditor))

    async with sessoes() as sessao:
        papeis = await sessao.scalar(
            text("SELECT actor_roles FROM audit_log WHERE action = 'unidade.criada'")
        )
    assert papeis == ["GESTOR_DADOS"]
    [criada] = resposta.json()["itens"]
    assert criada["autor_papeis"] == ["GESTOR_DADOS"]


async def test_historico_e_paginado_com_o_total_da_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """008/R1.1; design da 011 § Rotas (`pagina`, `tamanho`, `PaginaOut`): a segunda página de
    dois traz o terceiro e o quarto eventos mais recentes; depois da última, a lista vem vazia e
    o total continua o da unidade."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    autora = Ator(user_id=(await logado(sessoes, ("GESTOR_DADOS", GLOBAL))).user_id)
    for telefone in ("1", "2", "3", "4"):
        await _registrar(
            sessoes, "unidade.atualizada", autora, caps, [Mudanca("phone", None, telefone)]
        )
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    segunda = await cliente.get(
        _rota(caps), params={"pagina": 2, "tamanho": 2}, headers=bearer(app, auditor)
    )
    depois_da_ultima = await cliente.get(
        _rota(caps), params={"pagina": 4, "tamanho": 2}, headers=bearer(app, auditor)
    )

    assert segunda.status_code == 200
    assert [item["mudancas"][0]["para"] for item in segunda.json()["itens"]] == ["2", "1"]
    assert {k: v for k, v in segunda.json().items() if k != "itens"} == {
        "total": 5,
        "pagina": 2,
        "tamanho": 2,
    }
    assert depois_da_ultima.json() == {"itens": [], "total": 5, "pagina": 4, "tamanho": 2}


@pytest.mark.parametrize(
    "parametros",
    [{"pagina": 0}, {"tamanho": 0}, {"tamanho": 101}, {"pagina": "um"}],
    ids=["pagina-zero", "tamanho-zero", "tamanho-acima-de-100", "pagina-nao-numerica"],
)
async def test_paginacao_invalida_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, parametros: dict[str, Any]
) -> None:
    """Design da 011 § Rotas (`tamanho` padrão 20, máximo 100); steering/security.md: entrada
    inválida dá 422."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(_rota(caps), params=parametros, headers=bearer(app, auditor))

    assert resposta.status_code == 422
    assert resposta.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize(
    ("filtros", "esperados"),
    [
        ({"de": "2020-02-01T00:00:00Z", "ate": "2020-03-10T12:00:00Z"}, ["marco", "fevereiro"]),
        ({"de": "2020-02-10T09:00:00-03:00"}, ["criada", "marco", "fevereiro"]),
        ({"ate": "2020-02-10T11:59:59Z"}, ["janeiro"]),
        ({"autor": "bruno"}, ["fevereiro"]),
        ({"campo": "status"}, ["criada", "fevereiro"]),
        ({"campo": "phone", "autor": "ana"}, ["janeiro"]),
        (
            {"de": "2020-01-01T00:00:00Z", "ate": "2020-12-31T23:59:59Z", "campo": "phone"},
            ["fevereiro", "janeiro"],
        ),
        ({"campo": "cep", "autor": "bruno"}, []),
    ],
    ids=[
        "periodo",
        "so-inicio-com-fuso",
        "so-fim",
        "autor",
        "campo",
        "campo-e-autor",
        "periodo-e-campo",
        "nenhum",
    ],
)
async def test_historico_filtra_por_periodo_autor_e_campo(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    filtros: dict[str, str],
    esperados: list[str],
) -> None:
    """008/R1.3 (filtros por período, autor e campo, pedidos pelo design da 011 § Rotas): o
    período inclui as duas pontas; o autor é o id do usuário; o campo é o nome gravado na lista
    {campo, de, para}. Os filtros se somam e o total é o da lista filtrada."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    ana = Ator(user_id=(await logado(sessoes, ("GESTOR_DADOS", GLOBAL))).user_id)
    bruno = Ator(user_id=(await logado(sessoes, ("GESTOR_DADOS", GLOBAL))).user_id)
    eventos_em = {
        "janeiro": (ana, datetime(2020, 1, 10, 12, tzinfo=UTC), [Mudanca("phone", None, "1")]),
        "fevereiro": (
            bruno,
            datetime(2020, 2, 10, 12, tzinfo=UTC),
            [Mudanca("status", "ativa", "inativa"), Mudanca("phone", "1", "2")],
        ),
        "marco": (ana, datetime(2020, 3, 10, 12, tzinfo=UTC), [Mudanca("name", "CAPS", "CAPS II")]),
    }
    rotulos: dict[str, str] = {}
    for rotulo, (ator, quando, mudancas) in eventos_em.items():
        entrada = await _registrar(
            sessoes, "unidade.atualizada", ator, caps, mudancas, quando=quando
        )
        rotulos[entrada.occurred_at.isoformat().replace("+00:00", "Z")] = rotulo
    autores = {"ana": str(ana.user_id), "bruno": str(bruno.user_id)}
    parametros = {k: autores[v] if k == "autor" else v for k, v in filtros.items()}
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(_rota(caps), params=parametros, headers=bearer(app, auditor))

    assert resposta.status_code == 200, resposta.text
    itens = resposta.json()["itens"]
    assert [
        "criada" if item["acao"] == "unidade.criada" else rotulos[item["ocorrido_em"]]
        for item in itens
    ] == esperados
    assert resposta.json()["total"] == len(esperados)


@pytest.mark.parametrize(
    "parametros",
    [
        {"de": "2020-01-01T00:00:00"},
        {"ate": "ontem"},
        {"autor": "maria"},
        {"campo": "x" * 101},
        {"campo": ""},
    ],
    ids=["de-sem-fuso", "ate-nao-e-data", "autor-nao-e-uuid", "campo-longo", "campo-vazio"],
)
async def test_filtro_mal_formado_responde_422(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, parametros: dict[str, str]
) -> None:
    """008/R1.3; steering/security.md (entrada validada com limites; 422): data sem fuso
    (tech.md, datas sempre com fuso), autor que não é UUID e campo vazio ou longo."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(_rota(caps), params=parametros, headers=bearer(app, auditor))

    assert resposta.status_code == 422
    assert resposta.headers["content-type"] == "application/problem+json"


async def _atribuicao(
    sessoes: Sessoes, papel: str, nivel: str, alvo: str, unidades: dict[str, UUID]
) -> tuple[str, tuple[str, str | None]]:
    """Atribuição do papel no escopo dado: o id da unidade, do distrito ou da área pelo código."""
    match nivel:
        case "global":
            return papel, GLOBAL
        case "unidade":
            return papel, ("unidade", str(unidades[alvo]))
        case _:
            return papel, (nivel, str(await id_pelo_codigo(sessoes, nivel, alvo)))


@pytest.mark.parametrize(
    ("papel", "nivel", "alvo", "esperado"),
    [
        ("AUDITOR", "global", "", 200),
        ("GESTOR_DADOS", "global", "", 200),
        ("COORD_TECNICO", "area", "SAUDE_MENTAL", 200),
        ("COORD_TECNICO", "area", "APS", 403),
        ("TECNICO_DISTRITAL", "distrito", "DS-I", 200),
        ("TECNICO_DISTRITAL", "distrito", "DS-VI", 403),
        ("GESTOR_UNIDADE", "unidade", "caps", 200),
        ("GESTOR_UNIDADE", "unidade", "usf", 403),
    ],
)
async def test_historico_so_passa_no_escopo_de_auditoria_read_da_unidade(
    app: FastAPI,
    cliente: httpx.AsyncClient,
    sessoes: Sessoes,
    papel: str,
    nivel: str,
    alvo: str,
    esperado: int,
) -> None:
    """008/R1.1, 008/R1.4; design da 011 § Rotas (`auditoria:read` no escopo da unidade): o CAPS
    é de Saúde Mental no DS I; a USF, da APS no DS VI."""
    unidades = {
        "caps": await _criar_unidade(app, cliente, sessoes, "CAPS Esperança"),
        "usf": await _criar_unidade(
            app, cliente, sessoes, "USF Ibura", distrito="DS-VI", tipo="USF"
        ),
    }
    usuario = await logado(sessoes, await _atribuicao(sessoes, papel, nivel, alvo, unidades))

    resposta = await cliente.get(_rota(unidades["caps"]), headers=bearer(app, usuario))

    assert resposta.status_code == esperado, resposta.text
    if esperado == 200:
        assert [item["acao"] for item in resposta.json()["itens"]] == ["unidade.criada"]


async def test_fora_do_escopo_responde_403_e_audita_acesso_negado(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """008/R1.4, 003/R4.6: o gestor de outra unidade recebe 403 em problem+json, sem nada do
    histórico, e a negação fica na trilha com a unidade pedida."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    usf = await _criar_unidade(app, cliente, sessoes, "USF Ibura", distrito="DS-VI", tipo="USF")
    gestor_da_usf = await logado(sessoes, ("GESTOR_UNIDADE", ("unidade", str(usf))))

    resposta = await cliente.get(_rota(caps), headers=bearer(app, gestor_da_usf))

    assert resposta.status_code == 403
    assert resposta.headers["content-type"] == "application/problem+json"
    assert "itens" not in resposta.json()
    negacoes = await eventos(sessoes, "acesso.negado")
    assert [
        (negacao["actor_user_id"], negacao["entity_type"], negacao["entity_id"])
        for negacao in negacoes
    ] == [(gestor_da_usf.user_id, "unidade", str(caps))]
    assert negacoes[0]["metadata"] == {
        "permissao": "auditoria:read",
        "rota": "GET /api/v1/unidades/{id}/historico",
    }


async def test_historico_nao_mostra_eventos_de_acesso_da_unidade(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """008/R2.2 (eventos de acesso só para quem tem `auditoria:read_acessos`): a negação de
    acesso à unidade fica na trilha com a unidade como entidade, mas não no histórico dela, que
    o `GESTOR_UNIDADE` também lê. Ver "Perguntas em aberto" da 011."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    usf = await _criar_unidade(app, cliente, sessoes, "USF Ibura", distrito="DS-VI", tipo="USF")
    gestor_da_usf = await logado(sessoes, ("GESTOR_UNIDADE", ("unidade", str(usf))))
    negado = await cliente.get(_rota(caps), headers=bearer(app, gestor_da_usf))
    assert negado.status_code == 403
    await _registrar(sessoes, "auth.login", Ator(user_id=gestor_da_usf.user_id), caps)
    gestor_do_caps = await logado(sessoes, ("GESTOR_UNIDADE", ("unidade", str(caps))))

    resposta = await cliente.get(_rota(caps), headers=bearer(app, gestor_do_caps))

    assert resposta.status_code == 200
    assert [item["acao"] for item in resposta.json()["itens"]] == ["unidade.criada"]
    assert resposta.json()["total"] == 1


async def test_sem_auditoria_read_responde_403(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """008/R1.4: `DIRETORIA` não tem `auditoria:read` em escopo nenhum."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")
    diretora = await logado(sessoes, ("DIRETORIA", GLOBAL))

    resposta = await cliente.get(_rota(caps), headers=bearer(app, diretora))

    assert resposta.status_code == 403


async def test_sem_token_responde_401(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes
) -> None:
    """Design da 011 § Rotas (401); steering/security.md: teste negativo sem token."""
    caps = await _criar_unidade(app, cliente, sessoes, "CAPS Esperança")

    resposta = await cliente.get(_rota(caps))

    assert resposta.status_code == 401
    assert resposta.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize("unidade", ["0197a000-0000-7000-8000-0000000000ff", "nao-e-uuid"])
async def test_unidade_inexistente_responde_404_a_quem_tem_a_permissao(
    app: FastAPI, cliente: httpx.AsyncClient, sessoes: Sessoes, unidade: str
) -> None:
    """Design da 011 § Rotas (404); 003/R4.3: com `auditoria:read` global, a unidade que não
    existe dá 404."""
    auditor = await logado(sessoes, ("AUDITOR", GLOBAL))

    resposta = await cliente.get(_rota(unidade), headers=bearer(app, auditor))

    assert resposta.status_code == 404
    assert resposta.headers["content-type"] == "application/problem+json"
