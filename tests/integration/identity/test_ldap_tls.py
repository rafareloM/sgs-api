"""Conferência do TLS do LDAP com um servidor TLS local em *thread* (spec 004, T11; design
§ Riscos: o `ldap3` 2.9.1 confere o nome por um *backport* próprio).

O servidor de teste registra os bytes LDAP que recebe: com a CA errada ou o nome errado, o
adaptador recusa a conexão sem enviar nenhum (nenhuma credencial sai da API, R1.13). No fim, o
referral e a busca cortada pelo servidor: nenhum byte vai ao host do referral, e nada vira retrato.
"""

import contextlib
import datetime as dt
import socket
import ssl
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import SecretStr

from src.core.config import Settings
from src.modules.identity.domain.diretorio import DirectoryUnavailable, DirectoryUser
from src.modules.identity.infrastructure.ldap3_directory import Ldap3Directory, LdapConfig
from src.tools import sgs_admin
from tests.factories import make_settings

SENHA_DO_SERVICO = "senha-exemplo-servico-tls"
STARTTLS_OID = b"1.3.6.1.4.1.1466.20037"


@dataclass(frozen=True)
class Autoridade:
    chave: ec.EllipticCurvePrivateKey
    certificado: x509.Certificate


def _nome(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _uso_de_ca() -> x509.KeyUsage:
    # O contexto padrão do Python 3.13 usa VERIFY_X509_STRICT: CA com keyUsage e AKI na folha.
    return x509.KeyUsage(
        digital_signature=False,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=True,
        encipher_only=False,
        decipher_only=False,
    )


def _autoridade(cn: str) -> Autoridade:
    chave = ec.generate_private_key(ec.SECP256R1())
    agora = dt.datetime.now(dt.UTC)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(_nome(cn))
        .issuer_name(_nome(cn))
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - dt.timedelta(minutes=5))
        .not_valid_after(agora + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(_uso_de_ca(), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False
        )
        .sign(chave, hashes.SHA256())
    )
    return Autoridade(chave, certificado)


