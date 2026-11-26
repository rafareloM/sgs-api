# LDAP de laboratório (spec 004, R5.1; design § `slapd`): OpenLDAP do Debian estável, escutando
# só LDAPS (636) e ldapi. O cn=config sai do config.ldif no build; a carga inicial (seed.ldif)
# entra pelo ldapi na primeira subida (iniciar.sh). Usuários, grupos e senhas no README.
FROM debian:trixie-slim

# uid e gid fixos (389), criados antes do pacote: o servicos-certs entrega a chave do servidor a
# esse uid (docker/servicos/gerar-certificados.sh).
RUN groupadd --system --gid 389 openldap \
    && useradd --system --uid 389 --gid openldap --home-dir /var/lib/ldap --no-create-home \
        --shell /usr/sbin/nologin openldap

# Sem a configuração padrão do pacote (domínio pelo nome da máquina): a nossa vem do config.ldif.
RUN echo "slapd slapd/no_configuration boolean true" | debconf-set-selections \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        slapd ldap-utils \
    && rm -rf /var/lib/apt/lists/*

COPY config.ldif seed.ldif /etc/ldap/sgs/
COPY --chmod=0755 iniciar.sh /usr/local/bin/iniciar-slapd

RUN rm -rf /etc/ldap/slapd.d /var/lib/ldap \
    && install -d -m 0750 -o openldap -g openldap /etc/ldap/slapd.d /var/lib/ldap /run/slapd \
    && slapadd -n 0 -F /etc/ldap/slapd.d -l /etc/ldap/sgs/config.ldif \
    && chown -R openldap:openldap /etc/ldap/slapd.d

USER openldap
ENTRYPOINT ["/usr/local/bin/iniciar-slapd"]
