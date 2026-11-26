#!/bin/sh
# Entrada do contêiner `ldap` (spec 004, design § `slapd`). Roda como openldap (uid 389).
#
# Na primeira subida (volume ldap-data sem a marca), sobe o slapd só no ldapi, aplica a carga
# inicial (/etc/ldap/sgs/seed.ldif) como o usuário do contêiner e o para. Uma carga interrompida
# não deixa a marca: a próxima subida apaga a base e recomeça. Depois, o slapd fica em primeiro
# plano escutando só LDAPS (636) e ldapi, com o log das operações (stats) na saída de erro.
set -eu

config=/etc/ldap/slapd.d
dados=/var/lib/ldap
marca=$dados/.carga-inicial

if [ ! -e "$marca" ]; then
    rm -f "$dados"/*.mdb
    slapd -F "$config" -h ldapi:/// -d 0 &
    temporario=$!
    tentativas=0
    until ldapwhoami -Q -Y EXTERNAL -H ldapi:/// > /dev/null 2>&1; do
        tentativas=$((tentativas + 1))
        if [ "$tentativas" -ge 100 ]; then
            echo "ldap: o slapd não respondeu no ldapi" >&2
            exit 1
        fi
        sleep 0.1
    done
    ldapadd -Q -Y EXTERNAL -H ldapi:/// -f /etc/ldap/sgs/seed.ldif > /dev/null
    kill "$temporario"
    wait "$temporario" || true
    touch "$marca"
    echo "ldap: carga inicial aplicada" >&2
fi

exec slapd -F "$config" -h "ldaps:/// ldapi:///" -d stats
