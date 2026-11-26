"""Rotas de autenticação (spec 002, design § Rotas). Públicas: estão na lista de rotas públicas
(design da 002, Decisões; teste de rotas protegidas da 003/T5). O logout exige o Bearer.

O refresh token vai num cookie `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` (R3.3) e
nunca no corpo; o access token vai no corpo, para o front guardar em memória.
"""

from typing import Annotated, Any, Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.core.errors import Forbidden, ServiceUnavailable, Unauthorized
from src.core.origem import origem_da_requisicao
from src.core.problem import PROBLEM_JSON
from src.modules.identity.api.deps import CurrentUser
from src.modules.identity.application import login as casos
from src.modules.identity.application.login import Falha, Identidade, Origem, TokensEmitidos
from src.modules.identity.application.login_ldap import Diretorio, entrar_por_ldap

router = APIRouter(prefix="/api/v1/auth", tags=["autenticação"])

COOKIE = "sgs_refresh"
CAMINHO_DO_COOKIE = "/api/v1/auth"
CABECALHO_ANTI_CSRF = "sgs"  # X-Requested-With (R3.6)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256, repr=False)
    provider: Literal["local", "ldap"] = Field(
        default="local", description="`ldap` confere a senha no diretório (spec 004, R2)."
    )


class LoginOut(BaseModel):
    mfa_required: bool
    mfa_enrollment_required: bool
    mfa_token: str | None = Field(default=None, description="Vale 5 minutos (R1.1).")
    access_token: str | None = Field(default=None, description="Só com 2FA desligado em dev.")
    expires_in: int | None = None


class MfaTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfa_token: str = Field(min_length=1, max_length=4096, repr=False)


class CodigoIn(MfaTokenIn):
    code: str = Field(pattern=r"^[0-9]{6}$", description="Código TOTP de 6 dígitos.")


class EnrollOut(BaseModel):
    otpauth_uri: str = Field(description="Para o QR code; mostrada uma única vez (R2.1).")


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 (esquema do cabeçalho, não é segredo)
    expires_in: int


_401 = {"description": "Credenciais, código ou token inválidos", "content": {PROBLEM_JSON: {}}}
_429 = {"description": "Limite de 10 tentativas por minuto por IP", "content": {PROBLEM_JSON: {}}}
_503 = {"description": "Diretório LDAP indisponível (spec 004)", "content": {PROBLEM_JSON: {}}}


def _origem(request: Request) -> Origem:
    """IP, User-Agent e request id pelo helper comum (013/T3), o mesmo das rotas de negócio."""
    origem = origem_da_requisicao(request)
    return Origem(ip=origem.ip, user_agent=origem.user_agent, request_id=origem.request_id)


def _deps(request: Request, sessao: Any) -> Identidade:
    estado = request.app.state
    return Identidade(
        usuarios=estado.repositorio_de_usuarios(sessao),
        estados=estado.repositorio_de_login(sessao),
        sessoes=estado.repositorio_de_sessoes(sessao),
        refresh=estado.repositorio_de_refresh(sessao),
        refresh_escrita=estado.escrita_de_refresh(sessao),
        revogacao=estado.revogacao_de_sessao(sessao),
        auditoria=estado.auditoria(sessao),
        tokens=estado.token_service,
        hasher=estado.hasher_de_senha,
        totp=estado.verificador_totp,
        cifra=estado.cifra_de_campo,
        gerar_id=estado.gerar_id,
        mfa_obrigatorio=estado.settings.mfa_obrigatorio,
        papeis=_PapeisPeloResolvedor(estado, sessao),
    )


class _PapeisPeloResolvedor:
    """`PapeisDoUsuario` (013/R1.4) sobre o resolvedor de permissões que a raiz de composição põe
    em `app.state` (o mesmo de `require`), na sessão da própria rota de login."""

    def __init__(self, estado: Any, sessao: Any) -> None:
        self._estado = estado
        self._sessao = sessao

    async def de(self, usuario_id: UUID) -> tuple[str, ...]:
        repositorio = self._estado.repositorio_de_permissoes(self._sessao)
        _, papeis = await self._estado.resolvedor_de_permissoes.resolver(repositorio, usuario_id)
        return tuple(papeis)


