\set ON_ERROR_STOP on
\getenv app_user POSTGRES_APP_USER
\getenv app_password POSTGRES_APP_PASSWORD
\getenv ro_password WORKBENCH_RO_PASSWORD
\getenv db POSTGRES_DB

-- psql quotes identifiers and literals independently. Never interpolate raw secrets.
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE workbench_ro LOGIN PASSWORD :'ro_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"app_user", workbench_ro;
GRANT USAGE ON SCHEMA public TO :"app_user", workbench_ro;
ALTER ROLE workbench_ro SET default_transaction_read_only = on;
ALTER ROLE workbench_ro SET statement_timeout = '15s';
ALTER ROLE :"app_user" SET statement_timeout = '15s';
