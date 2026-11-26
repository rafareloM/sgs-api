-- Objetivo: achar os pedidos de relatório ainda abertos (`pendente` ou `gerando`).
-- Justificativa: na subida da API, os pedidos abertos viram `falhou` com "Interrompido" (design
--   da 005 § Geração e envio, passo 8), porque a geração roda em segundo plano numa instância
--   só. Índice parcial: só os abertos entram, e eles são poucos perto dos concluídos e falhos,
--   que só crescem.
-- Uso: `SqlRepositorioDePedidos.marcar_interrompidos` (005/T1), chamado na subida (005/T5).
-- Requisitos: 005/R2.6
CREATE INDEX ix_report_jobs_status_aberto ON report_jobs (status)
    WHERE status IN ('pendente', 'gerando');
