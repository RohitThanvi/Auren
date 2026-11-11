#!/bin/sh
# Runs once on first initialisation of the Postgres data volume (development only).
# Creates the isolated database used by the API test suite so tests never touch dev data.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "CREATE DATABASE ${POSTGRES_DB}_test OWNER ${POSTGRES_USER}"
