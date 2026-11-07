"""Casos de uso das consultas de qualidade do cadastro (spec 011, R2; design § Fluxo, Consulta).

Cada consulta obtém o escopo de leitura do usuário para `dashboard:read` (spec 003) e chama a
porta `ConsultasDashboard`, que executa o SQL com o escopo como parâmetros.
"""

from src.core.errors import DomainValidationError, FieldError
from src.modules.access.application.autorizacao import UsuarioAtual, escopo_de_leitura
from src.modules.dashboard.domain.consultas import (
    Filtros,
    ItemConciliacao,
    Pagina,
    Resultado,
    SituacaoConciliacao,
    UnidadeResumo,
)
from src.modules.dashboard.domain.ports import ConsultasDashboard

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "PERMISSAO",
    "ConsultasDashboard",
    "Filtros",
    "ItemConciliacao",
    "Pagina",
    "Resultado",
    "SituacaoConciliacao",
    "UnidadeResumo",
    "conciliacao_unidade_equipamento",
    "unidades_sem_servico",
]

PERMISSAO = "dashboard:read"


async def unidades_sem_servico(
    consultas: ConsultasDashboard, usuario: UsuarioAtual, filtros: Filtros, pagina: Pagina
) -> Resultado[UnidadeResumo]:
    """011/R2.1, R2.5: unidades não inativas sem serviço, no escopo de leitura do usuário."""
    await _conferir_filtros(consultas, filtros)
    escopo = escopo_de_leitura(usuario, PERMISSAO)
    return await consultas.unidades_sem_servico(escopo, filtros, pagina)


async def conciliacao_unidade_equipamento(
    consultas: ConsultasDashboard, usuario: UsuarioAtual, filtros: Filtros, pagina: Pagina
) -> Resultado[ItemConciliacao]:
    """011/R2.2, R2.5, R2.6: conciliação unidade x equipamento no escopo de leitura do usuário;
    equipamento sem unidade só com escopo global."""
    await _conferir_filtros(consultas, filtros)
    escopo = escopo_de_leitura(usuario, PERMISSAO)
    return await consultas.conciliacao_unidade_equipamento(escopo, filtros, pagina)


async def _conferir_filtros(consultas: ConsultasDashboard, filtros: Filtros) -> None:
    """011/R2.9: distrito ou tipo inexistente dá 422 antes de a consulta rodar. O formato (número
    inteiro no intervalo do id) já foi conferido pelo schema da rota."""
    erros = []
    if filtros.distrito is not None and not await consultas.distrito_existe(filtros.distrito):
        erros.append(FieldError(campo="distrito", mensagem="Distrito inexistente."))
    if filtros.tipo is not None and not await consultas.tipo_de_unidade_existe(filtros.tipo):
        erros.append(FieldError(campo="tipo", mensagem="Tipo de unidade inexistente."))
    if erros:
        raise DomainValidationError("O filtro aponta para uma referência que não existe.", erros)