def _com_cookie(response: Response, tokens: TokensEmitidos) -> TokenOut:
    response.set_cookie(
        COOKIE,
        tokens.refresh_token,
        expires=tokens.refresh_expira_em,
        path=CAMINHO_DO_COOKIE,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


def _diretorio(request: Request, sessao: Any) -> Diretorio:
    estado = request.app.state
    return Diretorio(
        porta=estado.diretorio,
        repositorio=estado.repositorio_do_diretorio(sessao),
        mapeamentos=estado.repositorio_de_mapeamentos(sessao),
        atribuicoes=estado.repositorio_de_atribuicoes(sessao),
        permissoes=estado.repositorio_de_permissoes(sessao),
    )


def _falhou(falha: Falha) -> NoReturn:
    if falha.status == 503:
        raise ServiceUnavailable(falha.mensagem)
    if falha.status == 403:
        raise Forbidden(falha.mensagem)
    raise Unauthorized(falha.mensagem)


@router.post(
    "/login",
    summary="Login com usuário e senha",
    responses={401: _401, 429: _429, 503: _503},
)
async def entrar(
    request: Request,
    response: Response,
    corpo: LoginIn,
) -> LoginOut:
    """R1: responde o desafio do 2FA (`mfa_required` ou `mfa_enrollment_required`). Com
    `provider = "ldap"`, a senha é conferida no diretório (spec 004, R2)."""
    origem = _origem(request)
    request.app.state.limite_de_login.conferir(origem.ip or "desconhecido")
    async with request.app.state.sessoes() as sessao, sessao.begin():
        deps = _deps(request, sessao)
        if corpo.provider == "ldap":
            resultado = await entrar_por_ldap(
                corpo.username,
                corpo.password,
                origem=origem,
                deps=deps,
                diretorio=_diretorio(request, sessao),
            )
        else:
            resultado = await casos.entrar(corpo.username, corpo.password, origem=origem, deps=deps)
    if isinstance(resultado, Falha):
        _falhou(resultado)
    if resultado.tokens is not None:
        acesso = _com_cookie(response, resultado.tokens)
        return LoginOut(
            mfa_required=False,
            mfa_enrollment_required=False,
            access_token=acesso.access_token,
            expires_in=acesso.expires_in,
        )
    return LoginOut(
        mfa_required=resultado.mfa_required,
        mfa_enrollment_required=resultado.mfa_enrollment_required,
        mfa_token=resultado.mfa_token,
    )


@router.post("/mfa/enroll", summary="Iniciar o cadastro do 2FA", responses={401: _401})
async def cadastrar(request: Request, corpo: MfaTokenIn) -> EnrollOut:
    """R2.1, com o `mfa_token` de finalidade `enroll`."""
    async with request.app.state.sessoes() as sessao, sessao.begin():
        uri = await casos.cadastrar_mfa(corpo.mfa_token, deps=_deps(request, sessao))
    if isinstance(uri, Falha):
        _falhou(uri)
    return EnrollOut(otpauth_uri=uri)


@router.post("/mfa/confirm", summary="Confirmar o 2FA e entrar", responses={401: _401})
async def confirmar(
    request: Request,
    response: Response,
    corpo: CodigoIn,
) -> TokenOut:
    """R2.2: ativa o 2FA e emite access token e refresh (cookie)."""
    async with request.app.state.sessoes() as sessao, sessao.begin():
        resultado = await casos.confirmar_mfa(
            corpo.mfa_token,
            corpo.code,
            origem=_origem(request),
            deps=_deps(request, sessao),
        )
    if isinstance(resultado, Falha):
        _falhou(resultado)
    return _com_cookie(response, resultado)


@router.post("/mfa/verify", summary="Verificar o código do 2FA e entrar", responses={401: _401})
async def verificar(
    request: Request,
    response: Response,
    corpo: CodigoIn,
) -> TokenOut:
    """R2.3 a R2.6."""
    async with request.app.state.sessoes() as sessao, sessao.begin():
        resultado = await casos.verificar_mfa(
            corpo.mfa_token,
            corpo.code,
            origem=_origem(request),
            deps=_deps(request, sessao),
        )
    if isinstance(resultado, Falha):
        _falhou(resultado)
    return _com_cookie(response, resultado)


@router.post(
    "/refresh",
    summary="Renovar o access token (refresh rotativo)",
    responses={
        401: _401,
        403: {"description": "Falha no anti-CSRF", "content": {PROBLEM_JSON: {}}},
    },
)
async def renovar(
    request: Request,
    response: Response,
    sgs_refresh: Annotated[str | None, Cookie()] = None,
    x_requested_with: Annotated[str | None, Header()] = None,
    origin: Annotated[str | None, Header()] = None,
) -> TokenOut:
    """R3.4 a R3.6: exige `X-Requested-With: sgs` e `Origin` permitida (anti-CSRF)."""
    permitidas = request.app.state.settings.cors_origins
    if x_requested_with != CABECALHO_ANTI_CSRF or origin is None or origin not in permitidas:
        raise Forbidden("Requisição recusada (anti-CSRF).")
    if not sgs_refresh:
        raise Unauthorized("Sessão expirada.")
    async with request.app.state.sessoes() as sessao, sessao.begin():
        resultado = await casos.renovar(
            sgs_refresh, origem=_origem(request), deps=_deps(request, sessao)
        )
    if isinstance(resultado, Falha):
        response.delete_cookie(COOKIE, path=CAMINHO_DO_COOKIE)
        _falhou(resultado)
    return _com_cookie(response, resultado)


@router.post("/logout", status_code=204, summary="Sair (revoga a sessão)", responses={401: _401})
async def sair(
    request: Request,
    usuario: CurrentUser,
) -> Response:
    """R3.7: revoga a sessão e apaga o cookie."""
    async with request.app.state.sessoes() as sessao, sessao.begin():
        await casos.sair(
            usuario.id,
            usuario.sessao_id,
            origem=_origem(request),
            deps=_deps(request, sessao),
        )
    resposta = Response(status_code=204)
    resposta.delete_cookie(COOKIE, path=CAMINHO_DO_COOKIE)
    return resposta
