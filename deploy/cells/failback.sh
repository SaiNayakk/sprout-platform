#!/usr/bin/env bash
# Moves a cell's customers home after the other cell took them over (ADR-027). Run on the laptop, with both cells up:
# the returning cell fenced (cellwatch TAKEN_OVER), the other holding it (HOLDING).
#
#   deploy/cells/failback.sh a      # the phone is back: its customers move home from the laptop
#   deploy/cells/failback.sh b      # the laptop is back: its customers move home from the phone
#
# What happens, in order (the returning cell's customers see "try again in a minute" for a few minutes):
#   1. the standby serving them takes no more writes (its fence file)
#   2. its database (the promoted copy, which has every write since the takeover) is dumped
#   3. the returning cell's own database is archived as sprout_before_failback_<time>, never deleted or merged:
#      every write it had acknowledged is in the copy already, or was replayed from the journal into it
#   4. the dump becomes the returning cell's database, published for replication again
#   5. the standby stops, its copy is dropped, and replication is set up again (replicate.sh)
#   6. both cells' cellwatch go back to NORMAL, and the returning cell's services start
set -euo pipefail
X="${1:?which cell is coming home: a or b}"
case "$X" in a) Y=b ;; b) Y=a ;; *) echo "a or b"; exit 2 ;; esac
HERE="$(cd "$(dirname "$0")" && pwd)"
LAPTOP="$HERE/../laptop"
set -a; . "$LAPTOP/data/.env"; set +a
PHONE="${PHONE:-u0_a1@192.168.0.6}"
SSH=(ssh -i "${PHONE_KEY:-$HOME/.ssh/backseat_phone}" -p 8022 -o BatchMode=yes -o IdentitiesOnly=yes "$PHONE")
export MSYS_NO_PATHCONV=1
LPG=(docker exec -i -e PGPASSWORD="$SPROUT_DB_PASSWORD" sprout-laptop-postgres-1)
cd "$LAPTOP"   # docker compose is given relative paths: a /c/... path means nothing to it on Windows
COMPOSE=(docker compose --env-file data/.env -f docker-compose.yml)
export SPROUT_WEB_IMAGE="sprout-web:$(tr -d '[:space:]' < "$LAPTOP/web.version")"
STAMP=$(date -u +%Y%m%d%H%M)
DUMP="/f/Backups/sprout/failback-$X-$STAMP.dump"
say() { printf '> %s\n' "$*"; }

if [ "$X" = a ]; then
  say "pausing cell A's writes on the laptop's standby"
  touch "$LAPTOP/data/journal/fenced-a"; sleep 5
  say "dumping cell A's promoted copy (laptop sprout_a) to $DUMP"
  "${LPG[@]}" pg_dump -U sprout -Fc --no-subscriptions --no-publications -d sprout_a > "$DUMP"
  say "stopping the phone's services; archiving its database; restoring the copy as cell A's database"
  "${SSH[@]}" "sh ~/sprout/ctl.sh stop sprout >/dev/null; pg_ctl -D \$PREFIX/var/lib/postgresql -l ~/sprout/postgres/failback.log -w start >/dev/null"
  "${SSH[@]}" "psql -d postgres -q -v ON_ERROR_STOP=1 -c 'ALTER DATABASE sprout RENAME TO sprout_before_failback_$STAMP' -c 'CREATE DATABASE sprout OWNER sprout'"
  "${SSH[@]}" "cat > ~/sprout-failback.dump" < "$DUMP"
  "${SSH[@]}" "pg_restore -d sprout --no-owner --role=sprout ~/sprout-failback.dump && rm ~/sprout-failback.dump"
  "${SSH[@]}" "psql -d sprout -q -v ON_ERROR_STOP=1" <<'SQL'
DO $$ DECLARE s text; BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO replicator', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO replicator', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE sprout IN SCHEMA %I GRANT SELECT ON TABLES TO replicator', s);
  END LOOP;
END $$;
CREATE PUBLICATION cell_a FOR ALL TABLES;
-- the laptop's replication slot belonged to the archived database: it would keep that database's WAL forever, and its
-- name would collide with the one replicate.sh creates
SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'from_a';
SQL
  "${SSH[@]}" "pg_ctl -D \$PREFIX/var/lib/postgresql -m fast -w stop >/dev/null"
  say "stopping the laptop's standby and dropping its copy of cell A"
  "${COMPOSE[@]}" --profile standby stop standby >/dev/null
  "${LPG[@]}" psql -U sprout -d sprout_a -q -c "ALTER SUBSCRIPTION from_a DISABLE" -c "ALTER SUBSCRIPTION from_a SET (slot_name = NONE)" -c "DROP SUBSCRIPTION from_a" || true
  "${LPG[@]}" psql -U sprout -d sprout -q -c "DROP DATABASE sprout_a"
  rm -f "$LAPTOP/data/journal/fenced-a"
  say "both cells back to normal"
  rm -f "$LAPTOP/data/cells/state.json"; docker restart sprout-laptop-cellwatch-1 >/dev/null
  "${SSH[@]}" "rm -f ~/sprout/cells/state.json ~/sprout/journal/fenced; sh ~/sprout/ctl.sh start sprout >/dev/null"
  say "cell A is starting on the phone (the starter brings it up piece by piece); then: deploy/cells/replicate.sh"
else
  say "pausing cell B's writes on the phone's standby"
  "${SSH[@]}" "touch ~/sprout/journal/fenced-b"; sleep 5
  say "dumping cell B's promoted copy (phone sprout_b) to $DUMP"
  "${SSH[@]}" "pg_dump -Fc --no-subscriptions --no-publications -d sprout_b" > "$DUMP"
  say "stopping the laptop's services; archiving its database; restoring the copy as cell B's database"
  "${COMPOSE[@]}" stop edge trading money street web front cellwatch >/dev/null
  "${LPG[@]}" psql -U sprout -d postgres -q -v ON_ERROR_STOP=1 -c "ALTER DATABASE sprout RENAME TO sprout_before_failback_$STAMP" -c "CREATE DATABASE sprout OWNER sprout"
  "${LPG[@]}" pg_restore -U sprout -d sprout --no-owner < "$DUMP"
  "${LPG[@]}" psql -U sprout -d sprout -q -c "CREATE PUBLICATION cell_b FOR ALL TABLES"     -c "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = 'from_b'"   # the archived database's
  say "stopping the phone's standby and dropping its copy of cell B"
  "${SSH[@]}" "sh ~/sprout/ctl.sh stop sprout-standby >/dev/null; psql -d sprout_b -q -c 'ALTER SUBSCRIPTION from_b DISABLE' -c 'ALTER SUBSCRIPTION from_b SET (slot_name = NONE)' -c 'DROP SUBSCRIPTION from_b'; psql -d postgres -q -c 'DROP DATABASE sprout_b'; rm -f ~/sprout/journal/fenced-b"
  say "both cells back to normal"
  "${SSH[@]}" "rm -f ~/sprout/cells/state.json; pkill -f '[c]ellwatch[.]py' || true"   # the starter starts it again; the bracket keeps pkill off this very shell
  rm -f "$LAPTOP/data/cells/state.json" "$LAPTOP/data/journal/fenced"
  "${COMPOSE[@]}" up -d edge trading money street web front cellwatch >/dev/null
  say "cell B is starting on the laptop; then: deploy/cells/replicate.sh"
fi
