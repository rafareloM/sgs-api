"""Rotas das tabelas de referência (design da 006 § Rotas; design da 011 § Rotas).

Para cada tabela, `GET /referencias/<tabela>` (qualquer usuário autenticado, 006/R7.1), `POST`
para incluir e `PATCH /{id}` para alterar, inclusive o código, ou desativar (`ativo: false`), só
com `regra_validacao:manage`, que a matriz dá ao Gestor de Dados (006/R7.2). Corrigir o código
de um tipo de equipamento leva o código novo aos equipamentos (006/R7.3, 011/R9.2).
"""

from dataclasses import asdict
from typing import Annotated, Self, cast

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.problem import problema
from src.modules.access.api.deps import (
    SessaoDeNegocio,
    UsuarioAtual,
    ator_da_requisicao,
    require,
)
from src.modules.identity.api.deps import CurrentUser
from src.modules.registry.application.referencias import (
    DadosDaReferencia,
    Referencia,
    TipoDeReferencia,
    alterar_referencia,
    criar_referencia,
    listar_referencias,
)

router = APIRouter(prefix="/api/v1/referencias", tags=["referências"])

PERMISSAO = "regra_validacao:manage"

# Tamanhos das colunas (0003 e 0006): `districts.code` é `varchar(20)`; os outros códigos,
# `varchar(50)`; os nomes, `varchar(100)`. Ids de referência são `smallint`.
_Nome = Annotated[str, Field(min_length=1, max_length=100)]
_Codigo = Annotated[str, Field(min_length=1, max_length=50)]
_CodigoDeDistrito = Annotated[str, Field(min_length=1, max_length=20)]
_IdDeReferencia = Annotated[int, Field(ge=1, le=32767)]


class ReferenciaCreate(BaseModel):
    """Item novo; nasce ativo."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    codigo: _Codigo
    nome: _Nome

    def dados(self) -> DadosDaReferencia:
        return DadosDaReferencia(codigo=self.codigo, nome=self.nome)


class DistritoCreate(ReferenciaCreate):
    codigo: _CodigoDeDistrito


class TipoUnidadeCreate(ReferenciaCreate):
    """O tipo de unidade aponta a área técnica, escopo do Coordenador Técnico (003)."""

    area_tecnica_id: _IdDeReferencia

    def dados(self) -> DadosDaReferencia:
        return DadosDaReferencia(
            codigo=self.codigo, nome=self.nome, area_tecnica_id=self.area_tecnica_id
        )


class ReferenciaUpdate(BaseModel):
    """Só os campos enviados mudam; `ativo: false` desativa, `true` reativa. Nulo explícito é
    recusado: os campos não são opcionais no banco."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    codigo: _Codigo | None = None
    nome: _Nome | None = None
    ativo: bool | None = None

    @model_validator(mode="after")
    def _sem_nulo(self) -> Self:
        nulos = [campo for campo in self.model_fields_set if getattr(self, campo) is None]
        if nulos:
            raise ValueError(f"Campo não pode ser nulo: {', '.join(sorted(nulos))}.")
        return self

    def mudancas(self) -> dict[str, object]:
        # Na ordem da declaração, que é a do de/para da auditoria (`model_fields_set` é um set).
        enviados = self.model_fields_set
        return {
            campo: getattr(self, campo) for campo in type(self).model_fields if campo in enviados
        }


class DistritoUpdate(ReferenciaUpdate):
    codigo: _CodigoDeDistrito | None = None


class TipoUnidadeUpdate(ReferenciaUpdate):
    area_tecnica_id: _IdDeReferencia | None = None


class ReferenciaOut(BaseModel):
    id: int
    codigo: str
    nome: str
    ativo: bool

    @classmethod
    def de(cls, item: Referencia) -> Self:
        # Os campos que o schema não declara (a área, fora do tipo de unidade) ficam de fora.
        return cls.model_validate(asdict(item))


class TipoUnidadeOut(ReferenciaOut):
    area_tecnica_id: int


