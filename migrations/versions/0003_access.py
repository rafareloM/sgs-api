"""access: catálogo de papéis e permissões do RBAC com escopo (spec 003, T1; R1.1 a R1.3).

Tabelas de docs/architecture/modelo-dados.md § 1 conforme o design da 003 § Modelo:
- `roles`, `permissions` e `role_permissions(max_scope)`, com a matriz de
  arquitetura-conceitual.md § 4 semeada aqui (R1.1, R1.2). Papel de sistema não é apagado nem
  pelo dono do banco (R1.3), e a API só lê o catálogo;
- `role_assignments` e `group_role_mappings`, vazias (as rotas vêm nas T7 e T8);
- os níveis de escopo do cadastro: `districts`, `technical_areas` e um stub de `health_units`
  (id, district_id, unit_type_id). A 0006 (spec 006) semeia, completa e põe as FKs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

from src.core.ids import uuid7

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Papéis de docs/architecture/arquitetura-conceitual.md § 2: código, nome e responsabilidade.
PAPEIS = {
    "ADMIN_TI": (
        "Administrador de TI",
        "Gerencia usuários locais, o mapeamento de grupos para papéis e a sincronização LDAP."
        " Não edita cadastro.",
    ),
    "GESTOR_DADOS": (
        "Gestor de Dados",
        "Governança central: edita qualquer unidade, define regras de validação, valida"
        " alterações e exporta relatórios.",
    ),
    "COORD_TECNICO": (
        "Coordenador Técnico",
        "Mantém os dados da sua área técnica, valida alterações propostas e exporta relatórios"
        " da área.",
    ),
    "TECNICO_DISTRITAL": (
        "Técnico do Distrito Sanitário",
        "Atualiza as unidades do seu distrito.",
    ),
    "GESTOR_UNIDADE": (
        "Gestor de Unidade",
        "Atualiza os dados da própria unidade apenas.",
    ),
    "DIRETORIA": (
        "Diretoria Executiva",
        "Leitura, dashboard e relatórios. Não altera dados.",
    ),
    "AUDITOR": (
        "Segurança da Informação",
        "Lê a trilha de auditoria e os eventos de acesso. Não altera dados.",
    ),
}

G, A, D, U = "global", "area", "distrito", "unidade"
ESCOPOS = (G, A, D, U)  # R1.2; em SQL, ('global', 'area', 'distrito', 'unidade')

# Matriz de arquitetura-conceitual.md § 4, na mesma orientação: uma linha por permissão, com o
# escopo máximo de cada papel que a tem. A linha `equipamento:write` / `servico:write` vira duas.
# `alteracao:*` é do workflow futuro (RF-04): a permissão existe, o fluxo não (003, fora do
# escopo). `relatorio:export` do AUDITOR é "G (só auditoria)": o recorte por tipo de relatório
# fica na spec 005.
MATRIZ: dict[str, tuple[str, dict[str, str]]] = {
    "unidade:read": (
        "Consultar unidades de saúde",
        {
            "GESTOR_DADOS": G,
            "COORD_TECNICO": G,
            "TECNICO_DISTRITAL": G,
            "GESTOR_UNIDADE": G,
            "DIRETORIA": G,
            "AUDITOR": G,
        },
    ),
    "unidade:create": ("Cadastrar unidade de saúde", {"GESTOR_DADOS": G, "COORD_TECNICO": A}),
    "unidade:update": (
        "Atualizar unidade de saúde",
        {"GESTOR_DADOS": G, "COORD_TECNICO": A, "TECNICO_DISTRITAL": D, "GESTOR_UNIDADE": U},
    ),
    "unidade:deactivate": ("Desativar unidade de saúde", {"GESTOR_DADOS": G}),
    "equipamento:write": (
        "Incluir, alterar e remover equipamentos",
        {"GESTOR_DADOS": G, "COORD_TECNICO": A, "TECNICO_DISTRITAL": D, "GESTOR_UNIDADE": U},
    ),
    "servico:write": (
        "Incluir, alterar e remover serviços",
        {"GESTOR_DADOS": G, "COORD_TECNICO": A, "TECNICO_DISTRITAL": D, "GESTOR_UNIDADE": U},
    ),
    "alteracao:propor": (
        "Propor alteração de cadastro (workflow futuro)",
        {"GESTOR_DADOS": G, "COORD_TECNICO": A, "TECNICO_DISTRITAL": D, "GESTOR_UNIDADE": U},
    ),
    "alteracao:validar": (
        "Validar alteração proposta (workflow futuro)",
        {"GESTOR_DADOS": G, "COORD_TECNICO": A},
    ),
    "regra_validacao:manage": ("Gerenciar regras de validação", {"GESTOR_DADOS": G}),
    "auditoria:read": (
        "Consultar a trilha de alterações",
        {
            "GESTOR_DADOS": G,
            "COORD_TECNICO": A,
            "TECNICO_DISTRITAL": D,
            "GESTOR_UNIDADE": U,
            "AUDITOR": G,
        },
    ),
    "auditoria:read_acessos": ("Consultar os eventos de acesso", {"ADMIN_TI": G, "AUDITOR": G}),
    "dashboard:read": (
        "Consultar os indicadores do dashboard",
        {
            "GESTOR_DADOS": G,
            "COORD_TECNICO": G,
            "TECNICO_DISTRITAL": G,
            "GESTOR_UNIDADE": G,
            "DIRETORIA": G,
        },
    ),
    "relatorio:export": (
        "Pedir exportação de relatório",
        {"GESTOR_DADOS": G, "COORD_TECNICO": A, "DIRETORIA": G, "AUDITOR": G},
    ),
    "relatorio:download": (
        "Baixar relatório exportado",
        {"GESTOR_DADOS": G, "COORD_TECNICO": A, "DIRETORIA": G, "AUDITOR": G},
    ),
    "usuario:manage": ("Gerenciar usuários locais", {"ADMIN_TI": G}),
    "papel:assign": ("Atribuir papéis e mapear grupos para papéis", {"ADMIN_TI": G}),
    "diretorio:sync": ("Disparar a sincronização do diretório", {"ADMIN_TI": G}),
}


def _timestamps() -> tuple[sa.Column[datetime], sa.Column[datetime]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def _escopo() -> tuple[sa.Column[str], sa.Column[str]]:
    # `scope_id` guarda o id do distrito, da área técnica (smallint) ou da unidade (uuid), em
    # texto; nulo quando o escopo é global (modelo-dados.md § 1). Por isso não há FK: a existência
    # do escopo é conferida na atribuição (R2.2).
    return (
        sa.Column("scope_type", sa.String(10), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=True),
    )


def _restricoes_de_escopo(tabela: str) -> tuple[sa.CheckConstraint, sa.CheckConstraint]:
    return (
        sa.CheckConstraint(f"scope_type IN {ESCOPOS}", name=op.f(f"ck_{tabela}_escopo_valido")),
        sa.CheckConstraint(
            "(scope_type = 'global') = (scope_id IS NULL)",
            name=op.f(f"ck_{tabela}_escopo_conforme_tipo"),
        ),
    )


def upgrade() -> None:
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.text("false")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    permissions = op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    role_permissions = op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid, nullable=False),
        sa.Column("permission_id", sa.Uuid, nullable=False),
        sa.Column("max_scope", sa.String(10), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_role_permissions_role_id_roles"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="fk_role_permissions_permission_id_permissions",
        ),
        sa.CheckConstraint(
            f"max_scope IN {ESCOPOS}", name=op.f("ck_role_permissions_escopo_maximo_valido")
        ),
    )

    ids_dos_papeis = {codigo: uuid7() for codigo in PAPEIS}
    ids_das_permissoes = {codigo: uuid7() for codigo in MATRIZ}
    op.bulk_insert(
        roles,
        [
            {
                "id": ids_dos_papeis[codigo],
                "code": codigo,
                "name": nome,
                "description": descricao,
                "is_system": True,
            }
            for codigo, (nome, descricao) in PAPEIS.items()
        ],
    )
    op.bulk_insert(
        permissions,
        [
            {"id": ids_das_permissoes[codigo], "code": codigo, "description": descricao}
            for codigo, (descricao, _) in MATRIZ.items()
        ],
    )
    op.bulk_insert(
        role_permissions,
        [
            {
                "role_id": ids_dos_papeis[papel],
                "permission_id": ids_das_permissoes[permissao],
                "max_scope": escopo,
            }
            for permissao, (_, escopos) in MATRIZ.items()
            for papel, escopo in escopos.items()
        ],
    )

    # R1.3: papel de sistema não é apagado, nem pelo dono do banco. Desmarcar `is_system` seria o
    # atalho para apagar depois, e TRUNCATE apaga sem disparar o trigger de linha.
    op.execute(
        """
        CREATE FUNCTION trg_roles_protect_system() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                IF EXISTS (SELECT 1 FROM roles WHERE is_system) THEN
                    RAISE EXCEPTION 'papel de sistema não pode ser apagado: TRUNCATE bloqueado';
                END IF;
                RETURN NULL;
            END IF;
            IF OLD.is_system THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'papel de sistema não pode ser apagado: %', OLD.code;
                ELSIF NOT NEW.is_system THEN
                    RAISE EXCEPTION 'papel de sistema não pode ser desmarcado: %', OLD.code;
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_roles_protect_system BEFORE UPDATE OR DELETE ON roles"
        " FOR EACH ROW EXECUTE FUNCTION trg_roles_protect_system()"
    )
    op.execute(
        "CREATE TRIGGER trg_roles_protect_system_truncate BEFORE TRUNCATE ON roles"
        " FOR EACH STATEMENT EXECUTE FUNCTION trg_roles_protect_system()"
    )
    # O catálogo nasce da migração (R1.1): a API só o lê.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON roles, permissions, role_permissions FROM sgs_app")

    # Níveis de escopo do cadastro (modelo-dados.md § 2). A 0006 semeia, completa e põe as FKs.
    op.create_table(
        "districts",
        sa.Column("id", sa.SmallInteger, nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_districts"),
        sa.UniqueConstraint("code", name="uq_districts_code"),
    )
    op.create_table(
        "technical_areas",
        sa.Column("id", sa.SmallInteger, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_technical_areas"),
        sa.UniqueConstraint("code", name="uq_technical_areas_code"),
    )
    op.create_table(
        "health_units",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("district_id", sa.SmallInteger, nullable=False),
        sa.Column("unit_type_id", sa.SmallInteger, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_health_units"),
    )

    op.create_table(
        "group_role_mappings",
        sa.Column("id", sa.Uuid, nullable=False),
        # Sem FK por enquanto: a tabela `groups` nasce na spec 004 (T1).
        sa.Column("group_id", sa.Uuid, nullable=False),
        sa.Column("role_id", sa.Uuid, nullable=False),
        *_escopo(),
        sa.Column("created_by", sa.Uuid, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_group_role_mappings"),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_group_role_mappings_role_id_roles"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_group_role_mappings_created_by_users"
        ),
        *_restricoes_de_escopo("group_role_mappings"),
    )
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("role_id", sa.Uuid, nullable=False),
        *_escopo(),
        sa.Column("origin", sa.String(10), nullable=False),
        sa.Column("group_mapping_id", sa.Uuid, nullable=True),
        sa.Column("granted_by", sa.Uuid, nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_role_assignments"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_role_assignments_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_role_assignments_role_id_roles"
        ),
        sa.ForeignKeyConstraint(
            ["group_mapping_id"],
            ["group_role_mappings.id"],
            name="fk_role_assignments_group_mapping_id_group_role_mappings",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["users.id"], name="fk_role_assignments_granted_by_users"
        ),
        *_restricoes_de_escopo("role_assignments"),
        sa.CheckConstraint(
            "origin IN ('direct', 'group')", name=op.f("ck_role_assignments_origem_valida")
        ),
        # Atribuição derivada aponta o mapeamento que a gerou; a direta não aponta nenhum.
        sa.CheckConstraint(
            "(origin = 'group') = (group_mapping_id IS NOT NULL)",
            name=op.f("ck_role_assignments_origem_conforme_mapeamento"),
        ),
    )
    op.create_index("ix_role_assignments_user_id", "role_assignments", ["user_id"])


def downgrade() -> None:
    op.drop_table("role_assignments")
    op.drop_table("group_role_mappings")
    op.drop_table("health_units")
    op.drop_table("technical_areas")
    op.drop_table("districts")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.execute("DROP FUNCTION trg_roles_protect_system()")
