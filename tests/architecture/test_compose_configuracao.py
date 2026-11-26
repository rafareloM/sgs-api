"""Cada suíte lenta sobe o compose com uma configuração que a API aceita.

As suítes `slow` (`tests/e2e/`, `tests/e2e_front/`) sobem o `docker/compose.yml` com variáveis
próprias e ficam fora do `make check`. Em 25/11/2026, uma regra nova do `Settings` (004/T6) impediu
a API de subir na `tests/e2e_front/`, e nenhuma verificação avisou. Aqui, sem subir contêiner, a
configuração de cada suíte é resolvida com `docker compose config`, e o ambiente do serviço `api`
passa pelo `load_settings()`, o mesmo da subida. Sem Docker, os testes são pulados.

Cada suíte declara, no próprio módulo, `ARQUIVOS_COMPOSE` e `AMBIENTE_COMPOSE`, e os usa ao subir o
compose: a configuração conferida aqui é a mesma da suíte.
"""

import importlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from src.core.config import load_settings
from src.tools.crypto_keys import novas_chaves
from tests.factories import make_jwt_private_keys

RAIZ = Path(__file__).resolve().parents[2]
DOCKER = shutil.which("docker")
PASTAS_LENTAS = ("e2e", "e2e_front")
# Só para o compose resolver o arquivo; `config` não cria rede.
BORDA = {"SGS_BORDA_SUBNET": "10.231.98.0/28", "SGS_BORDA_PROXY_IP": "10.231.98.14"}


def _suites() -> list[str]:
    """Módulos das suítes lentas que chamam `docker compose`."""
    return [
        f"tests.{pasta}.{arquivo.stem}"
        for pasta in PASTAS_LENTAS
        for arquivo in sorted((RAIZ / "tests" / pasta).glob("*.py"))
        if '"compose"' in arquivo.read_text(encoding="utf-8")
    ]


SUITES = _suites()


def _ambiente_da_api(suite: ModuleType) -> dict[str, str]:
    if DOCKER is None:
        pytest.skip("sem Docker: a configuração resolvida do compose não foi conferida")
    opcoes = [a for arquivo in suite.ARQUIVOS_COMPOSE for a in ("-f", str(arquivo))]
    # O ambiente da máquina não entra: nenhuma SGS_* local nem o docker/.env (o Compose novo só
    # obedece a COMPOSE_DISABLE_ENV_FILE; o antigo procura o .env no cwd, por isso `tests/`).
    limpo = {k: v for k, v in os.environ.items() if not k.startswith("SGS_")}
    resolvido = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [DOCKER, "compose", *opcoes, "-p", "sgs-api-arquitetura", "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=RAIZ / "tests",
        env=limpo | {"COMPOSE_DISABLE_ENV_FILE": "true"} | BORDA | suite.AMBIENTE_COMPOSE,
    )
    assert resolvido.returncode == 0, resolvido.stderr
    ambiente: dict[str, str | None] = json.loads(resolvido.stdout)["services"]["api"]["environment"]
    return {chave: valor for chave, valor in ambiente.items() if valor is not None}


def _arquivos_locais(ambiente: dict[str, str], pasta: Path) -> dict[str, str]:
    """Troca os caminhos de dentro do contêiner (segredos e CAs montados) por arquivos locais com
    conteúdo válido. Uma variável de arquivo nova, de outro formato, falha aqui pelo nome."""
    conteudos = {
        "JWT_PRIVATE_KEYS_FILE": make_jwt_private_keys("compose"),
        "CRYPTO_KEYS_FILE": json.dumps(novas_chaves()),
        "REPORT_SIGNING_KEYS_FILE": make_jwt_private_keys("rel-compose"),
    }
    trocado = dict(ambiente)
    for chave, valor in ambiente.items():
        if chave.endswith(("_FILE", "_CERT")) and valor.startswith("/"):
            arquivo = pasta / chave.lower()
            arquivo.write_text(conteudos.get(chave, ""), encoding="utf-8")
            trocado[chave] = str(arquivo)
    return trocado


def test_encontra_as_suites_lentas_que_sobem_o_compose() -> None:
    assert SUITES, "nenhuma suíte em tests/e2e ou tests/e2e_front chama docker compose"


@pytest.mark.parametrize("nome", SUITES)
def test_suite_declara_os_arquivos_e_o_ambiente_do_compose(nome: str) -> None:
    suite = importlib.import_module(nome)
    assert isinstance(getattr(suite, "ARQUIVOS_COMPOSE", None), tuple), (
        f"{nome}: declare ARQUIVOS_COMPOSE e use-o ao chamar docker compose"
    )
    assert isinstance(getattr(suite, "AMBIENTE_COMPOSE", None), dict), (
        f"{nome}: declare AMBIENTE_COMPOSE (as variáveis SGS_* da suíte) e use-o no compose"
    )


@pytest.mark.parametrize("nome", SUITES)
def test_api_aceita_a_configuracao_do_compose_da_suite(
    nome: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """001/R2.1 e R2.2: a configuração que a suíte dá à API passa pela validação da subida."""
    suite = importlib.import_module(nome)
    ambiente = _arquivos_locais(_ambiente_da_api(suite), tmp_path)
    for chave in list(os.environ):
        monkeypatch.delenv(chave)
    for chave, valor in ambiente.items():
        monkeypatch.setenv(chave, valor)
    load_settings()  # SettingsError nomeia cada variável recusada
