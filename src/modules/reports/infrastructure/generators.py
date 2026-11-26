"""Geradores CSV e XLSX dos relatórios (spec 005, R1.2, R2.3, R4.1, R4.2; design § Conteúdo e
§ Geração e envio, passo 2).

A escrita é bloqueante (`csv` e `openpyxl`): o caso de uso chama `escrever` e `finalizar` em
`anyio.to_thread.run_sync`, um lote por vez, e `descartar` num `finally`.
"""

import csv
import hashlib
import re
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import date, datetime
from decimal import Decimal
from typing import BinaryIO, Final

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from src.core.fuso import em_recife
from src.modules.reports.domain.arquivo import (
    LIMITE_DE_LINHAS,
    ArquivoGerado,
    GeradorDeArquivo,
    RelatorioGrandeDemais,
)
from src.modules.reports.domain.colunas import Coluna, TipoColuna, neutralizar

BOM_UTF8: Final = b"\xef\xbb\xbf"
SUBSTITUTO: Final = "�"
# XML 1.0 § 2.2: fora dele ficam os controles (menos tabulação e quebras), os surrogates soltos,
# U+FFFE e U+FFFF. O `ILLEGAL_CHARACTERS_RE` do openpyxl só cobre os controles, e o resto sai
# num XLSX que não abre.
FORA_DO_XML: Final = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


class _DestinoComHash:
    """Repassa ao destino cada bloco escrito e atualiza o SHA-256 e o tamanho na hora.

    Não tem `tell` nem `seek` de propósito: com destino posicionável, o `zipfile` do XLSX volta
    para reescrever o cabeçalho de cada parte, e o hash deixaria de ser o do arquivo final. Sem
    eles, o `zipfile` grava em fluxo, com o descritor de dados depois de cada parte.
    """

    def __init__(self, destino: BinaryIO) -> None:
        self._destino = destino
        self._sha256 = hashlib.sha256()
        self.tamanho = 0

    def write(self, dados: bytes) -> int:
        bloco = memoryview(dados)
        self._sha256.update(bloco)
        self._destino.write(bloco)
        self.tamanho += bloco.nbytes
        return bloco.nbytes

    def flush(self) -> None:
        self._destino.flush()

    def sha256(self) -> bytes:
        return self._sha256.digest()


class _TextoUtf8:
    """O `csv.writer` escreve `str`; o destino recebe UTF-8."""

    def __init__(self, destino: _DestinoComHash) -> None:
        self._destino = destino

    def write(self, texto: str) -> int:
        return self._destino.write(texto.encode("utf-8"))


def _data(valor: date) -> str:
    """ISO 8601 no fuso de Recife (design § Conteúdo, Trilha): `2026-11-25 23:50:19-03:00`, ou
    só `2026-11-25`. O banco devolve UTC; um instante sem fuso é UTC, como em `em_recife`."""
    if isinstance(valor, datetime):
        return em_recife(valor).isoformat(sep=" ", timespec="seconds")
    return valor.isoformat()


def _celula(coluna: Coluna, valor: object) -> int | float | Decimal | str | None:
    """Número e data de verdade saem formatados, sem neutralização; o resto é texto
    neutralizado (R4.2), mesmo numa coluna numérica ou de data."""
    if valor is None:
        return None
    if (
        coluna.tipo is TipoColuna.NUMERO
        and isinstance(valor, int | float | Decimal)
        and not isinstance(valor, bool)
    ):
        return valor
    if coluna.tipo is TipoColuna.DATA and isinstance(valor, date):
        return _data(valor)
    return neutralizar(valor if isinstance(valor, str) else str(valor))


class _Gerador:
    content_type: str
    extensao: str

    def __init__(
        self, destino: BinaryIO, colunas: Sequence[Coluna], *, limite: int = LIMITE_DE_LINHAS
    ) -> None:
        self._destino = _DestinoComHash(destino)
        self._colunas = tuple(colunas)
        self._limite = limite
        self._linhas = 0

    def escrever(self, linhas: Iterable[Sequence[object]]) -> None:
        for linha in linhas:
            if len(linha) != len(self._colunas):
                raise ValueError(
                    f"Linha com {len(linha)} valores; o relatório tem {len(self._colunas)} colunas."
                )
            if self._linhas >= self._limite:
                raise RelatorioGrandeDemais
            self._escrever_linha(
                [_celula(coluna, valor) for coluna, valor in zip(self._colunas, linha, strict=True)]
            )
            self._linhas += 1

    def finalizar(self) -> ArquivoGerado:
        self._fechar()
        self._destino.flush()
        return ArquivoGerado(
            tamanho=self._destino.tamanho, sha256=self._destino.sha256(), linhas=self._linhas
        )

    def descartar(self) -> None:
        return None

    def _escrever_linha(self, valores: list[int | float | Decimal | str | None]) -> None:
        raise NotImplementedError

    def _fechar(self) -> None:
        raise NotImplementedError


