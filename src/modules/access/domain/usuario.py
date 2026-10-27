"""Identidade legada usada para autorizar uma requisição."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UsuarioAutenticado:
    id_usuario: int
    nome: str
    id_perfil: int
    nome_perfil: str
    permissoes: frozenset[str]
    id_unidade: int | None
