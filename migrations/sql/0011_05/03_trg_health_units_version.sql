-- Objetivo: disparar `trg_health_units_version()` em toda alteração de unidade, linha a linha.
-- Justificativa: BEFORE, porque a função escreve na própria linha (`NEW.version`,
--   `NEW.updated_at`) antes de ela ser gravada; num AFTER, seria preciso outro UPDATE. FOR EACH
--   ROW, porque cada unidade tem a sua versão. Só UPDATE: no INSERT, a versão nasce 1 e a data
--   nasce `now()` pelos valores padrão da tabela (0006/11_health_units.sql). O trigger vale para
--   qualquer escrita (API, `sp_deactivate_unit`, superusuário), o que a versão no caso de uso não
--   garantia (011/R8.1; decisão U16).
-- Uso: `health_units`; o ETag da 006 passa a refletir também as alterações feitas fora da API
--   (011/R8.3, 011/T17).
-- Requisitos: 011/R8.1, 011/R8.2
CREATE TRIGGER trg_health_units_version
    BEFORE UPDATE ON health_units
    FOR EACH ROW
    EXECUTE FUNCTION trg_health_units_version();
