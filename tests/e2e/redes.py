"""Subnet da rede de borda de cada suíte que sobe um compose próprio (spec 013, T4; R3.7).

O compose exige `SGS_BORDA_SUBNET` e `SGS_BORDA_PROXY_IP` (docker/compose.yml): cada stack no
mesmo host precisa de uma subnet própria. Aqui ficam as das suítes, todas na faixa do projeto
(`10.231.0.0/16`, fora dos pools padrão do Docker). Cada uma aceita outra pela variável
`SGS_E2E_SUBNET_<SUITE>`. Antes de subir qualquer contêiner, a suíte confere, só lendo
(`docker network ls` e `docker network inspect`), se a subnet já está em uso; se estiver, ela para
com uma mensagem que diz qual rede ocupa a faixa e qual variável usar. Nenhuma rede é alterada.
"""

import ipaddress
import os
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

FAIXA_DO_PROJETO = ipaddress.IPv4Network("10.231.0.0/16")
POOLS_DO_DOCKER = (ipaddress.IPv4Network("172.16.0.0/12"), ipaddress.IPv4Network("192.168.0.0/16"))

SUBNETS = {
    "FRONT": "10.231.10.0/28",  # tests/e2e/test_frontend_entrega.py
    "TLS": "10.231.11.0/28",  # tests/e2e/test_tls_banco.py
    "FRONT_UI": "10.231.12.0/28",  # tests/e2e_front/conftest.py
    "AUDITORIA": "10.231.13.0/28",  # tests/e2e/test_auditoria_proxy.py
    "KEYCLOAK": "10.231.14.0/28",  # tests/e2e/test_lab_keycloak.py
    "LDAP": "10.231.15.0/28",  # tests/e2e/test_lab_ldap.py
    "S3": "10.231.16.0/28",  # tests/e2e/test_export_s3.py
    "SYNC_LDAP": "10.231.17.0/28",  # tests/e2e/test_sync_ldap.py
    "LOGIN": "10.231.18.0/28",  # tests/e2e/test_login_ldap_oidc.py
}
"""Suíte → subnet padrão. Os stacks de desenvolvimento usam 10.231.1.0/28 (.env.example)."""


class SubnetOcupadaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Borda:
    subnet: str
    proxy_ip: str
    gateway_ip: str

    def ambiente(self) -> dict[str, str]:
        """Variáveis que o docker/compose.yml exige."""
        return {"SGS_BORDA_SUBNET": self.subnet, "SGS_BORDA_PROXY_IP": self.proxy_ip}


def escolher(suite: str, ocupadas: Iterable[tuple[str, str]], ambiente: Mapping[str, str]) -> Borda:
    """A subnet da suíte (ou a da variável `SGS_E2E_SUBNET_<SUITE>`), se nenhuma rede existente
    (nome, subnet) a sobrepõe. O proxy fica no último endereço útil (o Docker dá os dinâmicos de
    baixo para cima, então a API, criada antes do proxy, não o toma) e o gateway da bridge no .1."""
    variavel = f"SGS_E2E_SUBNET_{suite}"
    rede = ipaddress.IPv4Network(ambiente.get(variavel, SUBNETS[suite]))
    for nome, subnet in ocupadas:
        if rede.overlaps(ipaddress.ip_network(subnet)):
            raise SubnetOcupadaError(
                f"a subnet {rede} da suíte {suite} sobrepõe a rede Docker existente {nome!r}"
                f" ({subnet}); defina {variavel} com uma subnet livre (por exemplo, outra /28 de"
                f" {FAIXA_DO_PROJETO}). Nenhuma rede foi alterada."
            )
    return Borda(subnet=str(rede), proxy_ip=str(rede[-2]), gateway_ip=str(rede[1]))


def redes_existentes(docker: str) -> list[tuple[str, str]]:
    """(nome, subnet) de toda rede Docker do host, só por leitura."""
    # Comandos fixos, sem entrada externa.
    nomes = subprocess.run(  # noqa: S603
        [docker, "network", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.split()
    if not nomes:
        return []
    saida = subprocess.run(  # noqa: S603
        [
            docker,
            "network",
            "inspect",
            "--format",
            "{{.Name}}{{range .IPAM.Config}} {{.Subnet}}{{end}}",
            *nomes,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    redes: list[tuple[str, str]] = []
    for linha in saida.splitlines():
        nome, *subnets = linha.split()
        redes.extend((nome, subnet) for subnet in subnets if subnet)
    return redes


def borda_da_suite(suite: str, docker: str, *, projeto: str) -> Borda:
    """A borda da suíte, conferida contra as redes do host. A rede do próprio projeto, sobrando
    de uma execução interrompida, não conta como ocupada: o `down` da suíte a remove."""
    proprias = (f"{projeto}_borda",)
    ocupadas = [(n, s) for n, s in redes_existentes(docker) if n not in proprias]
    return escolher(suite, ocupadas, os.environ)
