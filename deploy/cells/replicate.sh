#!/usr/bin/env bash
# Sets up each cell's database being copied into the other (ADR-027), by Postgres logical replication. Run on the laptop
# (cell B) with both cells up and the phone (cell A) reachable over SSH. Safe to run again: what exists is left alone.
#
#   deploy/cells/replicate.sh
#
#   cell A (phone)  database sprout   --publication cell_a-->  laptop  database sprout_a  (subscription from_a)
#   cell B (laptop) database sprout   --publication cell_b-->  phone   database sprout_b  (subscription from_b)
#
# Each copy starts with the publisher's schema (taken now) and its whole data (copied by the subscription), then
# follows every change. The connection runs through Cloudflare (pg-a-..., pg-b-...): the laptop's pgpeer container and
# the phone's pgpeer piece hold the client end. A migration that changes a table must reach the copy before the
# original (deploy/phone/rehearse.py and up.sh apply it to both): logical replication carries rows, not DDL.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../laptop"
set -a; . data/.env; set +a
PHONE="${PHONE:-u0_a1@192.168.0.6}"
SSH=(ssh -i "${PHONE_KEY:-$HOME/.ssh/backseat_phone}" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes "$PHONE")
PG=(docker exec -i -e PGPASSWORD="$SPROUT_DB_PASSWORD" sprout-laptop-postgres-1 psql -U sprout -v ON_ERROR_STOP=1 -q)
export MSYS_NO_PATHCONV=1

echo "> cell B publishes its database"
"${PG[@]}" -d sprout -v pw="$CELL_B_REPLICATOR_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE replicator LOGIN REPLICATION' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'replicator') \gexec
ALTER ROLE replicator PASSWORD :'pw';
DO $$ DECLARE s text; BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO replicator', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO replicator', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE sprout IN SCHEMA %I GRANT SELECT ON TABLES TO replicator', s);
  END LOOP;
END $$;
SELECT 'CREATE PUBLICATION cell_b FOR ALL TABLES' WHERE NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'cell_b') \gexec
SQL

DUMP=(pg_dump --schema-only --no-owner --no-privileges --no-publications --no-subscriptions)

echo "> cell A's database copied here (sprout_a)"
if [ "$("${PG[@]}" -d sprout -Atc "SELECT count(*) FROM pg_database WHERE datname = 'sprout_a'")" = 0 ]; then
  "${PG[@]}" -d sprout -c "CREATE DATABASE sprout_a OWNER sprout"
  "${SSH[@]}" "${DUMP[*]} -d sprout" | "${PG[@]}" -d sprout_a >/dev/null
fi
if [ "$("${PG[@]}" -d sprout_a -Atc "SELECT count(*) FROM pg_subscription WHERE subname = 'from_a'")" = 0 ]; then
  "${PG[@]}" -d sprout_a -v pw="$CELL_A_REPLICATOR_PASSWORD" <<'SQL'
SELECT format('CREATE SUBSCRIPTION from_a CONNECTION %L PUBLICATION cell_a WITH (copy_data = true)',
              'host=pgpeer port=5432 dbname=sprout user=replicator sslmode=disable password=' || :'pw') \gexec
SQL
fi

echo "> cell B's database copied into the phone (sprout_b)"
if [ "$("${SSH[@]}" "psql -d postgres -Atc \"SELECT count(*) FROM pg_database WHERE datname = 'sprout_b'\"")" = 0 ]; then
  "${SSH[@]}" "psql -d postgres -q -c 'CREATE DATABASE sprout_b OWNER sprout'"
  docker exec -e PGPASSWORD="$SPROUT_DB_PASSWORD" sprout-laptop-postgres-1 ${DUMP[*]} -U sprout -d sprout \
    | "${SSH[@]}" "psql -U sprout -d sprout_b -q -v ON_ERROR_STOP=1" >/dev/null
fi
if [ "$("${SSH[@]}" "psql -d sprout_b -Atc \"SELECT count(*) FROM pg_subscription WHERE subname = 'from_b'\"")" = 0 ]; then
  "${SSH[@]}" "psql -d sprout_b -q -v ON_ERROR_STOP=1 -v pw=\"\$(sed -n 's/^CELL_B_REPLICATOR_PASSWORD=//p' ~/.sprout.env)\"" <<'SQL'
SELECT format('CREATE SUBSCRIPTION from_b CONNECTION %L PUBLICATION cell_b WITH (copy_data = true)',
              'host=127.0.0.1 port=15433 dbname=sprout user=replicator sslmode=disable password=' || :'pw') \gexec
SQL
fi

echo "> state"
"${PG[@]}" -d sprout_a -Atc "SELECT 'from_a (laptop)', subenabled FROM pg_subscription"
"${SSH[@]}" "psql -d sprout_b -Atc \"SELECT 'from_b (phone)', subenabled FROM pg_subscription\""
