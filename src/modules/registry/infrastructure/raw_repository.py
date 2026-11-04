"""Operações de cadastro feitas com SQL explícito para a Etapa 03."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import PreconditionFailed
from src.modules.registry.domain.unidade import normalizar_nome

_SELECT_UNIDADE = text(
    "SELECT idunidade, codigocnes, nome, tipo, endereco, cep, distritosanitario, telefone, "
    "status, datacriacao, dataatualizacao, cnes_pendente, versao "
    "FROM unidade_saude WHERE idunidade = :idunidade"
)
_INSERT_ALTERACAO = text(
    "INSERT INTO alteracao "
    "(campoalterado, valoranterior, valornovo, idunidade, idusuario, motivo) "
    "VALUES (:campo, :anterior, :novo, :idunidade, :idusuario, :motivo)"
)


class SqlEtapa3Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_unidade(self, unidade_id: int) -> dict[str, Any] | None:
        result = await self._session.execute(_SELECT_UNIDADE, {"idunidade": unidade_id})
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def list_unidades(
        self, *, id_unidade: int | None, pagina: int, tamanho: int
    ) -> dict[str, Any]:
        filtros = {"id_unidade": id_unidade}
        total_result = await self._session.execute(
            text(
                "SELECT COUNT(*) FROM unidade_saude "
                "WHERE (:id_unidade IS NULL OR idunidade = :id_unidade)"
            ),
            filtros,
        )
        rows_result = await self._session.execute(
            text(
                "SELECT idunidade, codigocnes, nome, tipo, endereco, cep, distritosanitario, "
                "telefone, status, datacriacao, dataatualizacao, cnes_pendente, versao "
                "FROM unidade_saude "
                "WHERE (:id_unidade IS NULL OR idunidade = :id_unidade) "
                "ORDER BY nomenormalizado, idunidade LIMIT :limite OFFSET :offset"
            ),
            {
                **filtros,
                "limite": tamanho,
                "offset": (pagina - 1) * tamanho,
            },
        )
        return {
            "itens": [dict(row) for row in rows_result.mappings().all()],
            "total": int(total_result.scalar_one()),
            "pagina": pagina,
            "tamanho": tamanho,
        }

    async def create_unidade(self, dados: Mapping[str, Any], autor_id: int) -> dict[str, Any]:
        parametros = dict(dados)
        parametros["nomenormalizado"] = normalizar_nome(str(parametros["nome"]))
        result = await self._session.execute(
            text(
                "INSERT INTO unidade_saude "
                "(codigocnes, nome, tipo, endereco, cep, distritosanitario, telefone, status, "
                "cnes_pendente, nomenormalizado, versao) "
                "VALUES (:codigocnes, :nome, :tipo, :endereco, :cep, :distritosanitario, "
                ":telefone, :status, :cnes_pendente, :nomenormalizado, 1) "
                "RETURNING idunidade, codigocnes, nome, tipo, endereco, cep, distritosanitario, "
                "telefone, status, datacriacao, dataatualizacao, cnes_pendente, versao"
            ),
            parametros,
        )
        row = dict(result.mappings().one())
        auditar = [
            {
                "campo": campo,
                "anterior": None,
                "novo": str(valor) if valor is not None else None,
                "idunidade": row["idunidade"],
                "idusuario": autor_id,
                "motivo": None,
            }
            for campo, valor in (
                ("CodigoCNES", parametros["codigocnes"]),
                ("Nome", parametros["nome"]),
                ("Tipo", parametros["tipo"]),
                ("Endereco", parametros["endereco"]),
                ("CEP", parametros["cep"]),
                ("DistritoSanitario", parametros["distritosanitario"]),
                ("Telefone", parametros["telefone"]),
                ("Status", parametros["status"]),
            )
            if valor is not None
        ]
        await self._session.execute(_INSERT_ALTERACAO, auditar)
        return row

    async def update_status(
        self,
        unidade_id: int,
        status: str,
        versao: int,
        autor_id: int,
        motivo: str | None,
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            text(
                "SELECT status, versao FROM unidade_saude WHERE idunidade = :idunidade FOR UPDATE"
            ),
            {"idunidade": unidade_id},
        )
        anterior = result.mappings().one_or_none()
        if anterior is None:
            return None
        if int(anterior["versao"]) != versao:
            raise PreconditionFailed("A unidade foi alterada. Atualize os dados e tente novamente.")
        if anterior["status"] == status:
            return await self.get_unidade(unidade_id)
        result = await self._session.execute(
            text(
                "UPDATE unidade_saude SET status = :status, "
                "dataatualizacao = CURRENT_TIMESTAMP, versao = versao + 1 "
                "WHERE idunidade = :idunidade AND versao = :versao "
                "RETURNING idunidade, codigocnes, nome, tipo, endereco, cep, distritosanitario, "
                "telefone, status, datacriacao, dataatualizacao, cnes_pendente, versao"
            ),
            {"status": status, "idunidade": unidade_id, "versao": versao},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise PreconditionFailed("A unidade foi alterada. Atualize os dados e tente novamente.")
        await self._session.execute(
            text(
                "INSERT INTO alteracao "
                "(campoalterado, valoranterior, valornovo, idunidade, idusuario, motivo) "
                "VALUES (:campo, :anterior, :novo, :idunidade, :idusuario, :motivo)"
            ),
            {
                "campo": "Status",
                "anterior": str(anterior["status"]),
                "novo": status,
                "idunidade": unidade_id,
                "idusuario": autor_id,
                "motivo": motivo,
            },
        )
        return dict(row)

    async def get_equipamento(self, equipamento_id: int) -> dict[str, Any] | None:
        result = await self._session.execute(
            text(
                "SELECT idequipamento, nome, tipo, quantidade, idunidade "
                "FROM equipamento WHERE idequipamento = :idequipamento"
            ),
            {"idequipamento": equipamento_id},
        )
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def list_equipamentos(self, unidade_id: int | None) -> list[dict[str, Any]]:
        if unidade_id is None:
            result = await self._session.execute(
                text(
                    "SELECT idequipamento, nome, tipo, quantidade, idunidade "
                    "FROM equipamento ORDER BY idequipamento"
                )
            )
            return [dict(row) for row in result.mappings().all()]
        result = await self._session.execute(
            text(
                "SELECT idequipamento, nome, tipo, quantidade, idunidade "
                "FROM equipamento WHERE idunidade = :idunidade ORDER BY idequipamento"
            ),
            {"idunidade": unidade_id},
        )
        return [dict(row) for row in result.mappings().all()]

    async def create_equipamento(
        self, unidade_id: int | None, dados: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = await self._session.execute(
            text(
                "INSERT INTO equipamento (nome, tipo, quantidade, idunidade) "
                "VALUES (:nome, :tipo, :quantidade, :idunidade) "
                "RETURNING idequipamento, nome, tipo, quantidade, idunidade"
            ),
            {**dados, "idunidade": unidade_id},
        )
        return dict(result.mappings().one())

    async def update_equipamento(
        self, equipamento_id: int, dados: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        atual = await self.get_equipamento(equipamento_id)
        if atual is None:
            return None
        novos = {**atual, **dados}
        if all(atual[coluna] == novos[coluna] for coluna in ("nome", "tipo", "quantidade")):
            return atual
        result = await self._session.execute(
            text(
                "UPDATE equipamento SET nome = :nome, tipo = :tipo, quantidade = :quantidade "
                "WHERE idequipamento = :idequipamento "
                "RETURNING idequipamento, nome, tipo, quantidade, idunidade"
            ),
            {
                "nome": novos["nome"],
                "tipo": novos["tipo"],
                "quantidade": novos["quantidade"],
                "idequipamento": equipamento_id,
            },
        )
        return dict(result.mappings().one())

    async def delete_equipamento(self, equipamento_id: int) -> bool:
        result = await self._session.execute(
            text(
                "DELETE FROM equipamento WHERE idequipamento = :idequipamento "
                "RETURNING idequipamento"
            ),
            {"idequipamento": equipamento_id},
        )
        return result.scalar_one_or_none() is not None
