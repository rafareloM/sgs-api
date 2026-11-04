"""Rotas JSON de criação, atualização de status e exclusão de equipamentos."""

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import NotFound
from src.core.session import get_session
from src.modules.access.api.deps import require
from src.modules.access.application.autorizacao import autorizar
from src.modules.access.domain.usuario import UsuarioAutenticado
from src.modules.registry.api.schemas_etapa3 import (
    EquipamentoCreateInput,
    EquipamentoPatchInput,
    UnidadeCreateInput,
    UnidadeStatusPatchInput,
)
from src.modules.registry.application.ports import RegistryStore
from src.modules.registry.application.servicos import (
    atualizar_equipamento,
    atualizar_status_unidade,
    criar_equipamento,
    criar_unidade,
    excluir_equipamento,
)

router = APIRouter(prefix="/api/v1", tags=["cadastro etapa 03"])
_UNIDADE_CREATE = require("unidade:create")
_UNIDADE_READ = require("unidade:read")
_UNIDADE_UPDATE = require("unidade:update")
_EQUIPAMENTO_WRITE = require("equipamento:write")
_UNIDADE_CREATE_DEP = Depends(_UNIDADE_CREATE)
_UNIDADE_READ_DEP = Depends(_UNIDADE_READ)
_UNIDADE_UPDATE_DEP = Depends(_UNIDADE_UPDATE)
_EQUIPAMENTO_WRITE_DEP = Depends(_EQUIPAMENTO_WRITE)
_SESSION_DEP = Depends(get_session)


def _repository(request: Request, session: AsyncSession) -> RegistryStore:
    factory = cast(
        Callable[[AsyncSession], RegistryStore], request.app.state.etapa3_repository_factory
    )
    return factory(session)


def _set_etag(response: Response, versao: int) -> None:
    response.headers["ETag"] = f'"{versao}"'


def _parse_if_match(value: str | None) -> int:
    if value is None:
        raise HTTPException(status_code=428, detail="Envie o cabeçalho If-Match.")
    try:
        return int(value.strip().strip('"'))
    except ValueError:
        raise HTTPException(status_code=400, detail="If-Match inválido.") from None


