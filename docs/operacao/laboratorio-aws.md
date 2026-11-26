# Laboratório na AWS (Learner Lab)

Spec 005, tarefa T13 (§ Opcional, se houver conta AWS). Sobe o ambiente inteiro do compose (API, PostgreSQL, Caddy, Keycloak e LDAP) numa instância EC2 de uma conta **AWS Academy Learner Lab**, com um **bucket S3 real** no lugar do SeaweedFS. Serve para demonstrar a 004 (LDAP e OIDC) fora do `localhost` e para levar a exportação da 005 a uma conta AWS de verdade (R2.1, R2.3, R2.7, R2.8, R6.2).

Tudo é feito por `docker/aws/lab.sh`, em bash com o AWS CLI v2. Cada recurso leva a etiqueta `Projeto=sgs-lab` e é achado por ela.

| Arquivo | Papel |
|---|---|
| `docker/aws/lab.sh` | sondagem, subida, estado, lista de IPs, parar, ligar e destruir |
| `docker/aws/user-data.sh` | roteiro da primeira subida da instância (Docker, código, chaves, compose) |
| `docker/aws/compose.aws.yml` | sobreposição do `docker/compose.yml`: S3 real, sem SeaweedFS, Keycloak com *heap* menor |
| `docker/aws/Caddyfile` | proxy com nomes `sslip.io` e certificados Let's Encrypt |

## Custo e limites
- O Learner Lab dá créditos e uma sessão de cerca de 4 horas. Quando a sessão acaba, a instância para sozinha, e as credenciais copiadas deixam de valer.
- A instância é `t3.small` (2 vCPU, 2 GiB, com 2 GiB de *swap*), com 20 GiB gp3, no porte do nível gratuito.
- Os créditos de CPU são `unlimited` (decisão do Rafael, 26/11/2026). Em `standard`, o t3 novo começa sem créditos e fica preso em 20% de CPU: na primeira subida real, o build da API e o do Keycloak não terminaram. Com `unlimited`, o que passa da linha de base na subida custa uns US$ 0,05 por vCPU-hora, tirados dos créditos do lab. Parado, o laboratório fica abaixo da linha de base e não gasta créditos de CPU.
- O IP elástico custa por hora mesmo com a instância parada (cerca de US$ 0,12 por dia). Ao terminar o semestre, rode `lab.sh destruir --confirmo`.
- A chave de criptografia é a gerenciada `aws/s3`, sem custo mensal.

## Antes de começar
1. No AWS Academy, abra o Learner Lab e clique em **Start Lab**.
2. Em **AWS Details**, copie o bloco de credenciais para `~/.aws/credentials` (uma pasta `~/.aws` com o arquivo `credentials` dentro). Use um editor. Não cole as credenciais em chat, issue, commit ou arquivo do repositório. Elas trocam a cada sessão: repita este passo sempre que religar o lab.
3. Tenha no PATH: `aws` (CLI v2), `jq`, `python3`, `git` e `curl`.

```bash
aws sts get-caller-identity --query Arn --output text   # .../assumed-role/voclabs/...
```

## 1. Sondar a conta
```bash
docker/aws/lab.sh sondar
```

Confere duas coisas, num bucket temporário que é apagado no fim:
- se a `LabRole` consegue `sts:AssumeRole` nela mesma, com `ExternalId` e sessão de 900 s, que é o caminho de envio da 005/T3;
- se um `PutObject` com `aws:kms` na chave `aws/s3` passa, com SSE, chave e SHA-256 conferidos na resposta (R2.8).

Rodada do seu computador, a primeira conferência testa `voclabs → LabRole` e falha: o papel `voclabs` não está na confiança da `LabRole`. Isso é esperado. A conferência que decide roda na própria instância durante a subida, onde a `LabRole` assume a `LabRole`; o resultado aparece em `lab.sh estado`.

## 2. Subir
A instância clona o repositório público num commit fixo. O commit tem de estar no GitHub: por padrão é o `HEAD`, e `SGS_LAB_COMMIT` escolhe outro.

