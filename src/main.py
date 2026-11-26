"""Raiz de composição da API: cria o app e liga as camadas dos módulos."""

import asyncio
import contextlib
import functools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from typing import Any

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core import health
from src.core.config import AppEnv, Settings, SettingsError, load_settings
from src.core.crypto import FieldCipher
from src.core.db import create_engine, run_migrations
from src.core.fuso import agora_em_recife
from src.core.ids import uuid7
from src.core.limite import LimiteDeRequisicoes
from src.core.logging import configure_logging
from src.core.problem import install_error_handlers
from src.core.request_context import RequestContextMiddleware
from src.core.security_headers import SecurityHeadersMiddleware
from src.modules.access.api import rotas as acesso
from src.modules.access.application.permissoes import ResolvedorDePermissoes
from src.modules.access.infrastructure.repository import (
    SqlMembrosDeGrupo,
    SqlRepositorioDeAtribuicoes,
    SqlRepositorioDeMapeamentos,
    SqlRepositorioDePermissoes,
    SqlResolvedorDeUnidade,
)
from src.modules.audit.api import rotas as auditoria
from src.modules.audit.infrastructure.consultas import SqlConsultasDeAuditoria
from src.modules.audit.infrastructure.repository import SqlAuditStore
from src.modules.dashboard.api import rotas as dashboard
from src.modules.dashboard.infrastructure.consultas import SqlConsultasDashboard
from src.modules.identity.api import auth, diretorio, jwks
from src.modules.identity.api.sincronizacao import transacoes_da_sincronizacao
from src.modules.identity.application.agendamento import agendar, sincronizar_agendada
from src.modules.identity.application.sincronizacao import marcar_interrompidas
from src.modules.identity.domain.cron import Agenda, CronInvalido, analisar
from src.modules.identity.infrastructure.directory_repository import SqlDirectoryRepository
from src.modules.identity.infrastructure.ldap3_directory import Ldap3Directory, LdapConfig
from src.modules.identity.infrastructure.passwords import Argon2PasswordHasher
from src.modules.identity.infrastructure.repository import (
    SqlLoginStateRepository,
    SqlRefreshTokenRepository,
    SqlRefreshTokenWriter,
    SqlSessionRepository,
    SqlSessionRevoker,
    SqlUserRepository,
)
from src.modules.identity.infrastructure.tokens import JwtTokenService
from src.modules.identity.infrastructure.totp import PyotpVerificador
from src.modules.registry.api import referencias, unidades, vinculos
from src.modules.registry.infrastructure.repository import (
    SqlRepositorioDeReferencias,
    SqlRepositorioDeUnidades,
    SqlRepositorioDeVinculos,
)
from src.modules.reports.api import jwks as relatorios_jwks
from src.modules.reports.api import relatorios
from src.modules.reports.api.relatorios import transacoes_dos_relatorios
from src.modules.reports.application.gerar import Destino, Geracao
from src.modules.reports.application.gerar import marcar_interrompidos as relatorios_interrompidos
from src.modules.reports.infrastructure.assinatura import Es256AssinadorDeRelatorio
from src.modules.reports.infrastructure.consultas import SqlConsultasDeRelatorio
from src.modules.reports.infrastructure.generators import novo_gerador
from src.modules.reports.infrastructure.referencias import SqlReferenciasDosFiltros
from src.modules.reports.infrastructure.repository import SqlRepositorioDePedidos
from src.modules.reports.infrastructure.s3_storage import ConfiguracaoS3, S3ArmazenamentoDeObjetos


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    if settings.app_env is AppEnv.DEV and settings.database_migration_url is not None:
        # Em dev a subida aplica as migrações (R1.2); em test e prod elas são um passo à parte.
        await run_migrations(settings.database_migration_url.get_secret_value(), settings)
    agendador: asyncio.Task[None] | None = None
    if settings.ldap_url is not None:
        transacoes = transacoes_da_sincronizacao(app.state)
        # Spec 004, design § Fluxo, Sincronização, passo 6: o que ficou em andamento morreu
        # com o processo anterior (a API roda numa instância só).
        await marcar_interrompidas(transacoes=transacoes, agora=lambda: datetime.now(UTC))
        if app.state.agenda_do_diretorio is not None:  # LDAP_SYNC_CRON (R1.12)
            agendador = asyncio.create_task(
                agendar(
                    app.state.agenda_do_diretorio,
                    relogio=agora_em_recife,
                    esperar=asyncio.sleep,
                    rodar=functools.partial(
                        sincronizar_agendada,
                        diretorio=app.state.diretorio,
                        transacoes=transacoes,
                        gerar_id=app.state.gerar_id,
                        agora=lambda: datetime.now(UTC),
                    ),
                ),
                name="agendador-do-diretorio",
            )
    app.state.agendador_do_diretorio = agendador
    if app.state.geracao_de_relatorios is not None:
        # Spec 005, design § Geração e envio, passo 8: o que ficou pendente ou gerando morreu
        # com o processo anterior.
        await relatorios_interrompidos(
            transacoes=app.state.geracao_de_relatorios.transacoes,
            agora=lambda: datetime.now(UTC),
        )
    try:
        yield
    finally:
        if agendador is not None:
            agendador.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await agendador
        await app.state.engine.dispose()


