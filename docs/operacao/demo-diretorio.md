# Demonstração do diretório: LDAP e OIDC

Roteiro da spec 004 (R5.3, R1.13, R3.9; design § Roteiro e ferramenta). Mostra, no ambiente local, a sincronização criando, alterando e desativando usuários e grupos, o mapeamento de um grupo para um papel, o login LDAP com 2FA, o login OIDC pela tela e a recusa de certificado LDAP. Leva uns 15 minutos.

- **Estado em 26/11/2026: conferido na 004/T14**, pelos testes abaixo, contra o compose. Os números dos passos 1 e 2 e o corpo do passo 3 são os que eles conferem.
- **Testes que automatizam o roteiro:** `tests/e2e/test_sync_ldap.py` e `tests/e2e/test_login_ldap_oidc.py`, com `-m slow`.
- **Senhas:** as do laboratório (`sgs-lab-exemplo-*`) são fixas, versionadas e só locais (D004-15); a API as recusa em `prod` (R5.4). A senha do administrador local é sua: digite-a quando o comando pedir e não a grave em arquivo.

## 0. Preparar
1. Suba o ambiente do zero. O `down -v` apaga os volumes, e o diretório volta à carga inicial (`docker/ldap/seed.ldif`):

   ```bash
   docker compose -f docker/compose.yml down -v
   docker compose -f docker/compose.yml up -d --build --wait
   ```

2. Crie o administrador local (README § Dados de demonstração e primeiro administrador):

   ```bash
   read -rsp 'Senha do admin: ' SGS_SENHA_INICIAL; echo
   docker compose -f docker/compose.yml exec -e SGS_SENHA_INICIAL="$SGS_SENHA_INICIAL" api \
     sgs-admin create-user --username admin --nome "Administrador"
   ```

   Ele é quem dispara a primeira sincronização e cria os mapeamentos: ninguém do diretório tem papel antes deles.
3. Prepare o terminal. O `curl -k` aceita o certificado `tls internal` do Caddy, como nos outros guias. Use isso só no laboratório.

   ```bash
   API=https://localhost/api/v1   # com SGS_HTTPS_PORT, use a porta de SGS_PUBLIC_URL
   json() { curl -sk -H 'Content-Type: application/json' "$@"; }
   totp() { uv run python -c 'import sys, urllib.parse as u, pyotp
   q = u.parse_qs(u.urlsplit(sys.argv[1]).query)
   print(pyotp.TOTP(q["secret"][0]).now())' "$1"; }
   ```

4. Entre como administrador. No primeiro acesso, o 2FA é cadastrado aqui, e `totp` gera o código a partir da URI:

   ```bash
   read -rsp 'Senha do admin: ' SENHA; echo
   MFA=$(jq -n --arg p "$SENHA" '{username: "admin", password: $p}' | json "$API/auth/login" -d @- | jq -r .mfa_token)
   unset SENHA
   URI_ADMIN=$(json "$API/auth/mfa/enroll" -d "{\"mfa_token\": \"$MFA\"}" | jq -r .otpauth_uri)
   ADMIN=$(json "$API/auth/mfa/confirm" -d "{\"mfa_token\": \"$MFA\", \"code\": \"$(totp "$URI_ADMIN")\"}" | jq -r .access_token)
   ```

   Nos acessos seguintes, a resposta do login traz `mfa_required: true`, e o código vai para `/auth/mfa/verify`, com a mesma `URI_ADMIN`.

## 1. Sincronizar e ver a execução (R1.1, R1.5, R1.9)
```bash
EXEC=$(json -X POST "$API/admin/diretorio/sincronizar" -H "Authorization: Bearer $ADMIN" | jq -r .execucao_id)
sleep 3
json "$API/admin/diretorio/execucoes/$EXEC" -H "Authorization: Bearer $ADMIN" | jq '{status, usuarios, grupos, conflitos}'
```

- **Esperado:** `status: "concluida"`, `usuarios.criados: 8` (um por papel, mais `ldap.temporario`) e `grupos.criados: 7`, sem conflitos.
- **Uma sincronização por vez:** um segundo `POST` enquanto a primeira roda responde 409.
- **Grupos espelhados:** a lista está em `GET $API/admin/diretorio/grupos?origem=ldap`.