@router.get("/unidades")
async def get_unidades(
    request: Request,
    pagina: int = 1,
    tamanho: int = 20,
    usuario: UsuarioAutenticado = _UNIDADE_READ_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    if pagina < 1 or tamanho < 1 or tamanho > 100:
        raise HTTPException(status_code=422, detail="Paginação fora dos limites permitidos.")
    autorizar(usuario, "unidade:read", colecao=True)
    return await _repository(request, session).list_unidades(
        id_unidade=usuario.id_unidade if "gestao_dados" not in usuario.permissoes else None,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get("/unidades/{unidade_id}")
async def get_unidade(
    unidade_id: int,
    request: Request,
    usuario: UsuarioAutenticado = _UNIDADE_READ_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    autorizar(usuario, "unidade:read", unidade_id=unidade_id)
    unidade = await _repository(request, session).get_unidade(unidade_id)
    if unidade is None:
        raise NotFound("Unidade não encontrada.")
    return unidade


@router.post(
    "/unidades",
    status_code=status.HTTP_201_CREATED,
)
async def post_unidade(
    payload: UnidadeCreateInput,
    request: Request,
    response: Response,
    usuario: UsuarioAutenticado = _UNIDADE_CREATE_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    unidade = await criar_unidade(
        _repository(request, session), payload.model_dump(), usuario.id_usuario
    )
    _set_etag(response, int(unidade["versao"]))
    return unidade


@router.patch(
    "/unidades/{unidade_id}",
)
async def patch_status_unidade(
    unidade_id: int,
    payload: UnidadeStatusPatchInput,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    usuario: UsuarioAutenticado = _UNIDADE_UPDATE_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    permissao = "unidade:deactivate" if payload.status == "Inativa" else "unidade:update"
    autorizar(usuario, permissao, unidade_id=unidade_id)
    unidade = await atualizar_status_unidade(
        _repository(request, session),
        unidade_id=unidade_id,
        status=payload.status,
        versao=_parse_if_match(if_match),
        autor_id=usuario.id_usuario,
        motivo=payload.motivo,
    )
    _set_etag(response, int(unidade["versao"]))
    return unidade


@router.post(
    "/unidades/{unidade_id}/equipamentos",
    status_code=status.HTTP_201_CREATED,
)
async def post_equipamento(
    unidade_id: int,
    payload: EquipamentoCreateInput,
    request: Request,
    usuario: UsuarioAutenticado = _EQUIPAMENTO_WRITE_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    repository = _repository(request, session)
    if await repository.get_unidade(unidade_id) is None:
        raise NotFound("Unidade não encontrada.")
    autorizar(usuario, "equipamento:write", unidade_id=unidade_id)
    return await criar_equipamento(
        repository,
        unidade_id=unidade_id,
        dados=payload.model_dump(),
    )


@router.get("/unidades/{unidade_id}/equipamentos")
async def get_equipamentos_da_unidade(
    unidade_id: int,
    request: Request,
    usuario: UsuarioAutenticado = _UNIDADE_READ_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> list[dict[str, object]]:
    autorizar(usuario, "unidade:read", unidade_id=unidade_id)
    repository = _repository(request, session)
    if await repository.get_unidade(unidade_id) is None:
        raise NotFound("Unidade não encontrada.")
    return await repository.list_equipamentos(unidade_id)


@router.get("/equipamentos/{equipamento_id}")
async def get_equipamento(
    equipamento_id: int,
    request: Request,
    usuario: UsuarioAutenticado = _UNIDADE_READ_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    repository = _repository(request, session)
    equipamento = await repository.get_equipamento(equipamento_id)
    if equipamento is None:
        raise NotFound("Equipamento não encontrado.")
    if equipamento["idunidade"] is None:
        autorizar(usuario, "equipamento:write", exigir_global=True)
    else:
        autorizar(usuario, "unidade:read", unidade_id=int(equipamento["idunidade"]))
    return equipamento


@router.get("/equipamentos")
async def get_equipamentos_soltos(
    request: Request,
    usuario: UsuarioAutenticado = _EQUIPAMENTO_WRITE_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> list[dict[str, object]]:
    autorizar(usuario, "equipamento:write", exigir_global=True)
    return await _repository(request, session).list_equipamentos(None)


@router.post(
    "/equipamentos",
    status_code=status.HTTP_201_CREATED,
)
async def post_equipamento_solto(
    payload: EquipamentoCreateInput,
    request: Request,
    usuario: UsuarioAutenticado = _EQUIPAMENTO_WRITE_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    autorizar(usuario, "equipamento:write", exigir_global=True)
    return await criar_equipamento(
        _repository(request, session),
        unidade_id=None,
        dados=payload.model_dump(),
    )


@router.patch(
    "/equipamentos/{equipamento_id}",
)
async def patch_equipamento(
    equipamento_id: int,
    payload: EquipamentoPatchInput,
    request: Request,
    usuario: UsuarioAutenticado = _EQUIPAMENTO_WRITE_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> dict[str, object]:
    repository = _repository(request, session)
    equipamento = await repository.get_equipamento(equipamento_id)
    if equipamento is None:
        raise NotFound("Equipamento não encontrado.")
    if equipamento["idunidade"] is None:
        autorizar(usuario, "equipamento:write", exigir_global=True)
    else:
        autorizar(usuario, "equipamento:write", unidade_id=int(equipamento["idunidade"]))
    return await atualizar_equipamento(
        repository,
        equipamento_id=equipamento_id,
        dados=payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/equipamentos/{equipamento_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_equipamento(
    equipamento_id: int,
    request: Request,
    usuario: UsuarioAutenticado = _EQUIPAMENTO_WRITE_DEP,
    session: AsyncSession = _SESSION_DEP,
) -> None:
    repository = _repository(request, session)
    equipamento = await repository.get_equipamento(equipamento_id)
    if equipamento is None:
        raise NotFound("Equipamento não encontrado.")
    if equipamento["idunidade"] is None:
        autorizar(usuario, "equipamento:write", exigir_global=True)
    else:
        autorizar(usuario, "equipamento:write", unidade_id=int(equipamento["idunidade"]))
    await excluir_equipamento(repository, equipamento_id)
