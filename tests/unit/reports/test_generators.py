"""Geradores CSV e XLSX (005/T2; design § Conteúdo, § Geração e envio, passo 2)."""

import hashlib
import io
import re
import tempfile
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

from src.modules.reports.domain.arquivo import (
    LIMITE_DE_LINHAS,
    MENSAGEM_GRANDE_DEMAIS,
    GeradorDeArquivo,
    RelatorioGrandeDemais,
)
from src.modules.reports.domain.colunas import (
    COLUNAS_INVENTARIO_UNIDADES,
    COLUNAS_POR_TIPO,
    COLUNAS_TRILHA_AUDITORIA,
    Coluna,
    TipoColuna,
    neutralizar,
)
from src.modules.reports.infrastructure.generators import (
    GeradorCsv,
    GeradorXlsx,
    novo_gerador,
)

TEXTO = TipoColuna.TEXTO
NUMERO = TipoColuna.NUMERO
DATA = TipoColuna.DATA

COLUNAS = (Coluna("Nome", TEXTO), Coluna("Quantidade", NUMERO), Coluna("Instante", DATA))
RECIFE = timezone(timedelta(hours=-3))
PERIGOSOS = ("=1+1", "+55 81", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd")


Novo = Callable[..., GeradorDeArquivo]


@pytest.fixture
def novo() -> Iterator[Novo]:
    """`novo_gerador` com o `descartar` no fim, como o caso de uso faz num `finally`."""
    criados: list[GeradorDeArquivo] = []

    def criar(*args: Any, **kwargs: Any) -> GeradorDeArquivo:
        gerador = novo_gerador(*args, **kwargs)
        criados.append(gerador)
        return gerador

    yield criar
    for gerador in criados:
        gerador.descartar()


def _csv(colunas: Sequence[Coluna], *lotes: Sequence[Sequence[object]]) -> bytes:
    destino = io.BytesIO()
    gerador = GeradorCsv(destino, colunas)
    for lote in lotes:
        gerador.escrever(lote)
    gerador.finalizar()
    return destino.getvalue()


def _xlsx(colunas: Sequence[Coluna], *lotes: Sequence[Sequence[object]]) -> bytes:
    destino = io.BytesIO()
    gerador = GeradorXlsx(destino, colunas)
    for lote in lotes:
        gerador.escrever(lote)
    gerador.finalizar()
    return destino.getvalue()


def _linhas_xlsx(dados: bytes) -> list[list[object]]:
    planilha = load_workbook(io.BytesIO(dados)).active
    assert planilha is not None
    return [[celula.value for celula in linha] for linha in planilha.iter_rows()]


def test_csv_utf8_com_bom_ponto_e_virgula_e_crlf() -> None:
    """005/R4.1"""
    dados = _csv(COLUNAS, [["USF Alto do Céu", 3, None]])

    assert dados.startswith(b"\xef\xbb\xbf")
    assert dados[3:].decode("utf-8") == "Nome;Quantidade;Instante\r\nUSF Alto do Céu;3;\r\n"


def test_csv_campo_com_separador_ou_quebra_vai_entre_aspas() -> None:
    """005/R4.1: `csv.QUOTE_MINIMAL`, para o Excel não partir a célula."""
    dados = _csv((Coluna("Nome"),), [["USF; Alto\r\ndo Céu"]])

    assert dados[3:].decode("utf-8") == 'Nome\r\n"USF; Alto\r\ndo Céu"\r\n'


@pytest.mark.parametrize("valor", PERIGOSOS)
def test_neutralizar_poe_aspa_simples_em_texto_que_o_excel_le_como_formula(valor: str) -> None:
    """005/R4.2"""
    assert neutralizar(valor) == "'" + valor


@pytest.mark.parametrize("valor", ["USF Alto do Céu", "", "1000001", "a=b", "'=1+1"])
def test_neutralizar_nao_mexe_em_texto_comum(valor: str) -> None:
    """005/R4.2: só o primeiro caractere decide."""
    assert neutralizar(valor) == valor


@pytest.mark.parametrize("valor", PERIGOSOS)
def test_csv_neutraliza_celula_de_texto(valor: str) -> None:
    """005/R4.2"""
    destino = io.BytesIO()
    gerador = GeradorCsv(destino, (Coluna("Nome"),))
    gerador.escrever([[valor]])
    gerador.finalizar()

    linha = destino.getvalue()[3:].decode("utf-8").split("\r\n", 1)[1]
    assert linha.lstrip('"').startswith("'" + valor[0])


def test_csv_numeros_e_datas_saem_sem_aspa_simples() -> None:
    """005/R4.2: colunas numéricas e de data são formatadas pelo gerador, sem neutralização."""
    instante = datetime(2026, 11, 25, 23, 50, 19, tzinfo=RECIFE)
    dados = _csv(
        (Coluna("A", NUMERO), Coluna("B", NUMERO), Coluna("C", DATA), Coluna("D", DATA)),
        [[-5, Decimal("-1.5"), instante, date(2026, 11, 25)]],
    )

    assert dados[3:].decode("utf-8").split("\r\n")[1] == (
        "-5;-1.5;2026-11-25 23:50:19-03:00;2026-11-25"
    )


def test_texto_em_coluna_numerica_ou_de_data_tambem_e_neutralizado() -> None:
    """005/R4.2: só número e data de verdade escapam da neutralização."""
    colunas = (Coluna("A", NUMERO), Coluna("B", DATA), Coluna("C", NUMERO))
    dados = _csv(colunas, [["=1+1", "@x", True]])

    assert dados[3:].decode("utf-8").split("\r\n")[1] == "'=1+1;'@x;True"


def test_xlsx_nenhuma_celula_e_formula_e_texto_perigoso_ganha_aspa() -> None:
    """005/R4.2: o openpyxl grava como fórmula todo texto que começa por `=`."""
    dados = _xlsx((Coluna("Nome"), Coluna("Qtd", NUMERO)), [[valor, -1] for valor in PERIGOSOS])

    planilha = load_workbook(io.BytesIO(dados)).active
    assert planilha is not None
    celulas = [celula for linha in planilha.iter_rows() for celula in linha]
    assert celulas
    assert all(celula.data_type != "f" for celula in celulas)
    linhas = _linhas_xlsx(dados)
    assert linhas[0] == ["Nome", "Qtd"]
    # O XML normaliza `\r` para `\n` na leitura; a aspa continua na frente.
    assert linhas[1:] == [["'" + valor.replace("\r", "\n"), -1] for valor in PERIGOSOS]


def test_xlsx_texto_vai_como_texto_explicito() -> None:
    """005/R4.2: código de erro do Excel (`#REF!`) e número em coluna de texto ficam texto."""
    dados = _xlsx((Coluna("A"), Coluna("CNES")), [["#REF!", "0001234"]])

    planilha = load_workbook(io.BytesIO(dados)).active
    assert planilha is not None
    linha = next(planilha.iter_rows(min_row=2))
    assert [(c.value, c.data_type) for c in linha] == [("#REF!", "s"), ("0001234", "s")]


def test_xlsx_numero_e_numero_e_data_sai_como_no_csv() -> None:
    """005/R4.2: o arquivo diz o mesmo nos dois formatos; número continua somável no Excel."""
    instante = datetime(2026, 11, 25, 23, 50, 19, tzinfo=RECIFE)
    dados = _xlsx(COLUNAS, [["USF", 7, instante], [None, None, None], ["fim", 0, None]])

    planilha = load_workbook(io.BytesIO(dados)).active
    assert planilha is not None
    linha = next(planilha.iter_rows(min_row=2))
    assert [(c.value, c.data_type) for c in linha] == [
        ("USF", "s"),
        (7, "n"),
        ("2026-11-25 23:50:19-03:00", "s"),
    ]
    assert _linhas_xlsx(dados)[2:] == [[None, None, None], ["fim", 0, None]]


@pytest.mark.parametrize("caractere", ["\x01", "￾", "￿", "\ud800"])
def test_xlsx_troca_caractere_que_o_xml_nao_aceita_em_vez_de_corromper_o_arquivo(
    caractere: str,
) -> None:
    """005/T2: o XML 1.0 não aceita controles, U+FFFE, U+FFFF nem surrogate solto. Um valor só
    não pode derrubar a exportação nem gerar um XLSX que não abre, assinado e enviado."""
    dados = _xlsx((Coluna("Nome"),), [[f"USF{caractere}Alto"]])

    assert _linhas_xlsx(dados)[1] == ["USF�Alto"]


@pytest.mark.parametrize("formato", ["csv", "xlsx"])
@pytest.mark.parametrize(
    "instante",
    [
        datetime(2026, 11, 26, 2, 50, 19, tzinfo=UTC),
        datetime(2026, 11, 26, 2, 50, 19),  # noqa: DTZ001 - sem fuso de propósito
    ],
    ids=["utc", "sem-fuso"],
)
def test_instante_sai_no_fuso_de_recife(formato: str, instante: datetime, novo: Novo) -> None:
    """005/T2: design § Conteúdo, Trilha: "instante (fuso de Recife)". O banco devolve UTC, e um
    instante sem fuso é UTC, como em `src.core.fuso.em_recife` (008/R1.2)."""
    destino = io.BytesIO()
    gerador = novo(formato, destino, (Coluna("Instante", DATA),))
    gerador.escrever([[instante]])
    gerador.finalizar()

    valor: object
    if formato == "csv":
        valor = destino.getvalue()[3:].decode("utf-8").split("\r\n")[1]
    else:
        valor = _linhas_xlsx(destino.getvalue())[1][0]
    assert valor == "2026-11-25 23:50:19-03:00"


@pytest.mark.parametrize("formato", ["csv", "xlsx"])
def test_sha256_e_tamanho_calculados_durante_a_escrita_conferem_com_o_arquivo(
    formato: str, novo: Novo
) -> None:
    """005/R2.3: o hash enviado no `ChecksumSHA256` e assinado (R5.1) é o do arquivo inteiro."""
    destino = io.BytesIO()
    gerador = novo(formato, destino, COLUNAS)
    lote = [[f"unidade {i}", i, datetime(2026, 1, 1, tzinfo=UTC)] for i in range(1_000)]
    gerador.escrever(lote)
    gerador.escrever(lote)

    arquivo = gerador.finalizar()

    assert arquivo.sha256 == hashlib.sha256(destino.getvalue()).digest()
    assert arquivo.tamanho == len(destino.getvalue())
    assert arquivo.linhas == 2_000


@pytest.mark.parametrize("formato", ["csv", "xlsx"])
def test_limite_de_linhas_aceita_o_limite_e_recusa_a_seguinte(formato: str, novo: Novo) -> None:
    """005/T2: acima do limite, a geração falha com a mensagem do design (Geração, passo 2)."""
    no_limite = novo(formato, io.BytesIO(), COLUNAS, limite=2)
    no_limite.escrever([["a", 1, None], ["b", 2, None]])
    assert no_limite.finalizar().linhas == 2

    acima = novo(formato, io.BytesIO(), COLUNAS, limite=2)
    acima.escrever([["a", 1, None]])
    with pytest.raises(RelatorioGrandeDemais) as erro:
        acima.escrever([["b", 2, None], ["c", 3, None]])
    assert str(erro.value) == MENSAGEM_GRANDE_DEMAIS


@pytest.mark.parametrize("finalizado", [False, True])
def test_descartar_apaga_o_temporario_do_xlsx(
    finalizado: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """005/T2: falha no meio da geração não deixa a planilha num temporário até a API parar."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    gerador = novo_gerador("xlsx", io.BytesIO(), COLUNAS, limite=1)
    gerador.escrever([["a", 1, None]])
    assert list(tmp_path.glob("openpyxl.*"))
    if finalizado:
        gerador.finalizar()
    else:
        with pytest.raises(RelatorioGrandeDemais):
            gerador.escrever([["b", 2, None]])

    gerador.descartar()
    gerador.descartar()

    assert not list(tmp_path.glob("openpyxl.*"))


def test_limite_padrao_cabe_numa_planilha_do_excel() -> None:
    """005/T2: 1.000.000 de linhas mais o cabeçalho cabem no 1.048.576 do XLSX."""
    assert LIMITE_DE_LINHAS == 1_000_000


@pytest.mark.parametrize("formato", ["csv", "xlsx"])
def test_linha_com_quantidade_errada_de_valores_e_recusada(formato: str, novo: Novo) -> None:
    """005/T2: uma coluna a menos deslocaria todas as outras."""
    gerador = novo(formato, io.BytesIO(), COLUNAS)

    with pytest.raises(ValueError, match="3 colunas"):
        gerador.escrever([["só o nome", 1]])


def test_formato_desconhecido_e_recusado() -> None:
    """005/R1.2: só `csv` e `xlsx`."""
    with pytest.raises(ValueError, match="pdf"):
        novo_gerador("pdf", io.BytesIO(), COLUNAS)


@pytest.mark.parametrize(
    ("formato", "content_type", "extensao"),
    [
        ("csv", "text/csv; charset=utf-8", "csv"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    ],
)
def test_cada_formato_informa_content_type_e_extensao(
    formato: str, content_type: str, extensao: str, novo: Novo
) -> None:
    """005/R1.2, R2.4: a chave termina em `.{formato}` e o objeto vai com o tipo certo."""
    gerador = novo(formato, io.BytesIO(), COLUNAS)

    assert (gerador.content_type, gerador.extensao) == (content_type, extensao)


def test_os_dois_tipos_de_relatorio_tem_colunas() -> None:
    """005/R1.2"""
    assert set(COLUNAS_POR_TIPO) == {"inventario_unidades", "trilha_auditoria"}
    assert COLUNAS_POR_TIPO["inventario_unidades"] == COLUNAS_INVENTARIO_UNIDADES
    assert COLUNAS_POR_TIPO["trilha_auditoria"] == COLUNAS_TRILHA_AUDITORIA


def test_cnes_e_texto_e_contagens_sao_numeros_no_inventario() -> None:
    """005/R1.2: o CNES mantém os zeros à esquerda; as contagens somam no Excel."""
    tipos = {coluna.nome: coluna.tipo for coluna in COLUNAS_INVENTARIO_UNIDADES}

    assert tipos["CNES"] is TEXTO
    assert [nome for nome, tipo in tipos.items() if tipo is NUMERO] == [
        "Equipamentos",
        "Serviços",
        "Serviços fora do CNES",
    ]


def test_colunas_da_trilha_sem_dado_de_acesso() -> None:
    """005/R4.3: sem `metadata`, IP, User-Agent nem sessão (design § Conteúdo, Trilha)."""
    palavras = {
        palavra
        for coluna in COLUNAS_TRILHA_AUDITORIA
        for palavra in re.split(r"[\s\-_]+", coluna.nome.lower())
    }

    assert not palavras & {"metadata", "metadados", "ip", "user", "agent", "sessão", "session"}
    assert [coluna.nome for coluna in COLUNAS_TRILHA_AUDITORIA] == [
        "Instante",
        "Ação",
        "Tipo de ator",
        "Autor",
        "Papéis",
        "Entidade",
        "Id da entidade",
        "Resultado",
        "Mudanças",
    ]
    assert COLUNAS_TRILHA_AUDITORIA[0].tipo is DATA
