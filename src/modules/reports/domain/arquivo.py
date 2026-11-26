"""Arquivo gerado de um relatório (spec 005; design § Geração e envio, passo 2)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

# O XLSX aceita 1.048.576 linhas; o limite e o cabeçalho cabem nele.
LIMITE_DE_LINHAS: Final = 1_000_000
MENSAGEM_GRANDE_DEMAIS: Final = "Relatório grande demais; reduza o período ou os filtros"


class RelatorioGrandeDemais(Exception):  # noqa: N818 (sinal para o caso de uso, não um erro de API)
    def __init__(self) -> None:
        super().__init__(MENSAGEM_GRANDE_DEMAIS)


@dataclass(frozen=True)
class ArquivoGerado:
    """O que o caso de uso precisa depois de escrever: o hash vai para o `ChecksumSHA256`
    (R2.3) e para a assinatura (R5.1); o tamanho, para o pedido concluído (R2.5)."""

    tamanho: int
    sha256: bytes
    linhas: int


class GeradorDeArquivo(Protocol):
    """Escreve um formato (CSV ou XLSX) em lotes, como saem do cursor do servidor. A escrita é
    bloqueante: quem chama usa `anyio.to_thread.run_sync`."""

    content_type: str
    extensao: str

    def escrever(self, linhas: Iterable[Sequence[object]]) -> None:
        """Acrescenta um lote. Acima do limite de linhas, `RelatorioGrandeDemais`."""
        ...

    def finalizar(self) -> ArquivoGerado:
        """Fecha o formato no destino e devolve tamanho, SHA-256 e linhas escritas."""
        ...

    def descartar(self) -> None:
        """Apaga o que o formato guardou fora do destino (o temporário do XLSX). Quem chama usa
        num `finally`: vale depois de `finalizar` e mais de uma vez."""
        ...
