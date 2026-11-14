-- Objetivo: deixar o `sgs_owner` usar o schema `public` e criar objetos nele.
-- Justificativa: a tabela do log do banco é criada com `SET LOCAL ROLE sgs_owner` (011/T7), para
--   nascer com ele como dono, e as partições mensais são criadas pelo procedimento que roda com o
--   privilégio dele (011/T8). Desde o PostgreSQL 15, PUBLIC não cria no `public`; sem este
--   GRANT, as duas coisas falham. Nada além do schema da aplicação (011/R10.2).
-- Uso: `db_change_log` e suas partições, `sp_ensure_monthly_partitions` (011/T7, T8).
-- Requisitos: 011/R10.2
GRANT USAGE, CREATE ON SCHEMA public TO sgs_owner;
