-- Objetivo: classificar a situação cadastral de uma unidade em `inativa`, `com_pendencias`,
--   `sem_cnes` ou `regular`.
-- Justificativa: inventário, dashboard e relatórios mostram a mesma situação; calculada num lugar
--   só, no banco, os três concordam (011/R5.3). A estrutura condicional segue a precedência
--   aprovada pelo Rafael (decisão U6, 06/11/2026), da mais grave para a mais branda:
--   1. `inativa`: unidade desativada; o resto do cadastro dela não pede ação;
--   2. `com_pendencias`: tem pendência de validação (`pending_issues > 0`). Até a 007 manter
--      essa contagem, ela fica em 0 e o valor não aparece (decisão U6);
--   3. `sem_cnes`: ativa ou em implantação, sem pendência, mas fora do cadastro federal;
--   4. `regular`: nenhum dos anteriores.
--   - Recebe a linha inteira (`health_units`), e não as colunas soltas: quem chama escreve
--     `fn_registration_status(u)` e uma coluna nova na regra não muda as chamadas.
--   - IMMUTABLE: o resultado depende só da linha recebida, sem ler tabela nenhuma.
--     PARALLEL SAFE: pode rodar em consulta paralela. `search_path` fixo, como na
--     `fn_normalize_name`: os operadores usados são sempre os do `pg_catalog`.
--   - SECURITY INVOKER (o padrão): roda com o privilégio de quem chama; não precisa de mais.
-- Uso: coluna `registration_status` da `vw_unit_inventory` (011/T4), inventário do dashboard
--   (011/T13) e relatório `inventario_unidades` da 005.
-- Requisitos: 011/R5.3
CREATE FUNCTION fn_registration_status(p_unit health_units) RETURNS text
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_unit.status = 'inativa' THEN
        RETURN 'inativa';
    ELSIF p_unit.pending_issues > 0 THEN
        RETURN 'com_pendencias';
    ELSIF p_unit.cnes IS NULL THEN
        RETURN 'sem_cnes';
    ELSE
        RETURN 'regular';
    END IF;
END
$$;
