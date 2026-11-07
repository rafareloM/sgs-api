-- Objetivo: deixar a aplicação (`sgs_app`) só ler o log do banco.
-- Justificativa: o Auditor consulta o log pela API (011/R7.7), então o login da API precisa de
--   SELECT. Nada além disso: se a credencial da aplicação vazar, quem a tiver não consegue
--   incluir, alterar, apagar nem truncar registros para esconder uma alteração (011/R7.6). A
--   única escrita é a do trigger, que roda com o privilégio do dono (`sgs_owner`).
--   - Só na tabela-mãe: a consulta pela mãe lê todas as partições conferindo o privilégio só
--     nela; as partições, atuais e futuras, ficam sem privilégio nenhum para o `sgs_app`.
-- Uso: privilégios de `db_change_log`.
-- Requisitos: 011/R7.6, 011/R10.1
GRANT SELECT ON db_change_log TO sgs_app;
