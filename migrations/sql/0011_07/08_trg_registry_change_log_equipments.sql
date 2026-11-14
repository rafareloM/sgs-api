-- Objetivo: disparar `trg_registry_change_log()` em toda inclusão, alteração e exclusão de
--   equipamento, linha a linha.
-- Justificativa: o log do banco registra o equipamento venha a escrita de onde vier (011/R7.1).
--   - Inclui a alteração em cascata: corrigir o código de um tipo de equipamento atualiza os
--     equipamentos do tipo pela FK com ON UPDATE CASCADE (011/R9.2), e cada um aparece no log
--     como alteração própria, com o código de/para (011/R7.5).
--   - AFTER e FOR EACH ROW, como na unidade (07).
-- Uso: `equipments`; o log é lido em `GET /auditoria/banco` (011/T15).
-- Requisitos: 011/R7.1, 011/R7.5
CREATE TRIGGER trg_registry_change_log
    AFTER INSERT OR UPDATE OR DELETE ON equipments
    FOR EACH ROW
    EXECUTE FUNCTION trg_registry_change_log();
