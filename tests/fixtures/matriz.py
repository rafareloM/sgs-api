"""Matriz de papéis e permissões esperada pelos testes (spec 003).

Copiada à mão de docs/architecture/arquitetura-conceitual.md § 4, num lugar só: os testes conferem
o domínio, a resolução de permissões e a semeadura da 0003 contra o documento, e não contra a
própria migração.
"""

PAPEIS = (
    "ADMIN_TI",
    "GESTOR_DADOS",
    "COORD_TECNICO",
    "TECNICO_DISTRITAL",
    "GESTOR_UNIDADE",
    "DIRETORIA",
    "AUDITOR",
)

# G = global · A = na sua área técnica · D = no seu distrito · U = na sua unidade
# - = sem permissão. Colunas na ordem de PAPEIS. `equipamento:write` e `servico:write` são linhas
# separadas. O AUDITOR exporta "G (só auditoria)": restrição do tipo de relatório (spec 005), não
# de escopo.
MATRIZ: dict[str, tuple[str, ...]] = {
    "unidade:read":           ("-", "G", "G", "G", "G", "G", "G"),
    "unidade:create":         ("-", "G", "A", "-", "-", "-", "-"),
    "unidade:update":         ("-", "G", "A", "D", "U", "-", "-"),
    "unidade:deactivate":     ("-", "G", "-", "-", "-", "-", "-"),
    "equipamento:write":      ("-", "G", "A", "D", "U", "-", "-"),
    "servico:write":          ("-", "G", "A", "D", "U", "-", "-"),
    "alteracao:propor":       ("-", "G", "A", "D", "U", "-", "-"),
    "alteracao:validar":      ("-", "G", "A", "-", "-", "-", "-"),
    "regra_validacao:manage": ("-", "G", "-", "-", "-", "-", "-"),
    "auditoria:read":         ("-", "G", "A", "D", "U", "-", "G"),
    "auditoria:read_acessos": ("G", "-", "-", "-", "-", "-", "G"),
    "dashboard:read":         ("-", "G", "G", "G", "G", "G", "-"),
    "relatorio:export":       ("-", "G", "A", "-", "-", "G", "G"),
    "relatorio:download":     ("-", "G", "A", "-", "-", "G", "G"),
    "usuario:manage":         ("G", "-", "-", "-", "-", "-", "-"),
    "papel:assign":           ("G", "-", "-", "-", "-", "-", "-"),
    "diretorio:sync":         ("G", "-", "-", "-", "-", "-", "-"),
}  # fmt: skip

# A letra da matriz → `role_permissions.max_scope`, como a 0003 grava.
ESCOPO_MAXIMO_DA_LETRA = {"G": "global", "A": "area", "D": "distrito", "U": "unidade"}


def escopos_maximos(papel: str) -> dict[str, str]:
    """As permissões do papel (as células preenchidas da coluna dele) → `max_scope`."""
    coluna = PAPEIS.index(papel)
    return {
        permissao: ESCOPO_MAXIMO_DA_LETRA[linha[coluna]]
        for permissao, linha in MATRIZ.items()
        if linha[coluna] != "-"
    }
