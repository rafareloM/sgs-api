-- Objetivo: disparar `trg_registry_change_log()` em toda inclusão, alteração e exclusão de
--   unidade de saúde, linha a linha.
-- Justificativa: o log do banco registra a unidade venha a escrita de onde vier: API,
--   `sp_deactivate_unit`, superusuário (011/R7.1, R7.2).
--   - AFTER: a linha já passou pelo trigger de versão (BEFORE) e tem a coluna gerada
--     `name_normalized` calculada; num BEFORE, ela chegaria nula (achado da 011/T5). E só o que
--     de fato foi gravado entra no log: uma escrita que falha numa restrição não deixa linha.
--   - FOR EACH ROW: cada unidade alterada vira um registro, com o seu identificador e o seu
--     de/para.
-- Uso: `health_units`; o log é lido em `GET /auditoria/banco` (011/T15).
-- Requisitos: 011/R7.1
CREATE TRIGGER trg_registry_change_log
    AFTER INSERT OR UPDATE OR DELETE ON health_units
    FOR EACH ROW
    EXECUTE FUNCTION trg_registry_change_log();
