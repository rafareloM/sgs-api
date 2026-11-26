-- Objetivo: listar os pedidos de relatório de um usuário, do mais recente ao mais antigo.
-- Justificativa: `GET /relatorios` mostra a quem pede os próprios pedidos, mais recentes
--   primeiro (R3.5). Igualdade em `requested_by` e depois `created_at DESC`: o índice entrega as
--   linhas de quem pede já pela data, e o desempate por `id` da listagem só ordena os empates.
-- Uso: `SqlRepositorioDePedidos.listar` (005/T1), na rota `GET /relatorios` (005/T6).
-- Requisitos: 005/R3.5
CREATE INDEX ix_report_jobs_requested_by_created_at ON report_jobs (requested_by, created_at DESC);
