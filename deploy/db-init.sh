#!/bin/sh
set -eu
# Password is supplied through a container environment; never echoed.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=app_password="$S4_DB_APP_PASSWORD" --set=ON_ERROR_STOP=1 <<'SQL'
SELECT format('CREATE ROLE s4_app LOGIN PASSWORD %L', :'app_password') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE s4_dev TO s4_app;
GRANT USAGE ON SCHEMA public TO s4_app;
ALTER DEFAULT PRIVILEGES FOR ROLE s4_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO s4_app;
ALTER DEFAULT PRIVILEGES FOR ROLE s4_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO s4_app;
CREATE DATABASE s4_test OWNER s4_owner;
SQL
