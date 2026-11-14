-- Objetivo: função do trigger de versão da unidade: quando os dados de uma unidade mudam, soma 1
--   a `version` e põe a hora da transação em `updated_at`.
-- Justificativa: `version` é a versão do ETag/`If-Match` (006/R3.2). Se só o caso de uso da 006 a
--   incrementasse, uma alteração feita fora da API (procedimento, superusuário, script) não
--   invalidaria o ETag que o Gestor de Unidade tem em mãos, e o PATCH dele sobrescreveria a
--   mudança sem aviso. No banco, vale para qualquer escrita (011/R8.1; decisão U16, aprovada).
--   - A comparação é da linha inteira em JSON (`to_jsonb`), menos as colunas que não são dado da
--     unidade: `pending_issues` é uma contagem mantida pela validação (007), e mudar só ela não
--     invalida a versão (011/R8.2); `version` e `updated_at` são o que o próprio trigger escreve.
--     Assim, coluna nova na tabela entra na comparação sem mexer na função.
--   - `name_normalized` também fica de fora, além do recorte do design: a coluna gerada só é
--     calculada depois dos triggers BEFORE, e até lá chega nula em NEW; comparada, faria toda
--     alteração (até a só de `pending_issues`) incrementar a versão. Ela deriva de `name`, que
--     continua na comparação, então nenhuma mudança de nome passa sem incrementar (achado na
--     011/T5, conferido num `postgres:17`; 011, Perguntas em aberto).
--   - A lista vai numa constante `text[]`: com o literal sem tipo, o operador `-` o leria como uma
--     chave só (`jsonb - text`) e não tiraria coluna nenhuma.
--   - Com dado mudado, a versão nova é sempre `OLD.version + 1`, mesmo que o UPDATE tenha escrito
--     outra: um caso de uso que ainda somasse 1 por conta própria não pularia uma versão.
--   - UPDATE que não muda nada (`SET name = name`) devolve a linha sem tocar: a versão em mãos
--     continua válida.
--   - Sem SECURITY DEFINER: só mexe na linha que já está sendo gravada, com o privilégio de quem
--     grava. O EXECUTE sai de PUBLIC no próximo arquivo; o trigger dispara sem ele.
-- Uso: trigger `trg_health_units_version` (03); quem depende dele: caso de uso de alteração da
--   006 (`WHERE version = :esperada`, sem incrementar), `sp_deactivate_unit` (011/T6).
-- Requisitos: 011/R8.1, 011/R8.2, 006/R3.2
CREATE FUNCTION trg_health_units_version() RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    c_fora_da_comparacao constant text[] :=
        '{pending_issues,version,updated_at,name_normalized}';
BEGIN
    IF (to_jsonb(NEW) - c_fora_da_comparacao)
        IS DISTINCT FROM (to_jsonb(OLD) - c_fora_da_comparacao)
    THEN
        NEW.version := OLD.version + 1;
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END
$$;
