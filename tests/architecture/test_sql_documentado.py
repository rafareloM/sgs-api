"""SQL escrito à mão documentado e com nomes da convenção (spec 011, T20; ADR-0009).

Cobre os dois lugares do design da 011 § Onde fica o SQL: o DDL das migrações
(`migrations/sql/<revisão>/NN_<nome>.sql`) e as consultas dos módulos
(`src/modules/<módulo>/infrastructure/sql/<nome>.sql`). O script de primeira subida do compose
(`docker/postgres/init/`) não é SQL da disciplina e fica de fora.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
DDL = RAIZ / "migrations" / "sql"
MODULOS = RAIZ / "src" / "modules"
TESTES_DE_INTEGRACAO = RAIZ / "tests" / "integration"

ARQUIVOS_DDL = sorted(DDL.rglob("*.sql"))
ARQUIVOS_CONSULTA = sorted(MODULOS.glob("*/infrastructure/sql/*.sql"))
ARQUIVOS = ARQUIVOS_DDL + ARQUIVOS_CONSULTA

ROTULOS = ("Objetivo", "Justificativa", "Uso", "Requisito")
REQUISITO = re.compile(r"\b\d{3}/R\d+(\.\d+)?\b")

PREFIXOS = {"INDEX": "ix_", "VIEW": "vw_", "PROCEDURE": "sp_", "TRIGGER": "trg_"}
CRIACAO = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:UNIQUE\s+)?"
    r"(INDEX|VIEW|FUNCTION|PROCEDURE|TRIGGER|TABLE|ROLE)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
# "Sem nomes como `x1` ou `a1`" (011/R11.4): letra seguida só de dígitos.
NOME_SEM_SIGNIFICADO = re.compile(r"\b[a-z]{1,2}\d+\b", re.IGNORECASE)

# design da 011 § Fluxo, "Escopo em SQL explícito"; comparado sem diferença de espaços.
FRAGMENTO_DE_ESCOPO = (
    "(:scope_global OR technical_area_id = ANY(CAST(:scope_areas AS smallint[]))"
    " OR district_id = ANY(CAST(:scope_districts AS smallint[]))"
    " OR unit_id = ANY(CAST(:scope_units AS uuid[])))"
)
# Lê o cadastro (tem escopo); as tabelas de referência não têm.
LE_O_CADASTRO = re.compile(r"\b(health_units|equipments|services|vw_[a-z_]+)\b")

# Todo índice escrito à mão (011/R1.4, "cada índice"; 011/T9 e revisão do /implement-spec) → o
# nome que aparece no plano: o próprio ou, no log particionado, o que o PostgreSQL cria em cada
# partição a partir dele.
INDICES_COM_PLANO = {
    "ix_audit_log_entity": "ix_audit_log_entity",
    "ix_services_unit_id": "ix_services_unit_id",
    "ix_health_units_cnes": "ix_health_units_cnes",
    "ix_health_units_district_id_name_normalized": "ix_health_units_district_id_name_normalized",
    "ix_db_change_log_occurred_at": "db_change_log_y<AAAA>m<MM>_occurred_at_idx",
}
# Índices que o planejador não usa com o volume de demonstração: o cabeçalho traz o plano e diz
# isso (011, "Perguntas em aberto", R1.4).
INDICES_SEM_USO_COMPROVADO = {"ix_health_units_name_normalized_trgm"}


def _relativo(arquivo: Path) -> str:
    return arquivo.relative_to(RAIZ).as_posix()


def _cabecalho(arquivo: Path) -> str:
    """Os comentários `--` do começo do arquivo, até a primeira linha de SQL."""
    linhas = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if linha.startswith("--"):
            linhas.append(linha)
        elif linha.strip():
            break
    return "\n".join(linhas)


def _corpo(arquivo: Path) -> str:
    """O SQL sem comentários `--` e sem strings, para procurar nomes."""
    sem_comentario = re.sub(r"--[^\n]*", "", arquivo.read_text(encoding="utf-8"))
    return re.sub(r"'(?:[^']|'')*'", "''", sem_comentario)


def _sem_espacos(texto: str) -> str:
    return re.sub(r"\s+", "", texto)


def test_ha_sql_nos_dois_lugares() -> None:
    """011/R11.1: as regras abaixo não passam por falta de arquivo."""
    assert len(ARQUIVOS_DDL) > 20
    assert len(ARQUIVOS_CONSULTA) > 20


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=_relativo)
def test_todo_sql_tem_cabecalho_com_objetivo_justificativa_uso_e_requisito(
    arquivo: Path,
) -> None:
    """011/R11.1: o cabeçalho explica objetivo, justificativa semântica, quem usa e requisito."""
    cabecalho = _cabecalho(arquivo)

    ausentes = [r for r in ROTULOS if not re.search(rf"^--\s*{r}\w*\b[^\n]*:", cabecalho, re.M)]
    assert not ausentes, f"{_relativo(arquivo)}: cabeçalho sem {ausentes}"
    requisitos = cabecalho[cabecalho.index("-- Requisito") :]
    assert REQUISITO.search(requisitos), f"{_relativo(arquivo)}: requisito sem `NNN/Rx.y`"


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=_relativo)
def test_nomes_de_arquivo_seguem_a_convencao(arquivo: Path) -> None:
    """011/R11.4: nomes em inglês, minúsculas com `_`; o DDL numerado na ordem da revisão."""
    padrao = r"\d{2}_[a-z][a-z0-9_]+\.sql" if arquivo in ARQUIVOS_DDL else r"[a-z][a-z0-9_]+\.sql"
    assert re.fullmatch(padrao, arquivo.name), _relativo(arquivo)
    assert not NOME_SEM_SIGNIFICADO.search(arquivo.stem.lstrip("0123456789_")), _relativo(arquivo)


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=_relativo)
def test_sql_nao_usa_nomes_sem_significado(arquivo: Path) -> None:
    """011/R11.4: nenhum identificador como `x1` ou `a1` (aliases de uma letra são permitidos)."""
    achados = NOME_SEM_SIGNIFICADO.findall(_corpo(arquivo))
    assert not achados, f"{_relativo(arquivo)}: {achados}"


@pytest.mark.parametrize("arquivo", ARQUIVOS_DDL, ids=_relativo)
def test_objetos_criados_tem_o_prefixo_do_tipo(arquivo: Path) -> None:
    """011/R11.4: `ix_` índice, `vw_` view, `fn_` função, `sp_` procedimento, `trg_` trigger; a
    função de trigger tem o nome do trigger (design da 011 § Convenção de nomes).
    """
    corpo = _corpo(arquivo)
    for tipo, nome in CRIACAO.findall(corpo):
        tipo = tipo.upper()
        if tipo in PREFIXOS:
            assert nome.startswith(PREFIXOS[tipo]), f"{_relativo(arquivo)}: {tipo} {nome}"
        elif tipo == "FUNCTION":
            de_trigger = re.search(r"\bRETURNS\s+trigger\b", corpo, re.IGNORECASE)
            prefixo = "trg_" if de_trigger else "fn_"
            assert nome.startswith(prefixo), f"{_relativo(arquivo)}: FUNCTION {nome}"


CONSULTAS_DO_DASHBOARD = sorted((MODULOS / "dashboard" / "infrastructure" / "sql").glob("*.sql"))
CONSULTAS_COM_ESCOPO = [c for c in CONSULTAS_DO_DASHBOARD if LE_O_CADASTRO.search(_corpo(c))]


def test_so_as_conferencias_de_filtro_ficam_sem_escopo() -> None:
    """011/R2.5, R2.9: as conferências de filtro leem só tabelas de referência, que não têm
    escopo, e ficam isentas do fragmento (achado da 011/T11). Qualquer outra consulta do
    `dashboard` lê o cadastro.
    """
    isentas = {c.name for c in CONSULTAS_DO_DASHBOARD} - {c.name for c in CONSULTAS_COM_ESCOPO}
    assert isentas == {"district_exists.sql", "unit_type_exists.sql"}


@pytest.mark.parametrize("arquivo", CONSULTAS_COM_ESCOPO, ids=_relativo)
def test_consulta_do_dashboard_que_le_o_cadastro_tem_o_fragmento_de_escopo(
    arquivo: Path,
) -> None:
    """011/R2.5: toda consulta do `dashboard` sobre o cadastro aplica o escopo de leitura pelo
    fragmento fixo, com o escopo só como parâmetro.
    """
    assert _sem_espacos(FRAGMENTO_DE_ESCOPO) in _sem_espacos(_corpo(arquivo)), _relativo(arquivo)


def _arquivo_que_cria(nome: str) -> Path:
    for arquivo in ARQUIVOS_DDL:
        if any(criado == nome for _, criado in CRIACAO.findall(_corpo(arquivo))):
            return arquivo
    raise AssertionError(f"nenhum arquivo cria {nome}")


def test_todo_indice_criado_tem_regra_de_plano() -> None:
    """011/R1.4: nenhum índice escrito à mão fica fora das regras abaixo."""
    criados = {
        nome
        for arquivo in ARQUIVOS_DDL
        for tipo, nome in CRIACAO.findall(_corpo(arquivo))
        if tipo.upper() == "INDEX"
    }
    assert criados == set(INDICES_COM_PLANO) | INDICES_SEM_USO_COMPROVADO


@pytest.mark.parametrize("indice", sorted(INDICES_COM_PLANO))
def test_indice_documenta_o_plano_que_comprova_o_uso(indice: str) -> None:
    """011/R1.4: o índice cita a consulta ou view que o usa e o plano de execução da prova."""
    cabecalho = _cabecalho(_arquivo_que_cria(indice))
    no_plano = re.escape(INDICES_COM_PLANO[indice])

    assert "EXPLAIN" in cabecalho
    assert re.search(rf"Index Scan (using|on) {no_plano}\b", cabecalho)
    assert "tests/integration/db/test_indices.py" in cabecalho


@pytest.mark.parametrize("indice", sorted(INDICES_SEM_USO_COMPROVADO))
def test_indice_sem_uso_comprovado_registra_o_plano_e_diz_isso(indice: str) -> None:
    """011/R1.4: o índice que o planejador não usa com o volume de teste registra o plano real e
    diz que o uso não foi comprovado, sem forçar o plano."""
    cabecalho = _cabecalho(_arquivo_que_cria(indice))

    assert "EXPLAIN" in cabecalho
    assert "Sem uso comprovado" in cabecalho
    assert "`enable_seqscan` no padrão" in cabecalho
    assert "tests/integration/db/test_indices.py" in cabecalho


def _objetos_da_0011() -> list[str]:
    nomes = {
        nome
        for arquivo in ARQUIVOS_DDL
        if arquivo.parent.name.startswith("0011")
        for _, nome in CRIACAO.findall(_corpo(arquivo))
    }
    return sorted(nomes)


def _texto_dos_testes_de_integracao() -> str:
    return "\n".join(
        arquivo.read_text(encoding="utf-8") for arquivo in TESTES_DE_INTEGRACAO.rglob("*.py")
    )


def test_ha_objetos_na_0011() -> None:
    """011/R11.5: a regra abaixo não passa por falta de objeto."""
    assert {"vw_unit_inventory", "sp_deactivate_unit", "trg_registry_change_log"} <= set(
        _objetos_da_0011()
    )


@pytest.mark.parametrize("objeto", _objetos_da_0011())
def test_todo_objeto_da_0011_e_citado_num_teste_de_integracao(objeto: str) -> None:
    """011/R11.5: cada objeto criado nas revisões da 0011 tem teste contra o PostgreSQL."""
    assert re.search(rf"\b{objeto}\b", _texto_dos_testes_de_integracao()), objeto
