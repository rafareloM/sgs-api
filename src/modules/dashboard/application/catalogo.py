"""Catálogo de consultas filtrado pelas permissões efetivas do usuário (spec 011, R3.1 e R3.2).

A lista fixa fica no domain; aqui sai só o que o usuário pode executar: a permissão da entrada em
algum escopo e, para o log do banco e as partições, em escopo global (011/R7.8).
"""

from src.modules.access.application.autorizacao import UsuarioAtual, escopo_de_leitura
from src.modules.dashboard.domain.catalogo import CATALOGO, Coluna, ConsultaDescrita, Parametro

# Reexportados para a camada api, que só importa a application.
__all__ = ["Coluna", "ConsultaDescrita", "Parametro", "consultas_permitidas"]


def _pode_executar(usuario: UsuarioAtual, consulta: ConsultaDescrita) -> bool:
    escopo = escopo_de_leitura(usuario, consulta.permissao)
    if consulta.exige_escopo_global:
        return escopo.global_
    return escopo.global_ or bool(escopo.areas or escopo.distritos or escopo.unidades)


def consultas_permitidas(usuario: UsuarioAtual) -> tuple[ConsultaDescrita, ...]:
    """011/R3.2: as entradas do catálogo que o usuário tem permissão de executar, na ordem fixa."""
    return tuple(consulta for consulta in CATALOGO if _pode_executar(usuario, consulta))
