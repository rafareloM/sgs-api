-- Roda só na primeira subida do volume do banco (docker-entrypoint-initdb.d).
-- Cria o papel sgs_app (o mesmo da migração 0001, que concede os privilégios) e o login da API,
-- membro dele. A senha é de desenvolvimento: a API recusa iniciar com ela em prod (001/R2.3).
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sgs_app') THEN
        CREATE ROLE sgs_app NOLOGIN;
    END IF;
END
$$;

CREATE ROLE sgs_api LOGIN PASSWORD 'sgs_api' IN ROLE sgs_app;