def _agenda(settings: Settings) -> Agenda | None:
    """LDAP_SYNC_CRON no subconjunto aceito (004 design § Agendamento), ou a subida é recusada."""
    if not settings.ldap_sync_cron:
        return None
    try:
        return analisar(settings.ldap_sync_cron)
    except CronInvalido as erro:
        raise SettingsError(f"LDAP_SYNC_CRON: {erro}") from None


def _geracao_de_relatorios(settings: Settings, estado: Any) -> Geracao | None:
    """Spec 005: sem S3_BUCKET (ou sem chave de assinatura), a exportação fica desligada e o
    pedido e o download respondem 503 (R2.9). O `Settings` já recusou o que `prod` não aceita."""
    assinador = estado.assinador_de_relatorio
    if not settings.exportacao_ligada or assinador is None or settings.s3_bucket is None:
        return None
    configuracao = ConfiguracaoS3(
        bucket=settings.s3_bucket,
        regiao=settings.s3_region or "us-east-1",
        sse=settings.s3_sse,
        endpoint_url=settings.s3_endpoint_url,
        public_endpoint_url=settings.s3_endpoint_publico,
        ca_file=str(settings.s3_ca_file) if settings.s3_ca_file else None,
        addressing_style=settings.s3_addressing_style,
        assume_role_arn=settings.s3_assume_role_arn,
        external_id=settings.s3_external_id,
        kms_key_id=settings.s3_kms_key_id,
        access_key_id=_segredo(settings.s3_access_key_id),
        secret_access_key=_segredo(settings.s3_secret_access_key),
    )
    return Geracao(
        transacoes=transacoes_dos_relatorios(estado),
        consultas=SqlConsultasDeRelatorio(estado.engine),
        armazenamento=S3ArmazenamentoDeObjetos(configuracao),
        assinador=assinador,
        novo_gerador=novo_gerador,
        em_thread=anyio.to_thread.run_sync,
        destino=Destino(
            bucket=settings.s3_bucket,
            sse=settings.s3_sse,
            kms_key_id=settings.s3_kms_key_id,
            retencao=timedelta(days=settings.report_retention_days),
        ),
        agora=lambda: datetime.now(UTC),
    )