```bash
docker/aws/lab.sh subir
```

O comando cria, nesta ordem:
- o grupo de segurança `sgs-lab`;
- o bucket `sgs-lab-relatorios-<aleatório>`;
- o IP elástico;
- a instância.

Depois associa o IP e mostra os endereços:

| O quê | Endereço |
|---|---|
| Sistema | `https://<ip-com-traços>.sslip.io/` |
| Keycloak (console e login OIDC) | `https://keycloak.<ip-com-traços>.sslip.io/` |

O compose leva de 10 a 15 minutos para ficar no ar. Acompanhe:

```bash
docker/aws/lab.sh estado
```

O fim da subida aparece como `sgs-lab: pronto: https://...`. Se aparecer `sgs-lab: sondagem na instância FALHOU`, a exportação para o S3 não vai funcionar; veja as linhas `sgs-lab: sondar:` logo acima.

## 3. Entrar
- **Senhas do administrador e dos usuários do seed:** são geradas na instância e não saem dela. No console da AWS, abra EC2 → Instâncias → `sgs-lab` → **Conectar** → **EC2 Instance Connect** e rode `sudo cat /opt/sgs/credenciais-do-lab`. O usuário é `admin`; o 2FA é cadastrado no primeiro acesso.
- **Usuários do LDAP e do Keycloak:** os do laboratório local, descritos no README.
- **Roteiros:**
  - LDAP e OIDC: [demo-diretorio.md](demo-diretorio.md);
  - relatórios: [demo-relatorios.md](demo-relatorios.md). Na AWS, o objeto vai para o bucket real, e a URL de download aponta para `s3.amazonaws.com`.
- **Bucket:** no console da AWS, S3 → `sgs-lab-relatorios-...` → `reports/<ano>/<mês>/<tipo>/`.

## 4. Mudou de rede?
A porta 443 só abre para a lista de IPs da equipe. Se o seu IP mudar, o navegador não conecta (a porta 80 continua respondendo, só com o redirecionamento). Para liberar o IP atual:

```bash
docker/aws/lab.sh liberar-ip                                  # o seu IP (checkip.amazonaws.com)
SGS_LAB_IPS=198.51.100.7/32,203.0.113.0/24 docker/aws/lab.sh liberar-ip   # lista da equipe
```

O script recusa faixas maiores que `/16`, ou seja, nunca abre a 443 para todos.

## 5. Parar, ligar, destruir
```bash
docker/aws/lab.sh parar                  # para a instância; dados e IP ficam
docker/aws/lab.sh ligar                  # liga de novo; o compose volta sozinho
docker/aws/lab.sh destruir --confirmo    # apaga instância, IP, bucket (todas as versões) e grupo
```

Parar mantém tudo. Destruir não tem volta: os relatórios do bucket somem junto.

## 6. Evidência
`lab.sh evidencia` confere o laboratório no ar, do seu computador (o seu IP tem de estar na lista da 443), e grava `docs/operacao/evidencias/laboratorio-aws-<data>.json`. O arquivo sai sem o id da conta, sem o IP do laboratório e sem token, senha ou URL assinada.

Antes, grave a senha do administrador num arquivo só seu. Ela só existe na instância: pegue-a pela EC2 Instance Connect (`sudo cat /opt/sgs/credenciais-do-lab`, linha `admin:`).

```bash
mkdir -p ~/.config/sgs-lab && chmod 700 ~/.config/sgs-lab
(umask 077; read -rsp 'Senha do admin do lab: ' s; echo; printf '%s\n' "$s" > ~/.config/sgs-lab/senha-admin)
docker/aws/lab.sh evidencia
```

O que ela confere, nesta ordem:
1. **TLS público:** o certificado do endereço do laboratório, pelas CAs do sistema.
2. **Diretório:**
   - o administrador entra com 2FA e roda a sincronização LDAP;
   - os grupos `sgs-gestor-dados` (LDAP) e `oidc-gestor-dados` (OIDC) são mapeados para `GESTOR_DADOS`.
