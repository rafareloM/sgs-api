-- Objetivo: instalar a extensão `unaccent`, que tira acentos de um texto.
-- Justificativa: "Espaço Mãe Coruja" e "Espaco Mae Coruja" são a mesma unidade; sem tirar os
--   acentos, a unicidade por nome (006/R1.4) deixaria passar a duplicata e a busca (006/R2.2) não
--   acharia a unidade digitada sem acento. Fica no schema `public`, que a `fn_normalize_name`
--   cita pelo nome completo. Extensão confiável (trusted): o dono do banco a instala sem ser
--   superusuário.
-- Uso: `fn_normalize_name` (03_fn_normalize_name.sql).
-- Requisitos: 006/R1.4, 006/R2.2, 011/R5.1
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;
