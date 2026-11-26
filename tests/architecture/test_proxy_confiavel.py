"""Só o proxy, pelo IP fixo, informa o IP do cliente; redes separadas (spec 013, T4).

Confere o `docker/compose.yml` como o Compose o resolve (`docker compose config`, que só lê os
arquivos e não toca em contêiner nenhum) e o Dockerfile. Sem Docker, só o Dockerfile é conferido.
"""

import ipaddress
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.redes import FAIXA_DO_PROJETO, SUBNETS

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "docker" / "compose.yml"
DOCKERFILE = RAIZ / "docker" / "Dockerfile"
DOCKER = shutil.which("docker")
SUBNET, PROXY = "10.231.99.0/28", "10.231.99.14"


def _config(ambiente: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if DOCKER is None:
        pytest.skip("sem Docker: a configuração resolvida do compose não foi conferida")
    sem_borda = {k: v for k, v in os.environ.items() if not k.startswith("SGS_BORDA_")}
    # Só lê e resolve o arquivo; `--no-interpolate` não é usado de propósito.
    return subprocess.run(  # noqa: S603
        [
            DOCKER,
            "compose",
            "-f",
            str(COMPOSE),
            "-p",
            "sgs-api-arquitetura",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        # Um docker/.env local não pode entrar: o Compose antigo procura o .env no diretório atual
        # (por isso o cwd fora de docker/); o novo procura ao lado do compose.yml e só obedece à
        # variável COMPOSE_DISABLE_ENV_FILE.
        cwd=RAIZ / "tests",
        env=sem_borda | {"COMPOSE_DISABLE_ENV_FILE": "true"} | ambiente,
    )


def _resolvido() -> dict[str, Any]:
    resolvido = _config({"SGS_BORDA_SUBNET": SUBNET, "SGS_BORDA_PROXY_IP": PROXY})
    assert resolvido.returncode == 0, resolvido.stderr
    config: dict[str, Any] = json.loads(resolvido.stdout)
    return config


def test_sem_forwarded_allow_ips_curinga_nem_subnet() -> None:
    """013/R3.1: nenhum `*`; a API confia só no IP do proxy (/32), não na subnet nem no
    gateway; o Dockerfile não fixa a lista (o uvicorn lê `FORWARDED_ALLOW_IPS`)."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "--forwarded-allow-ips" not in dockerfile
    assert "--proxy-headers" in dockerfile
    texto = COMPOSE.read_text(encoding="utf-8")
    assert re.search(r'forwarded.allow.ips[^\n]*"\*"', texto, re.I) is None

    config = _resolvido()

    servicos = config["services"]
    assert servicos["api"]["environment"]["FORWARDED_ALLOW_IPS"] == f"{PROXY}/32"
    assert servicos["proxy"]["networks"]["borda"]["ipv4_address"] == PROXY
    [ipam] = config["networks"]["borda"]["ipam"]["config"]
    rede = ipaddress.IPv4Network(ipam["subnet"])
    assert ipaddress.IPv4Address(PROXY) in rede
    assert ipaddress.IPv4Address(PROXY) != rede[1]  # o .1 é o gateway da bridge
    confiaveis = [
        str(s.get("environment", {}).get("FORWARDED_ALLOW_IPS"))
        for s in servicos.values()
        if "FORWARDED_ALLOW_IPS" in s.get("environment", {})
    ]
    assert confiaveis == [f"{PROXY}/32"]


def test_compose_exige_subnet_e_ip_do_proxy() -> None:
    """013/R3.7: sem as variáveis o compose não resolve; as redes separam borda e dados, e o banco
    fica fora da borda e sem porta publicada. 004 (design § Redes; D004-13): os serviços de
    laboratório ficam em `integracoes` (com a API) e `exposicao` (com o proxy), sem porta no host,
    e proxy e API continuam só com a `borda` em comum (013/R3.1)."""
    sem_variaveis = _config({})
    assert sem_variaveis.returncode != 0
    assert "SGS_BORDA" in sem_variaveis.stderr

    config = _resolvido()
    servicos = config["services"]

    redes = {nome: set(s["networks"]) for nome, s in servicos.items()}
    assert redes == {
        "db-certs": {"dados"},
        "servicos-certs": {"exposicao"},
        "db": {"dados"},
        "api": {"borda", "dados", "integracoes"},
        "keycloak": {"integracoes", "exposicao"},
        "ldap": {"integracoes"},
        # Spec 005 (T8): a API envia pela `integracoes`; o navegador baixa pelo proxy.
        "s3": {"integracoes", "exposicao"},
        "s3-init": {"integracoes"},
        "proxy": {"borda", "exposicao"},
    }
    assert redes["api"] & redes["proxy"] == {"borda"}
    assert config["networks"]["integracoes"]["internal"] is True
    for servico in ("api", "db", "keycloak", "ldap", "s3", "s3-init"):
        assert "ports" not in servicos[servico], servico


def test_subnets_das_suites_sao_unicas_e_fora_dos_pools_do_docker() -> None:
    """013/R3.7: cada suíte que sobe compose usa a sua subnet (tests/e2e/redes.py), e o valor de
    desenvolvimento do .env.example não colide com nenhuma delas."""
    suites = {
        "FRONT": RAIZ / "tests" / "e2e" / "test_frontend_entrega.py",
        "TLS": RAIZ / "tests" / "e2e" / "test_tls_banco.py",
        "FRONT_UI": RAIZ / "tests" / "e2e_front" / "conftest.py",
        "AUDITORIA": RAIZ / "tests" / "e2e" / "test_auditoria_proxy.py",
        "KEYCLOAK": RAIZ / "tests" / "e2e" / "test_lab_keycloak.py",
        "LDAP": RAIZ / "tests" / "e2e" / "test_lab_ldap.py",
        "S3": RAIZ / "tests" / "e2e" / "test_export_s3.py",
    }
    assert set(suites) == set(SUBNETS)
    for suite, arquivo in suites.items():
        assert f'borda_da_suite("{suite}"' in arquivo.read_text(encoding="utf-8"), arquivo.name
    exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    [dev] = re.findall(r"^SGS_BORDA_SUBNET=(\S+)$", exemplo, re.M)
    [proxy_dev] = re.findall(r"^SGS_BORDA_PROXY_IP=(\S+)$", exemplo, re.M)
    rede_dev = ipaddress.IPv4Network(dev)
    assert rede_dev.subnet_of(FAIXA_DO_PROJETO)
    assert ipaddress.IPv4Address(proxy_dev) == rede_dev[-2]
    assert not any(rede_dev.overlaps(ipaddress.IPv4Network(s)) for s in SUBNETS.values())
