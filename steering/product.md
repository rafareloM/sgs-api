# Steering · Produto

## Problema
A Secretaria de Saúde do Recife não tem um cadastro único e governado de unidades, equipamentos e serviços de saúde. Os dados estão espalhados entre o CNES e planilhas de várias áreas, sem padrão, sem validação e sem trilha de quem alterou o quê. O maior problema, segundo o cliente, é a desatualização e a dessincronização.

## Proposta de valor
Centralizar → Validar → Controlar → Visualizar. Pilares: Confiabilidade, Controle, Simplicidade.

## Fluxo central do MVP (tem que funcionar de ponta a ponta)
Login → Cadastro/Consulta → Validação → Alteração → Auditoria → Visualização.

## Domínio (vocabulário do cliente)
- **Unidade de saúde:** tem autonomia administrativa (gestor, local fixo). Ex.: CAPS, CECON, SIM, USF, Policlínica. ~250 na rede.
- **Equipamento de saúde:** pode ou não ser uma unidade. Ex.: UTI móvel do SAMU é equipamento e não é unidade; uma unidade pode conter dois equipamentos (Policlínica + Maternidade).
- **Serviço:** ofertado dentro de uma unidade/equipamento ou "solto" (ex.: Sala de Vacinação do Shopping, Atende Gestante). Muitos não estão no CNES.
- **Distrito Sanitário (DS):** cada distrito é responsável pelas suas unidades.
- **Áreas técnicas:** Saúde Mental (escopo do grupo), Saúde Bucal, APS, Média e Alta Complexidade...
- **CNES:** cadastro federal, chave natural de unidades (7 dígitos). Integração fora do MVP.
- Cliente pediu: "fazer algo modular", para evoluir até a infraestrutura das unidades (salas, consultórios, status).

## Papéis (RBAC)
`ADMIN_TI`, `GESTOR_DADOS`, `COORD_TECNICO`, `TECNICO_DISTRITAL`, `GESTOR_UNIDADE`, `DIRETORIA`, `AUDITOR`. Matriz completa em `docs/architecture/arquitetura-conceitual.md` §4.

## Requisitos obrigatórios desta etapa (disciplinas)
1. Papéis e recursos → arquitetura conceitual.
2. RBAC → autenticação e permissão (specs 002, 003).
3. LDAP e OIDC populando usuários e grupos locais (spec 004).
4. Exportação de relatórios para S3 com autenticação avançada (spec 005).

## Fora do MVP (não implementar sem decisão registrada)
Integração real com CNES; workflow completo de aprovação; notificações; relatórios avançados e múltiplos formatos além de CSV/XLSX; IA e análises preditivas; integrações com outros sistemas municipais.

## Prazos
Desenvolvimento do MVP até 07/11/2026; validação 21/11; code freeze 28/11; SR2 05/12/2026.