## 2. Alterar e apagar no diretório, e sincronizar de novo (R1.6–R1.8)
As alterações usam o `ldapi` de dentro do contêiner, o mesmo caminho da carga inicial. O compose não publica porta LDAP no host.

```bash
# muda o nome de exibição de uma pessoa
docker compose -f docker/compose.yml exec -T ldap ldapmodify -Y EXTERNAL -H ldapi:/// <<'LDIF'
dn: uid=ldap.diretoria,ou=pessoas,dc=recife,dc=pe,dc=gov,dc=br
changetype: modify
replace: cn
cn: Diretoria Executiva (fictício)
LDIF

# apaga a pessoa do contrato temporário
docker compose -f docker/compose.yml exec ldap ldapdelete -Y EXTERNAL -H ldapi:/// \
  uid=ldap.temporario,ou=pessoas,dc=recife,dc=pe,dc=gov,dc=br

EXEC=$(json -X POST "$API/admin/diretorio/sincronizar" -H "Authorization: Bearer $ADMIN" | jq -r .execucao_id)
sleep 3
json "$API/admin/diretorio/execucoes/$EXEC" -H "Authorization: Bearer $ADMIN" | jq '{status, usuarios, grupos}'
```

- **Esperado:** `usuarios.criados: 0` e `usuarios.desativados: 1` (`ldap.temporario`). O `usuarios.atualizados` conta todas as pessoas que continuam no diretório, mudadas ou não (design, passo 3.3; nota N8 da revisão da frente A), e não só a do nome.
- **A conta não é apagada, só desativada (R1.7):** o histórico e a auditoria dela continuam.
- **Sem o *overlay* `refint`** (nota da 004/T13), o DN apagado continua no `member` de `sgs-tecnico-ds3`. A sincronização ignora membro que não é pessoa encontrada, e os 7 grupos continuam (`GET $API/admin/diretorio/grupos?origem=ldap` com `total: 7`).

## 3. Mapear um grupo para um papel (spec 003, R3.1)
O grupo `sgs-tecnico-ds3` vira o papel `TECNICO_DISTRITAL` com escopo no Distrito Sanitário III. Os membros ativos ganham a atribuição de origem `group` na hora.

```bash
GRUPO=$(json "$API/admin/diretorio/grupos?origem=ldap&busca=sgs-tecnico-ds3" -H "Authorization: Bearer $ADMIN" | jq -r '.itens[0].id')
ID_DS3=$(docker compose -f docker/compose.yml exec -T db psql -U sgs sgs -Atc "SELECT id FROM districts WHERE code = 'DS-III'")
json -X POST "$API/admin/mapeamentos-grupo" -H "Authorization: Bearer $ADMIN" \
  -d "{\"grupo_id\": \"$GRUPO\", \"papel\": \"TECNICO_DISTRITAL\", \"escopo_tipo\": \"distrito\", \"escopo_id\": \"$ID_DS3\"}"
```

Para os outros papéis, repita com o grupo de cada um. Os nomes estão no README § Diretório LDAP de laboratório.

## 4. Login LDAP com 2FA (R2)
É o login da spec 002, com `provider: "ldap"`. A senha é conferida por *bind* no diretório, e o resto (bloqueio, 2FA, sessão, auditoria) segue a 002.

```bash
LOGIN=$(json "$API/auth/login" -d '{"username": "ldap.tecnico.ds3", "password": "sgs-lab-exemplo-usuario", "provider": "ldap"}')
echo "$LOGIN" | jq '{mfa_required, mfa_enrollment_required}'   # primeiro acesso: cadastro do 2FA
MFA=$(echo "$LOGIN" | jq -r .mfa_token)
URI_DS3=$(json "$API/auth/mfa/enroll" -d "{\"mfa_token\": \"$MFA\"}" | jq -r .otpauth_uri)
DS3=$(json "$API/auth/mfa/confirm" -d "{\"mfa_token\": \"$MFA\", \"code\": \"$(totp "$URI_DS3")\"}" | jq -r .access_token)
json "$API/me" -H "Authorization: Bearer $DS3" | jq
```

