"""Segredos que o docker/compose.yml monta, para as suítes lentas que sobem a API.

O compose lê os segredos de `secrets/` (fora do Git). Cada suíte cria só os que faltam, com as
ferramentas do projeto, e no fim apaga só os que criou: os de quem desenvolve na máquina ficam.
Desde a 005/T8, a API monta também a chave de assinatura dos relatórios, e o `s3`, a chave da
SSE; uma suíte que não os criasse não subiria a API.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from src.tools import crypto_keys, jwt_keys, s3_sse_key

PASTA: Final = Path(__file__).resolve().parents[2] / "secrets"


def _jwt(caminho: Path) -> None:
    jwt_keys.main(["--output", str(caminho)])


def _cifra(caminho: Path) -> None:
    crypto_keys.main(["--output", str(caminho)])


def _relatorios(caminho: Path) -> None:
    jwt_keys.main(["--kid", "rel-e2e", "--output", str(caminho)])


def _sse_do_s3(caminho: Path) -> None:
    s3_sse_key.main(["--output", str(caminho)])


GERADORES: Final[dict[str, Callable[[Path], None]]] = {
    "jwt-keys.json": _jwt,
    "crypto-keys.json": _cifra,
    "report-keys.json": _relatorios,
    "s3-security.toml": _sse_do_s3,
}
DA_005: Final = ("report-keys.json", "s3-security.toml")


@dataclass
class Criados:
    arquivos: list[Path] = field(default_factory=list)
    pasta: bool = False


def criar_faltando(nomes: tuple[str, ...] = tuple(GERADORES)) -> Criados:
    """Gera os segredos `nomes` que ainda não existem e devolve o que foi criado."""
    criados = Criados(pasta=not PASTA.exists())
    PASTA.mkdir(exist_ok=True)
    for nome in nomes:
        caminho = PASTA / nome
        if not caminho.exists():
            GERADORES[nome](caminho)
            criados.arquivos.append(caminho)
    return criados


def apagar(criados: Criados) -> None:
    """Apaga só o que `criar_faltando` criou (a pasta, só se ficou vazia)."""
    for caminho in criados.arquivos:
        caminho.unlink(missing_ok=True)
    if criados.pasta and PASTA.exists() and not any(PASTA.iterdir()):
        PASTA.rmdir()
