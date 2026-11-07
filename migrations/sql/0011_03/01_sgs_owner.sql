-- Objetivo: criar o papel `sgs_owner`, dono das funções e procedimentos que rodam com o
--   privilégio de quem os criou (SECURITY DEFINER) e da tabela do log do banco.
-- Justificativa: privilégio mínimo (011/R10.2). Uma função SECURITY DEFINER roda com tudo o que
--   o dono pode; se o dono fosse o superusuário que migra, um erro na função viraria acesso
--   total ao servidor. O `sgs_owner` não tem login (ninguém conecta como ele) nem superusuário, e
--   só recebe o que as funções precisam (próximos arquivos).
--   - Papel é do servidor, não do banco: o bloco só cria se ainda não existir, como o `sgs_app`
--     da 0001, para a migração rodar em mais de um banco do mesmo servidor (os testes copiam um
--     banco-modelo; o compose pode ser recriado com o volume antigo).
-- Uso: dono de `db_change_log`, `trg_registry_change_log` e `sp_ensure_monthly_partitions`
--   (011/T7, T8); alvo dos default privileges de 05_default_privileges_sgs_owner.sql.
-- Requisitos: 011/R10.2
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sgs_owner') THEN
        CREATE ROLE sgs_owner NOLOGIN NOSUPERUSER;
    END IF;
END
$$;
