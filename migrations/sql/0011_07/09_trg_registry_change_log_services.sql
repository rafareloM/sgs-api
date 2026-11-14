-- Objetivo: disparar `trg_registry_change_log()` em toda inclusão, alteração e exclusão de
--   serviço, linha a linha.
-- Justificativa: o log do banco registra o serviço venha a escrita de onde vier (011/R7.1).
--   - Inclui a alteração em cascata: excluir um equipamento desliga dele os seus serviços pela
--     FK com ON DELETE SET NULL (011/R9.1), e cada serviço aparece no log como alteração
--     própria, com `equipment_id` de/para (011/R7.5).
--   - AFTER e FOR EACH ROW, como na unidade (07).
-- Uso: `services`; o log é lido em `GET /auditoria/banco` (011/T15).
-- Requisitos: 011/R7.1, 011/R7.5
CREATE TRIGGER trg_registry_change_log
    AFTER INSERT OR UPDATE OR DELETE ON services
    FOR EACH ROW
    EXECUTE FUNCTION trg_registry_change_log();