def _certificado_do_servidor(ca: Autoridade, nome: str, destino: Path) -> tuple[Path, Path]:
    chave = ec.generate_private_key(ec.SECP256R1())
    agora = dt.datetime.now(dt.UTC)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(_nome(nome))
        .issuer_name(ca.certificado.subject)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - dt.timedelta(minutes=5))
        .not_valid_after(agora + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(nome)]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca.chave.public_key()),
            critical=False,
        )
        .sign(ca.chave, hashes.SHA256())
    )
    cert = destino / f"{nome}.crt"
    key = destino / f"{nome}.key"
    cert.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(
        chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert, key


def _gravar_ca(ca: Autoridade, destino: Path) -> Path:
    caminho = destino / "ca.crt"
    caminho.write_bytes(ca.certificado.public_bytes(serialization.Encoding.PEM))
    return caminho


@dataclass
class ServidorTls:
    """Aceita uma conexão e guarda os bytes LDAP recebidos (antes e depois do TLS)."""

    contexto: ssl.SSLContext
    start_tls: bool
    # Com um resultCode, responde ao bind (0: sucesso; 49: invalidCredentials) e espera o unbind.
    resultado_do_bind: int | None = None
    porta: int = 0
    em_claro: bytearray = field(default_factory=bytearray)
    cifrados: bytearray = field(default_factory=bytearray)

    def rodar(self, escuta: socket.socket) -> None:
        try:
            conexao, _ = escuta.accept()
        except OSError:
            return
        conexao.settimeout(5)
        try:
            if self.start_tls:
                pedido = conexao.recv(4096)
                self.em_claro.extend(pedido)
                if STARTTLS_OID not in pedido:
                    return
                # extendedResp com sucesso e o mesmo messageID do pedido (comprimentos curtos).
                resposta = bytes([0x30, 0x0C, 0x02, 0x01, pedido[4]])
                conexao.sendall(resposta + bytes.fromhex("78070a010004000400"))
            with self.contexto.wrap_socket(conexao, server_side=True) as tls:
                while dados := tls.recv(4096):
                    self.cifrados.extend(dados)
                    if self.resultado_do_bind is None:
                        break  # o bind chegou: basta para o controle positivo
                    if dados[5] == 0x60:  # bindRequest → bindResponse com o mesmo messageID
                        cabecalho = bytes([0x30, 0x0C, 0x02, 0x01, dados[4], 0x61, 0x07])
                        corpo = bytes([0x0A, 0x01, self.resultado_do_bind, 0x04, 0x00, 0x04, 0x00])
                        tls.sendall(cabecalho + corpo)
        except (OSError, ssl.SSLError):
            pass  # a recusa do cliente (alerta TLS, conexão fechada) é o esperado
        finally:
            conexao.close()


@pytest.fixture
def autoridades() -> tuple[Autoridade, Autoridade]:
    return _autoridade("CA do laboratório"), _autoridade("CA de outra pessoa")


@contextmanager
def _servidor(
    cert: Path, key: Path, *, start_tls: bool, resultado_do_bind: int | None = None
) -> Iterator[ServidorTls]:
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(cert, key)
    servidor = ServidorTls(contexto, start_tls, resultado_do_bind)
    with socket.create_server(("127.0.0.1", 0)) as escuta:
        escuta.settimeout(10)
        servidor.porta = escuta.getsockname()[1]
        thread = threading.Thread(target=servidor.rodar, args=(escuta,), daemon=True)
        thread.start()
        yield servidor
        thread.join(timeout=10)


def _diretorio(url: str, ca: Path, *, start_tls: bool) -> Ldap3Directory:
    return Ldap3Directory(
        LdapConfig(
            url=url,
            start_tls=start_tls,
            ca_file=ca,
            bind_dn="cn=sgs-sync,ou=servicos,dc=teste",
            bind_password=SecretStr(SENHA_DO_SERVICO),
            user_base="ou=pessoas,dc=teste",
            user_filter="(objectClass=inetOrgPerson)",
            group_base="ou=grupos,dc=teste",
            group_filter="(objectClass=groupOfNames)",
            attr_login="uid",
            attr_email="mail",
            attr_name="cn",
            attr_id="entryUUID",
            attr_member="member",
            page_size=500,
        )
    )


CASOS = [
    pytest.param("certo", "localhost", True, id="ca-e-nome-certos"),
    pytest.param("errada", "localhost", False, id="ca-errada"),
    pytest.param("certo", "outro.teste", False, id="nome-errado"),
]


@pytest.mark.parametrize("start_tls", [False, True], ids=["ldaps", "starttls"])
@pytest.mark.parametrize(("ca_do_cliente", "nome_no_certificado", "aceita"), CASOS)
async def test_tls_do_ldap_e_conferido_antes_de_qualquer_credencial(
    tmp_path: Path,
    autoridades: tuple[Autoridade, Autoridade],
    start_tls: bool,
    ca_do_cliente: str,
    nome_no_certificado: str,
    aceita: bool,
) -> None:
    """004/R1.2, R1.13 (CA errada e nome errado recusados sem nenhum byte LDAP cifrado; o caso
    certo é o controle positivo: o bind chega ao servidor)"""
    certa, errada = autoridades
    cert, key = _certificado_do_servidor(certa, nome_no_certificado, tmp_path)
    ca = _gravar_ca(certa if ca_do_cliente == "certo" else errada, tmp_path)

    with _servidor(cert, key, start_tls=start_tls) as servidor:
        esquema = "ldap" if start_tls else "ldaps"
        url = f"{esquema}://localhost:{servidor.porta}"
        with pytest.raises(DirectoryUnavailable) as erro:
            # O servidor de teste não responde ao bind: até o caso certo termina indisponível.
            await _diretorio(url, ca, start_tls=start_tls).find_user("ana")
        assert SENHA_DO_SERVICO not in str(erro.value)

    if start_tls:  # em claro, só o pedido de StartTLS: uma mensagem, extendedReq (0x77)
        assert len(servidor.em_claro) == servidor.em_claro[1] + 2
        assert servidor.em_claro[5] == 0x77
        assert STARTTLS_OID in servidor.em_claro
    else:
        assert servidor.em_claro == b""
    if aceita:
        assert SENHA_DO_SERVICO.encode() in servidor.cifrados  # o bind veio, e só sob TLS
    else:
        assert servidor.cifrados == b""


# `sgs-admin diretorio testar` (design § Roteiro e ferramenta): conexão e bind da conta de
# serviço, sem gravar nada; responde "ok" ou o motivo genérico.

INVALID_CREDENTIALS = 49


def _settings_ldap(url: str, ca: Path, *, start_tls: bool = False) -> Settings:
    return make_settings(
        ldap_url=url,
        ldap_start_tls=start_tls,
        ldap_ca_file=str(ca),
        ldap_bind_dn="cn=sgs-sync,ou=servicos,dc=teste",
        ldap_bind_password=SecretStr(SENHA_DO_SERVICO),
        ldap_user_base="ou=pessoas,dc=teste",
        ldap_user_filter="(objectClass=inetOrgPerson)",
        ldap_group_base="ou=grupos,dc=teste",
        ldap_group_filter="(objectClass=groupOfNames)",
    )


@pytest.mark.parametrize(
    ("ca_do_cliente", "nome_no_certificado", "resultado_do_bind", "codigo", "saida"),
    [
        pytest.param("certo", "localhost", 0, 0, "ok", id="ok"),
        pytest.param("certo", "localhost", INVALID_CREDENTIALS, 1, "credencial", id="credencial"),
        pytest.param("errada", "localhost", 0, 1, "certificado", id="ca-errada"),
        pytest.param("certo", "outro.teste", 0, 1, "certificado", id="nome-errado"),
    ],
)
@pytest.mark.parametrize("start_tls", [False, True], ids=["ldaps", "starttls"])
def test_sgs_admin_diretorio_testar_responde_ok_ou_o_motivo(
    tmp_path: Path,
    autoridades: tuple[Autoridade, Autoridade],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    start_tls: bool,
    ca_do_cliente: str,
    nome_no_certificado: str,
    resultado_do_bind: int,
    codigo: int,
    saida: str,
) -> None:
    """004/R1.13, R5.3 (o operador e o teste ponta a ponta conferem a recusa do certificado;
    nada da senha na saída)"""
    certa, errada = autoridades
    cert, key = _certificado_do_servidor(certa, nome_no_certificado, tmp_path)
    ca = _gravar_ca(certa if ca_do_cliente == "certo" else errada, tmp_path)
    nenhuma_ca = tmp_path / "nao-usada.crt"
    nenhuma_ca.write_text("x", encoding="utf-8")
    # A configuração aponta para outro servidor e outra CA: --url e --ca valem por cima dela.
    invalido = "ldap://ldap.invalido" if start_tls else "ldaps://ldap.invalido"
    configurado = _settings_ldap(invalido, nenhuma_ca, start_tls=start_tls)
    monkeypatch.setattr(sgs_admin, "load_settings", lambda: configurado)

    with _servidor(cert, key, start_tls=start_tls, resultado_do_bind=resultado_do_bind) as sv:
        url = f"{'ldap' if start_tls else 'ldaps'}://localhost:{sv.porta}"
        retorno = sgs_admin.main(["diretorio", "testar", "--url", url, "--ca", str(ca)])

    capturado = capsys.readouterr()
    assert retorno == codigo
    assert saida in (capturado.out if codigo == 0 else capturado.err)
    assert SENHA_DO_SERVICO not in capturado.out + capturado.err


def test_sgs_admin_diretorio_testar_sem_servidor_responde_conexao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """004/R1.10 (diretório fora do ar: motivo genérico, sem a senha)"""
    ca = tmp_path / "ca.crt"
    ca.write_text("x", encoding="utf-8")
    with socket.create_server(("127.0.0.1", 0)) as livre:
        porta = livre.getsockname()[1]
    monkeypatch.setattr(
        sgs_admin, "load_settings", lambda: _settings_ldap(f"ldaps://localhost:{porta}", ca)
    )

    retorno = sgs_admin.main(["diretorio", "testar"])

    capturado = capsys.readouterr()
    assert retorno == 1
    assert "conexao" in capturado.err
    assert SENHA_DO_SERVICO not in capturado.out + capturado.err


@pytest.mark.parametrize(
    ("argumentos", "mensagem"),
    [
        pytest.param([], "LDAP_URL", id="ldap-desligado"),
        pytest.param(["--url", "ldap://ldap.teste"], "LDAP_URL: use ldaps://", id="sem-tls"),
    ],
)
def test_sgs_admin_diretorio_testar_recusa_configuracao_invalida(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    argumentos: list[str],
    mensagem: str,
) -> None:
    """004/R1.2 (o teste usa as mesmas regras da subida: só LDAPS ou StartTLS)"""
    ca = tmp_path / "ca.crt"
    ca.write_text("x", encoding="utf-8")
    configurado = _settings_ldap("ldaps://ldap.teste", ca) if argumentos else make_settings()
    monkeypatch.setattr(sgs_admin, "load_settings", lambda: configurado)

    assert sgs_admin.main(["diretorio", "testar", *argumentos]) == 2
    assert mensagem in capsys.readouterr().err


# Referral e busca cortada (revisão de integração da frente A, B1 e S1). Seguir um referral
# refaria o bind da conta de serviço no host indicado, e um `ldap://` o mandaria em claro. Uma
# busca cortada pelo servidor (sizeLimitExceeded, timeLimitExceeded) seria um retrato parcial, e
# a R1.7 desativaria quem ficou de fora. As duas terminam como o diretório fora do ar (R1.10).

SUCESSO, TIME_LIMIT_EXCEEDED, SIZE_LIMIT_EXCEEDED, REFERRAL = 0, 3, 4, 10
BIND_REQUEST, BIND_RESPONSE, UNBIND_REQUEST = 0x60, 0x61, 0x42
SEARCH_REQUEST, SEARCH_RES_ENTRY, SEARCH_RES_DONE = 0x63, 0x64, 0x65
TEXTO_DO_SERVIDOR = "texto-cru-do-servidor"
SENHA_DA_ANA = "senha-exemplo-da-ana"
ANA = DirectoryUser(
    external_id="uuid-ana",
    dn="uid=ana,ou=pessoas,dc=teste",
    login="ana",
    email="ana@teste",
    display_name="Ana",
)


def _tlv(tag: int, conteudo: bytes) -> bytes:
    """Um elemento BER: tag, comprimento definido e conteúdo."""
    if len(conteudo) < 0x80:
        return bytes([tag, len(conteudo)]) + conteudo
    tamanho = len(conteudo).to_bytes((len(conteudo).bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(tamanho)]) + tamanho + conteudo


def _elemento(dados: bytes, inicio: int = 0) -> tuple[int, int] | None:
    """Início e fim do conteúdo do elemento BER em `inicio`; None se ainda não chegou inteiro."""
    if len(dados) < inicio + 2:
        return None
    tamanho, posicao = dados[inicio + 1], inicio + 2
    if tamanho & 0x80:
        bytes_do_tamanho = tamanho & 0x7F
        if len(dados) < posicao + bytes_do_tamanho:
            return None
        tamanho = int.from_bytes(dados[posicao : posicao + bytes_do_tamanho], "big")
        posicao += bytes_do_tamanho
    return (posicao, posicao + tamanho) if len(dados) >= posicao + tamanho else None


def _resultado(codigo: int, referral: str | None) -> bytes:
    """Corpo de um LDAPResult (RFC 4511 § 4.1.9); o referral só acompanha o código 10."""
    corpo = _tlv(0x0A, bytes([codigo])) + _tlv(0x04, b"") + _tlv(0x04, TEXTO_DO_SERVIDOR.encode())
    if codigo == REFERRAL and referral is not None:
        corpo += _tlv(0xA3, _tlv(0x04, referral.encode()))  # Referral, [3] IMPLICIT
    return corpo


def _entrada_da_ana() -> bytes:
    atributos = b"".join(
        _tlv(0x30, _tlv(0x04, nome) + _tlv(0x31, _tlv(0x04, valor)))
        for nome, valor in ((b"uid", b"ana"), (b"mail", b"ana@teste"), (b"cn", b"Ana"))
    )
    return _tlv(0x04, ANA.dn.encode()) + _tlv(0x30, atributos)


def _escutar(
    escuta: socket.socket, parar: threading.Event, atender: Callable[[socket.socket], None]
) -> None:
    """Atende uma conexão por vez até `parar`."""
    escuta.settimeout(0.1)
    while not parar.is_set():
        try:
            conexao, _ = escuta.accept()
        except TimeoutError:
            continue
        except OSError:
            return
        with conexao, contextlib.suppress(OSError):  # inclui ssl.SSLError
            conexao.settimeout(5)
            atender(conexao)


@dataclass
class ServidorLdap:
    """LDAPS que responde ao bind e a cada busca (a entrada da Ana e o `searchResDone`) com os
    resultados dados, até o unbind."""

    contexto: ssl.SSLContext
    resultado_do_bind: bytes
    resultado_da_busca: bytes

    def atender(self, conexao: socket.socket) -> None:
        with self.contexto.wrap_socket(conexao, server_side=True) as tls:
            recebidos = b""
            while dados := tls.recv(4096):
                recebidos += dados
                while (mensagem := _elemento(recebidos)) is not None:
                    inicio, fim = mensagem
                    if not self._responder(tls, recebidos[inicio:fim]):
                        return
                    recebidos = recebidos[fim:]

    def _responder(self, tls: ssl.SSLSocket, mensagem: bytes) -> bool:
        """Responde a uma LDAPMessage com o mesmo messageID; False no unbind."""
        id_da_mensagem = _elemento(mensagem)
        assert id_da_mensagem is not None
        cabecalho, operacao = mensagem[: id_da_mensagem[1]], mensagem[id_da_mensagem[1]]

        def enviar(tag: int, corpo: bytes) -> None:
            tls.sendall(_tlv(0x30, cabecalho + _tlv(tag, corpo)))

        if operacao == BIND_REQUEST:
            enviar(BIND_RESPONSE, self.resultado_do_bind)
        elif operacao == SEARCH_REQUEST:
            enviar(SEARCH_RES_ENTRY, _entrada_da_ana())
            enviar(SEARCH_RES_DONE, self.resultado_da_busca)
        return operacao != UNBIND_REQUEST


@dataclass
class HostDoReferral:
    """O host para onde o referral aponta, em claro: guarda o que chegar e fecha a conexão."""

    recebido: bytearray = field(default_factory=bytearray)

    def atender(self, conexao: socket.socket) -> None:
        self.recebido.extend(conexao.recv(4096))


@contextmanager
def _diretorio_com_referral(
    tmp_path: Path, ca: Autoridade, *, codigo_do_bind: int, codigo_da_busca: int
) -> Iterator[tuple[Ldap3Directory, HostDoReferral]]:
    """O adaptador de produção (LDAPS, CA e nome conferidos) contra um servidor que responde com
    os códigos dados; o 10 da busca aponta para outro host, em `ldap://`."""
    cert, key = _certificado_do_servidor(ca, "localhost", tmp_path)
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(cert, key)
    destino, parar = HostDoReferral(), threading.Event()
    with (
        socket.create_server(("127.0.0.1", 0)) as escuta_do_destino,
        socket.create_server(("127.0.0.1", 0)) as escuta,
    ):
        referral = f"ldap://127.0.0.1:{escuta_do_destino.getsockname()[1]}/ou=pessoas,dc=teste"
        # O bindResponse vai sem a URL: o decodificador do `ldap3` 2.9.1 não lê o campo
        # referral nele (KeyError) e por isso nunca o seguiria.
        servidor = ServidorLdap(
            contexto, _resultado(codigo_do_bind, None), _resultado(codigo_da_busca, referral)
        )
        threads = [
            threading.Thread(target=_escutar, args=(sock, parar, atender), daemon=True)
            for sock, atender in ((escuta_do_destino, destino.atender), (escuta, servidor.atender))
        ]
        for thread in threads:
            thread.start()
        try:
            url = f"ldaps://localhost:{escuta.getsockname()[1]}"
            yield _diretorio(url, _gravar_ca(ca, tmp_path), start_tls=False), destino
        finally:
            parar.set()
            for thread in threads:
                thread.join(timeout=10)


def _so_a_mensagem_generica(erro: DirectoryUnavailable) -> None:
    """Nem a senha, nem a URL do referral, nem o texto do servidor (security.md § Segredos)."""
    texto = f"{erro} {erro.args!r}"
    for proibido in (SENHA_DO_SERVICO, "127.0.0.1", TEXTO_DO_SERVIDOR):
        assert proibido not in texto
    assert erro.__cause__ is None


OPERACOES: dict[str, Callable[[Ldap3Directory], Awaitable[object]]] = {
    "snapshot": lambda diretorio: diretorio.snapshot(),
    "find_user": lambda diretorio: diretorio.find_user("ana"),
    "groups_of": lambda diretorio: diretorio.groups_of(ANA),
}


@pytest.mark.parametrize("operacao", list(OPERACOES))
@pytest.mark.parametrize(
    "codigo",
    [
        pytest.param(REFERRAL, id="referral"),
        pytest.param(SIZE_LIMIT_EXCEEDED, id="size-limit"),
        pytest.param(TIME_LIMIT_EXCEEDED, id="time-limit"),
    ],
)
async def test_busca_sem_sucesso_fica_indisponivel_sem_seguir_referral(
    tmp_path: Path, autoridades: tuple[Autoridade, Autoridade], codigo: int, operacao: str
) -> None:
    """004/R1.13, R1.7, R1.10, R2.1 (o referral não é seguido: nenhum byte chega ao outro host;
    a busca cortada não vira retrato parcial; a sincronização e o login falham fechados)"""
    with (
        _diretorio_com_referral(
            tmp_path, autoridades[0], codigo_do_bind=SUCESSO, codigo_da_busca=codigo
        ) as (diretorio, destino),
        pytest.raises(DirectoryUnavailable) as erro,
    ):
        await OPERACOES[operacao](diretorio)

    assert destino.recebido == b""
    _so_a_mensagem_generica(erro.value)


async def test_bind_com_referral_falha_fechado_sem_seguir(
    tmp_path: Path, autoridades: tuple[Autoridade, Autoridade]
) -> None:
    """004/R1.13, R2.1 (bind que volta com referral não é seguido: a conta de serviço deixa o
    diretório indisponível e a senha do usuário não confere)"""
    with _diretorio_com_referral(
        tmp_path, autoridades[0], codigo_do_bind=REFERRAL, codigo_da_busca=SUCESSO
    ) as (diretorio, destino):
        with pytest.raises(DirectoryUnavailable) as erro:
            await diretorio.find_user("ana")
        assert await diretorio.verify_password(ANA.dn, SENHA_DA_ANA) is False

    assert destino.recebido == b""
    _so_a_mensagem_generica(erro.value)