- **Esperado:** o `/me` mostra `TECNICO_DISTRITAL` no DS-III, de origem `group`, vindo do mapeamento do passo 3.
- **Senha errada e conta apagada** respondem o mesmo 401 genérico: `ldap.temporario` não entra mais.
- **No navegador:** a escolha de LDAP na tela de login fica fora da 004 (§ Decisões do G2). O login LDAP é demonstrado pela API.

## 5. Login OIDC pela tela (R3.1–R3.4, R3.9)
1. Abra `https://localhost/` (ou o endereço de `SGS_PUBLIC_URL`). Com o OIDC ligado, o login mostra **Entrar pelo provedor de identidade**.
2. Clique. O navegador vai ao Keycloak (`https://keycloak.localhost`), realm `sgs`.
3. Entre com `oidc.tecnico.ds4`, senha `sgs-lab-exemplo-usuario`.
4. O Keycloak volta ao callback da API, que confere `state`, `nonce` e o `id_token` e redireciona ao front. Nenhum token passa pela URL (R3.4): o front abre a sessão pela renovação, com o cookie de refresh.
5. **Esperado:** a tela "sem acesso" (`#/sem-acesso`), porque a conta ainda não tem papel. O grupo `oidc-tecnico-ds-iv` é espelhado no primeiro login e ainda não tem mapeamento. Mapeie-o como no passo 3 (`origem=oidc`, Distrito IV) e entre de novo: o papel aparece.

- **Recusa:** qualquer falha no retorno, como `state` vencido, `id_token` inválido ou conta inativa, volta ao login com "Não foi possível entrar pelo provedor de identidade. Tente de novo.". A auditoria grava `auth.oidc_failed` com o motivo.
- **Usuários do Keycloak** são outros, sem federação com o `slapd` (D004-7). Os nomes estão no README § Provedor OIDC de laboratório.

## 6. Recusa de certificado LDAP (R1.13)
O `sgs-admin diretorio testar` tenta a conexão e o *bind* da conta de serviço sem gravar nada, e responde `ok` ou o motivo genérico.

```bash
# configuração do compose: CA de laboratório e nome certo
docker compose -f docker/compose.yml exec api sgs-admin diretorio testar
# CA errada: a do banco, que não emitiu o certificado do LDAP
docker compose -f docker/compose.yml exec api sgs-admin diretorio testar --ca /certs/ca.crt
# nome errado: o mesmo servidor por um alias que não está no certificado
docker compose -f docker/compose.yml exec api sgs-admin diretorio testar --url ldaps://ldap-nome-errado:636
```

- **Esperado:** `ok` no primeiro e recusa por certificado nos outros dois, antes de qualquer *bind*: nenhuma credencial sai da API.
- **Na sincronização:** a mesma falha numa sincronização marca a execução como `falhou`, com erro genérico (R1.10).

## Pela tela (spec 014)
Os passos 1 e 3 também podem ser feitos pela tela, entrando como Admin TI:
1. **Diretório → Execuções** (`#/diretorio/execucoes`): **Sincronizar agora** cria a execução, que aparece Em andamento e vira Concluída sozinha; **Detalhes** mostra as contagens e os conflitos. Uma segunda sincronização durante a primeira dá o aviso "Já há uma sincronização em andamento." (409).
2. **Diretório → Grupos** (`#/diretorio/grupos`): a lista traz os grupos espelhados; **Mapear** escolhe o papel e, se o papel exigir, o id do escopo (o Admin TI não lê as tabelas de referência, então o id é digitado e a API o confere). O mapeamento aparece em Mapeamentos, com **Remover**.
- **Teste que automatiza:** `uv run pytest -m slow tests/e2e_front/test_diretorio.py`.

## Voltar ao início
```bash
docker compose -f docker/compose.yml down -v
```

Apaga os volumes do banco e do diretório, e a próxima subida volta à carga inicial.
