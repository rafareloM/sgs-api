"""Regras de autorização legada sem acesso ao banco ou ao FastAPI."""

import pytest

from src.core.errors import Forbidden
from src.modules.access.application.autorizacao import autorizar
from src.modules.access.domain.usuario import UsuarioAutenticado


def _usuario(permissoes: str, id_unidade: int | None = None) -> UsuarioAutenticado:
    return UsuarioAutenticado(
        id_usuario=10,
        nome="Usuário de teste",
        id_perfil=2,
        nome_perfil="Gestor de Unidade 01",
        permissoes=frozenset(permissoes.split(";")),
        id_unidade=id_unidade,
    )


def test_gestor_de_dados_pode_criar_unidades_globalmente() -> None:
    autorizar(_usuario("gestao_dados;cadastro_unidade"), "unidade:create")


def test_gestor_de_unidade_so_altera_a_unidade_vinculada() -> None:
    usuario = _usuario("consulta_unidade;edicao_unidade", id_unidade=7)

    autorizar(usuario, "unidade:update", unidade_id=7)
    with pytest.raises(Forbidden):
        autorizar(usuario, "unidade:update", unidade_id=8)


def test_perfil_sem_unidade_nao_recebe_escopo_global() -> None:
    usuario = _usuario("consulta_unidade", id_unidade=None)

    with pytest.raises(Forbidden):
        autorizar(usuario, "unidade:read", unidade_id=7)


def test_perfil_sem_unidade_nao_lista_todas_as_unidades() -> None:
    with pytest.raises(Forbidden):
        autorizar(_usuario("consulta_unidade"), "unidade:read", colecao=True)


def test_permissao_nao_declarada_e_negada() -> None:
    with pytest.raises(Forbidden):
        autorizar(_usuario("consulta_unidade", id_unidade=7), "unidade:deactivate")
