-- Objetivo: desativar uma unidade de saúde e devolver o status que ela tinha e a versão depois da
--   desativação.
-- Justificativa: a desativação é uma operação do próprio banco, igual venha a chamada de onde
--   vier (011/R6.1); a API só a chama e decide a auditoria pelo status anterior.
--   - `FOR UPDATE` trava a linha antes de ler o status: duas desativações simultâneas da mesma
--     unidade ficam em fila, e a segunda já lê `inativa`. Sem a trava, as duas leriam `ativa` e a
--     API gravaria a mesma desativação duas vezes na auditoria.
--   - Unidade inexistente: `RAISE` com o SQLSTATE próprio `SGS01`, que a API traduz em 404 com
--     detalhe fixo, sem repassar a mensagem do banco ao cliente (011/R6.3, 001/R4.3).
--   - Unidade já inativa: devolve a versão atual sem UPDATE, então nada muda e a versão em mãos
--     continua válida (011/R6.4, 006/R3.6).
--   - Senão, o UPDATE só troca o status; quem incrementa a versão e a data de atualização é o
--     trigger `trg_health_units_version` (0011_05), e o `RETURNING` lê a versão já incrementada.
--   - Sem COMMIT: roda dentro da transação de quem chama, junto com a auditoria da API (006/R4,
--     011/R6.2); se a transação for desfeita, a desativação também é.
--   - SECURITY INVOKER (o padrão): roda com o privilégio de quem chama. A aplicação já pode ler e
--     alterar `health_units`, então o procedimento não lhe dá poder nenhum além disso; por não ser
--     DEFINER, não pertence ao `sgs_owner` nem precisa de `search_path` fixo (design da 011 §
--     Segurança). O EXECUTE sai de PUBLIC e vai só para `sgs_app` nos próximos arquivos.
-- Uso: caso de uso de desativação da 006 (`POST /unidades/{id}/desativar`, 011/T16):
--   `CALL sp_deactivate_unit(CAST(:id AS uuid), NULL, NULL)` devolve uma linha com
--   `o_previous_status` e `o_version`.
-- Requisitos: 011/R6.1, 011/R6.3, 011/R6.4
CREATE PROCEDURE sp_deactivate_unit(
    p_unit_id uuid,
    OUT o_previous_status text,
    OUT o_version integer
)
LANGUAGE plpgsql
AS $$
BEGIN
    SELECT status, version
      INTO o_previous_status, o_version
      FROM health_units
     WHERE id = p_unit_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unidade % não existe', p_unit_id USING ERRCODE = 'SGS01';
    END IF;
    IF o_previous_status <> 'inativa' THEN
        UPDATE health_units
           SET status = 'inativa'
         WHERE id = p_unit_id
        RETURNING version INTO o_version;
    END IF;
END
$$;
