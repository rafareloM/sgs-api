-- Objetivo: uma foto única e só de leitura para toda a geração de um relatório.
-- Justificativa: o arquivo sai por cursor do servidor, em lotes; em REPEATABLE READ, todos os
--   lotes veem o mesmo instante do banco, e READ ONLY garante que a geração não grava nada
--   (design da 005 § Geração e envio, passo 2). Precisa ser o primeiro comando da transação.
-- Uso: geração do relatório (005/T5), antes da consulta do tipo.
-- Requisitos: 005/R1.3
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY
