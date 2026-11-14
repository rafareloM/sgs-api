"""Consulta do log do banco e das suas partições pela API (spec 011, R6.9, R7.7 e R7.8; design
§ Rotas).

A rota exige `auditoria:read` pelo `require` da 003; o log é do banco inteiro, sem recorte por
unidade, então aqui se exige ainda que a permissão valha em escopo global (011/R7.8). Fora dele,
`AcessoNegado` (403), auditado pela `SessaoDeNegocio` da camada api.
"""

from src.modules.access.application.autorizacao import (
    AcessoNegado,
    UsuarioAtual,
    escopo_de_leitura,
)
from src.modules.audit.domain.historico import Pagina, Resultado
from src.modules.audit.domain.log_banco import (
    AlteracaoBanco,
    FiltrosDoLog,
    ParticaoDoLog,
    TabelaDoCadastro,
)
from src.modules.audit.domain.ports import LogDoBanco

# Reexportados para a camada api, que só importa a application.
__all__ = [
    "PERMISSAO",
    "AlteracaoBanco",
    "FiltrosDoLog",
    "LogDoBanco",
    "Pagina",
    "ParticaoDoLog",
    "Resultado",
    "TabelaDoCadastro",
    "listar_alteracoes",
    "listar_particoes",
]

PERMISSAO = "auditoria:read"


def _exigir_escopo_global(usuario: UsuarioAtual) -> None:
    """011/R7.8: `auditoria:read` de área, distrito ou unidade não dá acesso ao log."""
    if not escopo_de_leitura(usuario, PERMISSAO).global_:
        raise AcessoNegado(PERMISSAO)


async def listar_alteracoes(
    log: LogDoBanco, usuario: UsuarioAtual, filtros: FiltrosDoLog, pagina: Pagina
) -> Resultado[AlteracaoBanco]:
    """011/R7.7: registros do log nos filtros pedidos, do mais recente para o mais antigo."""
    _exigir_escopo_global(usuario)
    return await log.listar(filtros, pagina)


async def listar_particoes(log: LogDoBanco, usuario: UsuarioAtual) -> tuple[ParticaoDoLog, ...]:
    """011/R6.9: as partições do log com o intervalo e a quantidade de registros."""
    _exigir_escopo_global(usuario)
    return await log.particoes()