3. **Login LDAP com 2FA** de `ldap.gestor.dados`, com o papel vindo do grupo no `/me`.
4. **Login OIDC** de `oidc.gestor.dados`, pelo formulário do Keycloak, sem navegador:
   - início na API, callback e renovação pelo cookie;
   - nenhum token na URL;
   - depois do mapeamento, o papel aparece no `/me`.
5. **Exportação:**
   - o gestor pede o inventário em CSV, e o pedido fica `concluido`, com integridade;
   - o download pela URL pré-assinada responde 200, com o mesmo SHA-256;
   - a mesma URL sem assinatura é recusada, e a URL assinada por HTTP também.
6. **O objeto no bucket**, lido de fora da API: `aws:kms` na chave `aws/s3` e o mesmo SHA-256.
7. **A política do bucket** recusa um `PutObject` sem `aws:kms`.
8. **A configuração do bucket:** bloqueio público, versionamento, criptografia padrão, ciclo de vida e política.
9. **No CloudTrail, o `AssumeRole` da API na `LabRole`:**
   - sessão `sgs-<id>`;
   - 900 s;
   - com `ExternalId`.

   O CloudTrail pode levar alguns minutos para mostrar o evento.

O 2FA de cada usuário cadastrado pela evidência fica em `~/.config/sgs-lab/<usuário>.totp` (0600), para as execuções seguintes. Para entrar na tela com esses usuários, use a mesma URI num app autenticador.

## 7. Demonstrar um relatório no bucket
Para mostrar, ao vivo, um relatório indo para o S3: rode, depois da evidência (ela cria o mapeamento e o 2FA do gestor):

```bash
docker/aws/lab.sh relatorio          # inventário em CSV; 'lab.sh relatorio xlsx' para planilha
```

Cada etapa aparece numa linha:
1. o login de `ldap.gestor.dados` por LDAP com 2FA, com o papel `GESTOR_DADOS`;
2. o pedido e cada mudança de status (`pendente`, `gerando`, `concluido`);
3. o tamanho, a assinatura e o SHA-256, em hex (como a API guarda) e em base64 (como o console do S3 mostra);
4. o objeto no bucket, lido de fora da API (criptografia `aws:kms`, chave, checksum, versão, hora da gravação), com o link direto para ele no console da AWS;
5. o download pela URL pré-assinada, com o SHA-256 conferido.

No fim, o link pré-assinado abre direto no navegador (`xdg-open`) e não aparece no terminal: além da assinatura, ele carrega o token da sessão do `AssumeRole`, que vale 15 minutos. O terminal mostra só o mesmo endereço sem a assinatura, que o S3 recusa.

No console da AWS, abra o link do passo 4 e mostre:
- **Propriedades:** criptografia `aws:kms`, a hora da gravação e o checksum, igual ao base64 do passo 3;
- **Versões:** uma por envio.

Em CloudTrail → Histórico de eventos, filtre `AssumeRole` e mostre a sessão `sgs-<id>` daquele minuto: a API pegou credenciais de 15 minutos para o envio.

**Se a sua rede troca de IP:** algumas conexões (4G, CGNAT, VPN) mudam o IP público a cada tanto, e a 443 deixa de responder. O `relatorio` e a `evidencia` conferem a 443 antes de começar e dizem qual é o seu IP agora. Rode `lab.sh liberar-ip` logo antes de apresentar e tenha o comando à mão.

## O que muda em relação ao compose local
| Peça | Local | AWS |
|---|---|---|
| S3 | SeaweedFS em `s3.localhost`, chave fixa de exemplo, `AES256` | bucket real, `AssumeRole` na `LabRole` a cada operação, `aws:kms` com `aws/s3`, sem chave fixa |
| Certificados públicos | CA interna do Caddy (`tls internal`) | Let's Encrypt, pelo desafio HTTP-01 na porta 80 |
| Nomes | `localhost`, `keycloak.localhost` | `<ip>.sslip.io`, `keycloak.<ip>.sslip.io` |
| Chaves da API | geradas por quem desenvolve, em `secrets/` | geradas na instância, em `/opt/sgs/sgs-api/secrets/` |
| `APP_ENV` | `dev` | `dev` (decisão do Rafael, 26/11/2026) |