class GeradorCsv(_Gerador):
    """R4.1: UTF-8 com BOM, `;`, `\\r\\n` e `QUOTE_MINIMAL`, para abrir certo no Excel em
    português."""

    content_type = "text/csv; charset=utf-8"
    extensao = "csv"

    def __init__(
        self, destino: BinaryIO, colunas: Sequence[Coluna], *, limite: int = LIMITE_DE_LINHAS
    ) -> None:
        super().__init__(destino, colunas, limite=limite)
        self._destino.write(BOM_UTF8)
        self._csv = csv.writer(
            _TextoUtf8(self._destino),
            delimiter=";",
            lineterminator="\r\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        self._csv.writerow([neutralizar(coluna.nome) for coluna in self._colunas])

    def _escrever_linha(self, valores: list[int | float | Decimal | str | None]) -> None:
        self._csv.writerow(valores)

    def _fechar(self) -> None:
        return None


class GeradorXlsx(_Gerador):
    """`openpyxl` em `write_only`. Todo texto vai como texto explícito (`data_type = "s"`): o
    openpyxl grava como fórmula o texto que começa por `=` (R4.2), e como erro o que é um código
    de erro do Excel (`#REF!`)."""

    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    extensao = "xlsx"

    def __init__(
        self, destino: BinaryIO, colunas: Sequence[Coluna], *, limite: int = LIMITE_DE_LINHAS
    ) -> None:
        super().__init__(destino, colunas, limite=limite)
        self._livro = Workbook(write_only=True)
        self._planilha = self._livro.create_sheet("Relatório")
        self._encerrado = False
        self._planilha.append([self._texto(neutralizar(coluna.nome)) for coluna in self._colunas])

    def _texto(self, texto: str) -> WriteOnlyCell:
        # Um valor só, fora do XML, não pode derrubar a exportação (o openpyxl recusa controles)
        # nem gerar um arquivo que não abre (U+FFFF passa pelo openpyxl).
        celula = WriteOnlyCell(self._planilha, value=FORA_DO_XML.sub(SUBSTITUTO, texto))
        celula.data_type = "s"
        return celula

    def _escrever_linha(self, valores: list[int | float | Decimal | str | None]) -> None:
        self._planilha.append(
            [self._texto(valor) if isinstance(valor, str) else valor for valor in valores]
        )

    def _fechar(self) -> None:
        # O `save` grava as partes no destino e apaga o temporário da planilha.
        self._livro.save(self._destino)
        self._encerrado = True

    def descartar(self) -> None:
        """O `openpyxl` guarda a planilha num temporário em disco até o `save`, e só o apaga
        sozinho quando o processo termina. Numa falha no meio da geração, apaga agora."""
        if self._encerrado:
            return
        self._encerrado = True
        # O mesmo fechamento que o `save` faz antes de copiar a planilha para o ZIP; sem ele, o
        # gerador de linhas do openpyxl tenta escrever num arquivo já fechado quando é coletado.
        if not self._planilha.closed:
            self._planilha.close()
        # Um `save` que falhou no meio pode já ter apagado o temporário.
        with suppress(FileNotFoundError, ValueError):
            self._planilha._writer.cleanup()


FORMATOS: Final[dict[str, type[GeradorCsv] | type[GeradorXlsx]]] = {
    "csv": GeradorCsv,
    "xlsx": GeradorXlsx,
}


def novo_gerador(
    formato: str, destino: BinaryIO, colunas: Sequence[Coluna], *, limite: int = LIMITE_DE_LINHAS
) -> GeradorDeArquivo:
    """R1.2: `csv` ou `xlsx`."""
    try:
        classe = FORMATOS[formato]
    except KeyError:
        raise ValueError(f"Formato de relatório desconhecido: {formato!r}.") from None
    return classe(destino, colunas, limite=limite)
