-- Objetivo: dizer se um tipo de unidade existe nas referências, ativo ou não.
-- Justificativa: o filtro `tipo` das consultas de qualidade é conferido antes de a consulta
--   rodar, para um tipo inexistente dar 422 apontando o campo, e não uma lista vazia que
--   pareceria "nenhuma lacuna" (011/R2.9). Tipo desativado (exclusão lógica, decisão U5)
--   continua filtrável: as unidades dele seguem no cadastro.
--   - Lê só a tabela de referência, que não tem escopo de leitura: por isso não leva o fragmento
--     de escopo das consultas de dados.
-- Uso: SqlConsultasDashboard.tipo_de_unidade_existe, nas rotas GET /api/v1/dashboard/consultas/*
--   com filtro de tipo (011/T11).
-- Requisitos: 011/R2.9
SELECT EXISTS (
    SELECT 1
    FROM unit_types
    WHERE id = :unit_type_id
);