O LDAP, o Keycloak e a conexão da API com eles não mudam: a CA de laboratório continua valendo dentro da instância, e nenhuma porta de LDAP ou do Keycloak fica exposta.

## Diferenças em relação ao documento da T7
O [exemplo de IAM e STS](../architecture/aws-iam-exemplo.md) (005/T7) descreve a conta de produção. O Learner Lab não deixa criar papel nem chave, então o laboratório se afasta dele em quatro pontos:

| T7 (produção) | Laboratório | Consequência |
|---|---|---|
| Papel próprio `sgs-report-writer`, só com `PutObject`, `GetObject` e `DeleteObjectVersion` em `reports/*` | `LabRole`, que já existe e pode bem mais | o menor privilégio do papel não é demonstrado |
| Confiança exige o `ExternalId` combinado | a confiança da `LabRole` não tem condição | a API envia o `ExternalId`, mas a AWS não o confere |
| Chave KMS própria | chave gerenciada `aws/s3` | mesma conferência da R2.8 (ARN da chave na resposta), sem a política própria da chave |
| `APP_ENV=prod`, com as recusas da R2.9 | `APP_ENV=dev` | as recusas da R2.9 seguem provadas pelos testes, não pela conta |

O que o laboratório prova numa conta real:
- o envio com credenciais temporárias de 15 minutos (R2.1), sem chave fixa (R2.2);
- `aws:kms` e SHA-256 conferidos na resposta (R2.3, R2.8);
- HTTPS obrigatório (R2.7) e a política do bucket recusando o que chega sem TLS ou sem `aws:kms`;
- o bucket privado, versionado e com a guarda de 90 dias;
- o download pela URL pré-assinada (R6.2).

No bucket do laboratório, a regra de ciclo de vida também expira as versões anteriores em 1 dia e remove os marcadores órfãos. Isso responde o ponto 1 de § 8 do documento da T7 só para o laboratório.

## Segurança
- **Grupo de segurança:**
  - 443 só da lista da equipe;
  - 80 aberta, só para o redirecionamento e o desafio do Let's Encrypt;
  - 22 só da lista de prefixos do EC2 Instance Connect.
- **As senhas de laboratório são públicas** (estão no README). Por isso a 443 não abre para todos.
- **A instância usa o IMDSv2**, com salto 2, para a API pegar a identidade da `LabRole` de dentro do contêiner. Nenhuma credencial AWS vai para a instância ou para o compose.
- **A saída do `lab.sh` esconde o id da conta e o nome da sessão.** No Learner Lab, o nome da sessão traz o e-mail de quem roda. Ainda assim, não publique a saída sem conferir.
- **Ao terminar a sessão do dia**, clique em **End Lab**: as credenciais copiadas deixam de valer.

## Problemas comuns
| Sintoma | Causa | O que fazer |
|---|---|---|
| `sem credenciais válidas` | a sessão do lab acabou | **Start Lab** e copie de novo o bloco de **AWS Details** |
| o navegador não conecta, mas `http://` redireciona | o seu IP não está na lista da 443 | `lab.sh liberar-ip` |
| `o commit ... não está em nenhum ramo remoto` | o commit local ainda não foi para o GitHub | faça o push, ou use `SGS_LAB_COMMIT` com um commit publicado |
| `já existe a instância` | a subida anterior continua lá | `lab.sh estado`, `lab.sh ligar` ou `lab.sh destruir --confirmo` |
| aviso de certificado no navegador logo após a subida | o Let's Encrypt ainda não emitiu | espere alguns minutos; pela EC2 Instance Connect, `cd /opt/sgs/sgs-api && sudo docker compose -f docker/compose.yml -f docker/aws/compose.aws.yml logs proxy` |
| a subida não termina e o console mostra contêineres reiniciando | falta de memória | `lab.sh destruir --confirmo` e `SGS_LAB_TIPO=t3.medium lab.sh subir` (sai do nível gratuito) |
