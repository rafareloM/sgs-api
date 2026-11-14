"""Repositórios do cadastro sobre a sessão SQLAlchemy de quem os usa.

SQL escrito à mão, em `sql/*.sql`, executado com `text()` e parâmetros nomeados (ADR-0009).
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.escopo import parametros_de_escopo
from src.core.sql import consulta
from src.modules.registry.domain.busca import (
    DetalheDaUnidade,
    EquipamentoDaUnidade,
    FiltrosDeUnidades,
    Ordenacao,
    PaginaDeUnidades,
    PaginaPedida,
    ServicoDaUnidade,
)
from src.modules.registry.domain.ports import EscopoDeLeitura
from src.modules.registry.domain.unidade import (
    CAMPOS_DE_NEGOCIO,
    DadosDaUnidade,
    Desativacao,
    Unidade,
    UnidadeRepetidaError,
)

_SQL = Path(__file__).parent / "sql"

# O JSONB declarado faz o SQLAlchemy serializar o dicionário do horário de funcionamento.
_INSERIR_UNIDADE = consulta(_SQL / "insert_health_unit.sql").bindparams(
    bindparam("opening_hours", type_=JSONB)
)
_AREA_DO_TIPO = consulta(_SQL / "unit_type_technical_area.sql")
_DISTRITO_ATIVO = consulta(_SQL / "district_is_active.sql")
_ID_PELO_CNES = consulta(_SQL / "health_unit_id_by_cnes.sql")
_ID_PELO_NOME = consulta(_SQL / "health_unit_id_by_name.sql")
_DESATIVAR = consulta(_SQL / "deactivate_health_unit.sql")
_UNIDADE_PELO_ID = consulta(_SQL / "health_unit_by_id.sql")
_AREA_DA_UNIDADE = consulta(_SQL / "health_unit_technical_area.sql")
_ATUALIZAR_UNIDADE = consulta(_SQL / "update_health_unit.sql").bindparams(
    bindparam("opening_hours", type_=JSONB)
)
_BUSCAR_UNIDADES = consulta(_SQL / "search_health_units.sql")
_EQUIPAMENTOS_DA_UNIDADE = consulta(_SQL / "health_unit_equipments.sql")
_SERVICOS_DA_UNIDADE = consulta(_SQL / "health_unit_services.sql")

# SQLSTATE do Postgres para valor repetido num índice único.
_UNIQUE_VIOLATION = "23505"

# SQLSTATE próprio que o `sp_deactivate_unit` levanta para unidade inexistente (0011_06).
_UNIDADE_INEXISTENTE = "SGS01"


class SqlRepositorioDeUnidades:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def area_do_tipo(self, unit_type_id: int) -> int | None:
        area: int | None = await self._session.scalar(_AREA_DO_TIPO, {"unit_type_id": unit_type_id})
        return area

    async def distrito_ativo(self, district_id: int) -> bool:
        return bool(await self._session.scalar(_DISTRITO_ATIVO, {"district_id": district_id}))

    async def inserir(self, id_: UUID, dados: DadosDaUnidade) -> Unidade | None:
        parametros: dict[str, Any] = {campo: getattr(dados, campo) for campo in CAMPOS_DE_NEGOCIO}
        resultado = await self._session.execute(_INSERIR_UNIDADE, {"id": id_, **parametros})
        linha = resultado.mappings().one_or_none()
        return None if linha is None else _unidade(linha)

    async def com_cnes(self, cnes: str) -> UUID | None:
        unidade: UUID | None = await self._session.scalar(_ID_PELO_CNES, {"cnes": cnes})
        return unidade

    async def com_nome(self, district_id: int, name: str) -> UUID | None:
        unidade: UUID | None = await self._session.scalar(
            _ID_PELO_NOME, {"district_id": district_id, "name": name}
        )
        return unidade

    async def ler(self, id_: UUID) -> Unidade | None:
        resultado = await self._session.execute(_UNIDADE_PELO_ID, {"id": id_})
        linha = resultado.mappings().one_or_none()
        return None if linha is None else _unidade(linha)

    async def area_da_unidade(self, id_: UUID) -> int | None:
        area: int | None = await self._session.scalar(_AREA_DA_UNIDADE, {"id": id_})
        return area

    async def atualizar(
        self, id_: UUID, versao_esperada: int, dados: DadosDaUnidade
    ) -> Unidade | None:
        parametros: dict[str, Any] = {campo: getattr(dados, campo) for campo in CAMPOS_DE_NEGOCIO}
        try:
            # O savepoint desfaz só o UPDATE recusado; a transação da requisição segue, e o caso
            # de uso ainda procura a unidade repetida para o 409.
            async with self._session.begin_nested():
                resultado = await self._session.execute(
                    _ATUALIZAR_UNIDADE,
                    {"id": id_, "expected_version": versao_esperada, **parametros},
                )
                linha = resultado.mappings().one_or_none()
        except IntegrityError as erro:
            if getattr(erro.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
                raise UnidadeRepetidaError from None
            raise
        return None if linha is None else _unidade(linha)

    async def desativar(self, id_: UUID) -> Desativacao | None:
        try:
            resultado = await self._session.execute(_DESATIVAR, {"id": id_})
        except DBAPIError as erro:
            # Só o "não existe" do procedimento vira `None`; a mensagem do banco não sai daqui
            # (011/R6.3). Qualquer outro erro segue adiante, e a requisição responde 500.
            if getattr(erro.orig, "sqlstate", None) == _UNIDADE_INEXISTENTE:
                return None
            raise
        status_anterior: str = resultado.one().o_previous_status
        linha = (await self._session.execute(_UNIDADE_PELO_ID, {"id": id_})).mappings().one()
        return Desativacao(status_anterior=status_anterior, unidade=_unidade(linha))

    async def buscar(
        self,
        escopo: EscopoDeLeitura,
        filtros: FiltrosDeUnidades,
        ordem: Ordenacao,
        pagina: PaginaPedida,
    ) -> PaginaDeUnidades:
        parametros: dict[str, Any] = {
            **parametros_de_escopo(escopo),
            "q": filtros.texto,
            "q_like": None if filtros.texto is None else _escapar_like(filtros.texto),
            "unit_type_id": filtros.tipo,
            "technical_area_id": filtros.area,
            "district_id": filtros.distrito,
            "status": filtros.status,
            "with_pending": filtros.com_pendencias,
            "order_by": ordem,
            "limit": pagina.tamanho,
            "offset": pagina.offset,
        }
        linhas = list((await self._session.execute(_BUSCAR_UNIDADES, parametros)).mappings())
        if linhas:
            total = int(linhas[0]["total"])
        elif pagina.offset == 0:
            total = 0
        else:
            # Numa página depois da última não volta linha; o total sai da primeira.
            primeira = await self._session.execute(
                _BUSCAR_UNIDADES, {**parametros, "limit": 1, "offset": 0}
            )
            linha = primeira.mappings().first()
            total = 0 if linha is None else int(linha["total"])
        itens = tuple(
            _unidade({k: v for k, v in linha.items() if k != "total"}) for linha in linhas
        )
        return PaginaDeUnidades(itens=itens, total=total)

    async def detalhar(self, id_: UUID) -> DetalheDaUnidade | None:
        unidade = await self.ler(id_)
        if unidade is None:
            return None
        equipamentos = await self._session.execute(_EQUIPAMENTOS_DA_UNIDADE, {"unit_id": id_})
        servicos = await self._session.execute(_SERVICOS_DA_UNIDADE, {"unit_id": id_})
        return DetalheDaUnidade(
            unidade=unidade,
            equipamentos=tuple(EquipamentoDaUnidade(**linha) for linha in equipamentos.mappings()),
            servicos=tuple(ServicoDaUnidade(**linha) for linha in servicos.mappings()),
        )


def _escapar_like(texto: str) -> str:
    """O texto com a barra invertida, `%` e `_` escapados, para o LIKE procurá-los como
    caracteres (a barra invertida é o escape padrão do Postgres)."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _unidade(linha: Mapping[Any, Any]) -> Unidade:
    return Unidade(**dict(linha))
