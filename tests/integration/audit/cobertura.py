"""Mapa de cobertura da trilha: toda rota de escrita → a ação que ela grava (spec 013, T11; R7.1).

Uma rota de escrita nova precisa entrar em `MAPA` ou em `EXCECOES` (com o motivo), senão
`test_toda_rota_de_escrita_esta_mapeada` falha.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

ESCRITA = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Esperado:
    acao: str
    entidade: str | None
    resultado: str = "success"


MAPA: dict[str, Esperado] = {
    # Login com senha certa só abre o desafio do 2FA (o `auth.login` sai no confirm/verify); o
    # fato auditado da rota é a tentativa que falha.
    "POST /api/v1/auth/login": Esperado("auth.login_failed", "usuario", "failure"),
    "POST /api/v1/auth/mfa/confirm": Esperado("auth.mfa_enrolled", "usuario"),
    "POST /api/v1/auth/mfa/verify": Esperado("auth.login", "usuario"),
    "POST /api/v1/auth/logout": Esperado("auth.logout", "usuario"),
    "POST /api/v1/admin/atribuicoes": Esperado("papel.atribuido", "usuario"),
    "DELETE /api/v1/admin/atribuicoes/{id_}": Esperado("papel.removido", "usuario"),
    # O grupo do teste não tem membros, então o mapeamento só grava o próprio evento, sem
    # `papel.atribuido` ou `papel.removido` de derivadas (003/T8).
    "POST /api/v1/admin/mapeamentos-grupo": Esperado("mapeamento.criado", "mapeamento_grupo"),
    "DELETE /api/v1/admin/mapeamentos-grupo/{id_}": Esperado(
        "mapeamento.removido", "mapeamento_grupo"
    ),
    # A execução roda em segundo plano, com quem disparou como ator (004/T4).
    "POST /api/v1/admin/diretorio/sincronizar": Esperado(
        "diretorio.sincronizado", "execucao_diretorio"
    ),
    "POST /api/v1/unidades": Esperado("unidade.criada", "unidade"),
    # A geração em segundo plano audita `relatorio.exportado` depois; o fato da rota é o pedido.
    "POST /api/v1/relatorios": Esperado("relatorio.solicitado", "relatorio"),
    "PATCH /api/v1/unidades/{id}": Esperado("unidade.atualizada", "unidade"),
    "POST /api/v1/unidades/{id}/desativar": Esperado("unidade.desativada", "unidade"),
    "POST /api/v1/unidades/{id}/equipamentos": Esperado(
        "unidade.equipamento_adicionado", "unidade"
    ),
    "PATCH /api/v1/unidades/{id}/equipamentos/{equipamento_id}": Esperado(
        "unidade.equipamento_alterado", "unidade"
    ),
    "DELETE /api/v1/unidades/{id}/equipamentos/{equipamento_id}": Esperado(
        "unidade.equipamento_removido", "unidade"
    ),
    "POST /api/v1/equipamentos": Esperado("equipamento.adicionado", "equipamento"),
    "PATCH /api/v1/equipamentos/{equipamento_id}": Esperado("equipamento.alterado", "equipamento"),
    "DELETE /api/v1/equipamentos/{equipamento_id}": Esperado("equipamento.removido", "equipamento"),
    "POST /api/v1/unidades/{id}/servicos": Esperado("unidade.servico_adicionado", "unidade"),
    "PATCH /api/v1/unidades/{id}/servicos/{servico_id}": Esperado(
        "unidade.servico_alterado", "unidade"
    ),
    "DELETE /api/v1/unidades/{id}/servicos/{servico_id}": Esperado(
        "unidade.servico_removido", "unidade"
    ),
    "POST /api/v1/servicos": Esperado("servico.adicionado", "servico"),
    "PATCH /api/v1/servicos/{servico_id}": Esperado("servico.alterado", "servico"),
    "DELETE /api/v1/servicos/{servico_id}": Esperado("servico.removido", "servico"),
    "POST /api/v1/referencias/{tipo}": Esperado("referencia.criada", "referencia"),
    "PATCH /api/v1/referencias/{tipo}/{id_}": Esperado("referencia.atualizada", "referencia"),
    "POST /api/v1/auditoria/verificar": Esperado("auditoria.verificada", None),
}

EXCECOES: dict[str, str] = {
    "POST /api/v1/auth/mfa/enroll": (
        "só emite o QR do segredo pendente, sem estado durável; a matrícula é auditada no"
        " confirm (`auth.mfa_enrolled`)"
    ),
    "POST /api/v1/auth/refresh": (
        "rotação de token, de volume alto; o fato relevante (`auth.login`) já está gravado, e o"
        " reuso é auditado (`auth.refresh_reuse`)"
    ),
}
"""Rotas de escrita sem evento de sucesso, com o motivo (013 design § Mapa de cobertura). Uma
escrita sem mudança (PATCH idêntico) também não gera evento: não há fato."""


def rotas_de_escrita(rotas: Sequence[BaseRoute], prefixo: str = "") -> set[str]:
    """`MÉTODO caminho` de cada rota de escrita, seguindo os roteadores incluídos (nesta versão
    do FastAPI, `include_router` guarda o roteador em vez de copiar as rotas)."""
    encontradas: set[str] = set()
    for rota in rotas:
        if isinstance(rota, APIRoute):
            for metodo in (rota.methods or set()) & ESCRITA:
                encontradas.add(f"{metodo} {prefixo}{rota.path}")
        incluido = getattr(rota, "original_router", None)
        if incluido is not None:
            contexto = getattr(rota, "include_context", None)
            encontradas |= rotas_de_escrita(
                incluido.routes, prefixo + getattr(contexto, "prefix", "")
            )
    return encontradas