def _rotas(
    caminho: str,
    tipo: TipoDeReferencia,
    rotulo: str,
    create: type[ReferenciaCreate],
    update: type[ReferenciaUpdate],
    out: type[ReferenciaOut],
) -> None:
    """Liga as três rotas de uma tabela de referência ao `router`. Cada uma declara a sua
    exigência (autenticação no GET, `require(PERMISSAO)` no POST e no PATCH)."""

    @router.get(
        f"/{caminho}",
        summary=f"Listar {rotulo}",
        response_model=list[out],  # type: ignore[valid-type]
        responses={401: problema("Sem access token válido")},
    )
    async def listar(
        request: Request, _usuario: CurrentUser, sessao: SessaoDeNegocio
    ) -> list[ReferenciaOut]:
        """006/R7.1: ativos e desativados (`ativo`), na ordem da semeadura."""
        itens = await listar_referencias(
            tipo, referencias=request.app.state.repositorio_de_referencias(sessao)
        )
        return [out.de(item) for item in itens]

    @router.post(
        f"/{caminho}",
        status_code=201,
        summary=f"Incluir item em {rotulo}",
        response_model=out,
        responses={
            401: problema("Sem access token válido"),
            403: problema(f"Sem `{PERMISSAO}`"),
            409: problema("Já existe item com este código"),
            422: problema("Campos inválidos, ou área técnica inexistente ou desativada"),
        },
    )
    async def criar(
        request: Request,
        corpo: create,  # type: ignore[valid-type]
        usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
        sessao: SessaoDeNegocio,
    ) -> ReferenciaOut:
        """006/R7.2. Audita `referencia.criada`."""
        estado = request.app.state
        item = await criar_referencia(
            tipo,
            cast(ReferenciaCreate, corpo).dados(),
            ator=ator_da_requisicao(request, usuario),
            referencias=estado.repositorio_de_referencias(sessao),
            auditoria=estado.auditoria(sessao),
        )
        return out.de(item)

    @router.patch(
        f"/{caminho}/{{id}}",
        summary=f"Alterar ou desativar item de {rotulo}",
        response_model=out,
        responses={
            401: problema("Sem access token válido"),
            403: problema(f"Sem `{PERMISSAO}`"),
            404: problema("O item não existe"),
            409: problema("Já existe item com este código"),
            422: problema("Campos inválidos, ou área técnica inexistente ou desativada"),
        },
    )
    async def alterar(
        request: Request,
        id: Annotated[int, Path(ge=1, le=32767)],
        corpo: update,  # type: ignore[valid-type]
        usuario: Annotated[UsuarioAtual, Depends(require(PERMISSAO))],
        sessao: SessaoDeNegocio,
    ) -> ReferenciaOut:
        """006/R7.2, R7.3; 011/R9.2. Audita `referencia.atualizada` com o de/para (e, no código
        de um tipo de equipamento, `equipamentos_afetados`); nada mudou, nada é auditado."""
        estado = request.app.state
        item = await alterar_referencia(
            tipo,
            id,
            cast(ReferenciaUpdate, corpo).mudancas(),
            ator=ator_da_requisicao(request, usuario),
            referencias=estado.repositorio_de_referencias(sessao),
            auditoria=estado.auditoria(sessao),
        )
        return out.de(item)


_rotas(
    "distritos",
    TipoDeReferencia.DISTRITO,
    "distritos sanitários",
    DistritoCreate,
    DistritoUpdate,
    ReferenciaOut,
)
_rotas(
    "areas-tecnicas",
    TipoDeReferencia.AREA_TECNICA,
    "áreas técnicas",
    ReferenciaCreate,
    ReferenciaUpdate,
    ReferenciaOut,
)
_rotas(
    "tipos-unidade",
    TipoDeReferencia.TIPO_UNIDADE,
    "tipos de unidade",
    TipoUnidadeCreate,
    TipoUnidadeUpdate,
    TipoUnidadeOut,
)
_rotas(
    "tipos-equipamento",
    TipoDeReferencia.TIPO_EQUIPAMENTO,
    "tipos de equipamento",
    ReferenciaCreate,
    ReferenciaUpdate,
    ReferenciaOut,
)
_rotas(
    "tipos-servico",
    TipoDeReferencia.TIPO_SERVICO,
    "tipos de serviço",
    ReferenciaCreate,
    ReferenciaUpdate,
    ReferenciaOut,
)