def _segredo(valor: SecretStr | None) -> str | None:
    return None if valor is None else valor.get_secret_value()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fábrica do app. Sem argumento, lê a configuração do ambiente (`uvicorn --factory`)."""
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    # Documentação OpenAPI só em dev e test (R6.3).
    public_docs = settings.app_env is not AppEnv.PROD
    app = FastAPI(
        title="SGS · API de Governança de Dados de Saúde",
        version=version("sgs-api"),
        lifespan=_lifespan,
        openapi_url="/openapi.json" if public_docs else None,
        docs_url="/docs" if public_docs else None,
        redoc_url="/redoc" if public_docs else None,
    )
    app.state.settings = settings
    # A engine só abre conexões quando usada; criar o app não exige banco no ar.
    app.state.engine = create_engine(settings.database_url.get_secret_value(), settings)
    app.state.sessoes = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.token_service = JwtTokenService.from_settings(settings)
    # Assinatura dos relatórios (005/R5): None sem REPORT_SIGNING_KEYS, e então nada é assinado.
    app.state.assinador_de_relatorio = Es256AssinadorDeRelatorio.from_settings(settings)
    # Fábricas de repositórios: recebem a sessão SQLAlchemy de quem as usa (a camada api não
    # importa a infrastructure; design da 002, Decisões).
    app.state.repositorio_de_usuarios = SqlUserRepository
    app.state.repositorio_de_sessoes = SqlSessionRepository
    app.state.repositorio_de_login = SqlLoginStateRepository
    app.state.repositorio_de_refresh = SqlRefreshTokenRepository
    app.state.escrita_de_refresh = SqlRefreshTokenWriter
    app.state.revogacao_de_sessao = SqlSessionRevoker
    # Login local (spec 002): hasher Argon2id, TOTP, cifra do segredo e limite por IP (R1.5).
    app.state.hasher_de_senha = Argon2PasswordHasher()
    app.state.verificador_totp = PyotpVerificador()
    app.state.cifra_de_campo = FieldCipher(
        settings.chaves_de_cifra, active_version=settings.crypto_active_key or 0
    )
    app.state.gerar_id = uuid7
    app.state.limite_de_login = LimiteDeRequisicoes("10/minute")
    app.state.repositorio_de_permissoes = SqlRepositorioDePermissoes
    app.state.repositorio_de_atribuicoes = SqlRepositorioDeAtribuicoes
    app.state.repositorio_de_mapeamentos = SqlRepositorioDeMapeamentos
    app.state.repositorio_do_diretorio = SqlDirectoryRepository
    # Spec 004: sem LDAP_URL, o LDAP fica desligado (login LDAP e sincronização respondem 503).
    ldap = LdapConfig.from_settings(settings)
    app.state.diretorio = None if ldap is None else Ldap3Directory(ldap)
    app.state.agenda_do_diretorio = _agenda(settings) if ldap is not None else None
    # Membros dos grupos do diretório: `user_groups` com conta ativa (004/T4; 003/R3.1).
    app.state.membros_de_grupo = SqlMembrosDeGrupo
    app.state.auditoria = SqlAuditStore
    app.state.consultas_auditoria = SqlConsultasDeAuditoria
    app.state.repositorio_de_unidades = SqlRepositorioDeUnidades
    app.state.repositorio_de_vinculos = SqlRepositorioDeVinculos
    app.state.repositorio_de_referencias = SqlRepositorioDeReferencias
    app.state.consultas_dashboard = SqlConsultasDashboard
    # Relatórios (spec 005): pedidos e conferência dos filtros sobre a sessão da requisição; a
    # geração em segundo plano, com o S3, só com S3_BUCKET.
    app.state.repositorio_de_pedidos = SqlRepositorioDePedidos
    app.state.referencias_dos_filtros = SqlReferenciasDosFiltros
    app.state.geracao_de_relatorios = _geracao_de_relatorios(settings, app.state)
    # Um resolvedor por processo: o cache de permissões é dele (design da 003, passo 3).
    app.state.resolvedor_de_permissoes = ResolvedorDePermissoes()
    # `ResourceRef.tipo` → fábrica do `ResolvedorDeAlvo` daquele tipo de recurso (design da 003,
    # § Verificação).
    app.state.resolvedores_de_alvo = {"unidade": SqlResolvedorDeUnidade}
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(jwks.router)
    app.include_router(relatorios_jwks.router)
    app.include_router(auth.router)
    app.include_router(acesso.router)
    app.include_router(diretorio.router)
    app.include_router(unidades.router)
    app.include_router(vinculos.router)
    app.include_router(referencias.router)
    app.include_router(dashboard.router)
    app.include_router(dashboard.painel)
    app.include_router(auditoria.router)
    app.include_router(relatorios.router)

    # O último middleware adicionado é o mais externo: contexto > cabeçalhos > CORS > rotas.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),  # só as origens configuradas (R6.2)
        allow_credentials=True,  # o refresh token da 002 viaja em cookie
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    return app
