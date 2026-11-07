-- Objetivo: impedir duas unidades com o mesmo CNES, deixando várias sem CNES.
-- Justificativa: o CNES é a chave natural da unidade no cadastro federal; repeti-lo é cadastrar a
--   mesma unidade duas vezes (006/R1.3), e o caso de uso devolve 409 apontando a existente.
--   Índice parcial (`WHERE cnes IS NOT NULL`): unidade sem CNES é aceita (006/R1.5) e não entra
--   no índice. Também atende à busca por CNES exato.
-- Uso: unicidade na criação e na alteração de unidade (006/T3, T5) e busca por CNES (006/T4).
-- Requisitos: 006/R1.3, 006/R1.5
CREATE UNIQUE INDEX ix_health_units_cnes ON health_units (cnes) WHERE cnes IS NOT NULL;
