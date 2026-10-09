"""Makes the laptop's docker-compose.yml from pre-prod's, so what runs for visitors is wired exactly as every
release was tested, and only what has to differ differs:

  - every throwaway secret ("preprod-only-...") becomes a real one, generated once into data/.env
  - the data lives on volumes, so a restart or a reboot loses nothing
  - nothing is published but the web app (to this machine only; the tunnel reaches it by name)
  - the demo market keeps its place across restarts (its epoch and start date are fixed once)
  - the bank's payment requests wait 5 minutes (pre-prod's 30 seconds is for tests)
  - the web app and the Cloudflare tunnel are added; the load-test and observability tools are not
  - it runs as cell B (ADR-027): logical replication on, the gateway journals into cell A, the web server routes
    each cell's customers, and cellwatch, the replication client, the shared front door and a standby for cell A are
    added

    python render.py            writes docker-compose.yml (and any missing secrets) next to this file
"""
import base64
import datetime
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = HERE / 'data'
SOURCE = ROOT / 'preprod' / 'docker-compose.yml'
TOTP_DEV_KEY = 'cHJlcHJvZC1vbmx5LTMyLWJ5dGUtdGVzdC1rZXkhISE='


def must(text: str, old: str, new: str, count: int = 1) -> str:
    if text.count(old) < 1:
        sys.exit(f'pre-prod\'s compose file has changed shape: expected to find {old!r}')
    return text.replace(old, new, count)


def secret_name(value: str) -> str:
    """preprod-only-member-key -> S_MEMBER_KEY"""
    return 'S_' + value.removeprefix('preprod-only-').upper().replace('-', '_')


def build() -> tuple[str, set[str]]:
    text = SOURCE.read_text(encoding='utf-8')
    text = text[:text.index('\n  lgtm:')]   # the tools after the hosts are for pre-prod only
    needed: set[str] = {'SPROUT_DB_PASSWORD', 'IDENTITY_TOTP_KEY', 'MARKETDATA_START_DATE', 'MARKETDATA_EPOCH', 'SPROUT_HOSTNAME',
                        'S_PAYROLL_PARTNER_KEY', 'S_PAYROLL_WEBHOOK_SECRET',
                        # the cells' shared settings: copied in by up.sh from the cells' own secrets, never generated here
                        'CELL_KEY', 'CELL_A_REPLICATOR_PASSWORD', 'CELL_B_REPLICATOR_PASSWORD', 'CELL_WEIGHTS'}

    text = must(text, 'name: sprout-preprod', 'name: sprout-laptop')
    text = must(text, 'context: ..', 'context: ../..', text.count('context: ..'))

    # secrets
    text = text.replace('preprod-only-not-a-secret', '${SPROUT_DB_PASSWORD}')
    text = text.replace(TOTP_DEV_KEY, '${IDENTITY_TOTP_KEY}')

    def swap(m: re.Match) -> str:
        name = secret_name(m.group(0))
        needed.add(name)
        return '${' + name + '}'
    text = re.sub(r'preprod-only-[a-z-]+', swap, text)
    if 'preprod-only' in text:
        sys.exit('a throwaway secret is left in the laptop compose file')

    # data survives restarts
    # 512 MB, not pre-prod's 256: as a cell this Postgres also holds the copy of cell A's database (ADR-027)
    text = must(text, '    mem_limit: 256m\n', '    mem_limit: 512m\n    volumes:\n      - pgdata:/var/lib/postgresql\n')
    # cell B (ADR-027): its database is replicated into cell A's Postgres, and cell A's into a second database here
    text = must(text, '      - pgdata:/var/lib/postgresql\n',
                '      - pgdata:/var/lib/postgresql\n'
                '    command: ["postgres", "-c", "wal_level=logical", "-c", "max_replication_slots=10", "-c", "max_wal_senders=10", "-c", "max_connections=300"]\n')
    # the gateway journals customers' writes into cell A before forwarding them, and keeps cell A's journal here
    text = must(text, '      GATEWAY_TRUST_CF_IP: "true"\n',
                '      GATEWAY_TRUST_CF_IP: "true"\n      GATEWAY_CELL_ID: b\n'
                '      GATEWAY_CELL_PEER_URL: https://sprout-a-saiworks.nncs.in\n      GATEWAY_CELL_KEY: ${CELL_KEY}\n'
                '      GATEWAY_CELL_JOURNAL_DIR: /journal\n      GATEWAY_CELL_FENCE_FILE: /journal/fenced\n')
    text = must(text, '      - ./out/keys:/keys:ro', '      - ./data/keys:/keys:ro\n      - ./data/journal:/journal')

    # only the web app is reachable, and only from this machine; the gateway is for the web app (on the compose network)
    text = must(text, '      - "8100:8100"', '      - "127.0.0.1:8100:8100"')
    must(text, 'GATEWAY_TRUST_CF_IP: "true"', '')   # already so in pre-prod (behind Cloudflare the real visitor is CF-Connecting-IP): fail if that changes

    # real timings
    text = must(text, '      BANK_COLLECT_TTL: 30s             # short, so E2E can watch a request expire\n', '')
    text = re.sub(r'(PLANS_EVERY|GOALS_EVERY): 2s', r'\1: 10s', text)
    text = re.sub(r'SANDBOX_EVERY: 2s', 'SANDBOX_EVERY: 5s', text)

    # the demo market keeps its place across restarts
    text = must(text, '      MARKETDATA_SPEED: ${MARKETDATA_SPEED:-30}',
                '      MARKETDATA_SPEED: ${MARKETDATA_SPEED:-30}\n      MARKETDATA_START_DATE: ${MARKETDATA_START_DATE}\n      MARKETDATA_EPOCH: ${MARKETDATA_EPOCH}')

    # the fictional payroll must not run on the repository's well-known dev keys
    text = must(text, '      BANK_PAYROLL_FLOAT:', '      BANK_PAYROLL_PARTNER_KEY: ${S_PAYROLL_PARTNER_KEY}\n      BANK_PAYROLL_WEBHOOK_SECRET: ${S_PAYROLL_WEBHOOK_SECRET}\n      BANK_PAYROLL_FLOAT:')
    text = must(text, '      SANDBOX_EVERY:', '      BANK_PAYROLL_PARTNER_KEY: ${S_PAYROLL_PARTNER_KEY}\n      SANDBOX_EVERY:')

    # The laptop's hosts get the laptop's JVM (capacity E4, 2026-10-09): full JIT (C2) and a parallel collector instead
    # of the phone's C1-only, serial one. Same heaps; about 40 MB more each for the compiled code. It cut the CPU a
    # request costs by a fifth to a third, and still leaves room for cell A's standby beside them
    text = must(text, '        XMX: 160m\n    environment:\n',
                '        XMX: 160m\n    environment:\n      JAVA_OPTS: "-XX:+UseParallelGC -XX:ParallelGCThreads=2 -Xms96m '
                '-Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m -XX:ReservedCodeCacheSize=96m"\n', count=4)
    text = must(text, "    mem_limit: 384m                     # the phone's budget for this host",
                '    mem_limit: 448m')
    text = must(text, "    mem_limit: 320m                     # the phone's budget for this host",
                '    mem_limit: 384m', count=2)
    text = must(text, '    mem_limit: 320m\n', '    mem_limit: 384m\n')

    # come back by themselves, and never fill the disk with logs: each service keeps at most 30 MB of them
    text = text.replace('    mem_limit:', '    restart: unless-stopped\n    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}\n    mem_limit:')

    text += '''
  # The web app: up.sh builds the release in web.version (or a local checkout, while developing) and names it here;
  # without that, compose falls back to the release's own name, so `docker compose down`/`logs` work on their own.
  web:
    image: ${SPROUT_WEB_IMAGE:-sprout-web:%s}
    environment:
      SPROUT_API: http://edge:8100
      # cell B (ADR-027): the cell-aware configuration replaces the image's own
      SPROUT_CELL: b
      SPROUT_PEER: a
      SPROUT_PEER_HOST: sprout-a-saiworks.nncs.in
      SPROUT_STANDBY_API: http://standby:8100
      CELL_KEY: ${CELL_KEY}
    volumes:
      - ../cells/web-cell.conf.template:/etc/nginx/templates/default.conf.template:ro
      - ./data/cells:/etc/nginx/cells:ro
    ports:
      - "127.0.0.1:18080:80"
    depends_on:
      edge:
        condition: service_healthy
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}
    mem_limit: 64m

  # This cell's own address (sprout-b-..., where cell A forwards this cell's customers) and its database's address for
  # cell A's replication client (pg-b-..., a Postgres login needing the replicator's password). Nothing else is reachable.
  cloudflared:
    image: cloudflare/cloudflared:2025.8.1
    command: ["tunnel", "--no-autoupdate", "--config", "/etc/cloudflared/config.yml", "run"]
    volumes:
      - ./data/cloudflared:/etc/cloudflared:ro
    depends_on:
      - web
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}
    mem_limit: 128m

  # The front door both cells share (sprout-saiworks...): a connector here and one in cell A, so a visitor reaches
  # whichever cell is up (ADR-027)
  front:
    image: cloudflare/cloudflared:2025.8.1
    command: ["tunnel", "--no-autoupdate", "--config", "/etc/cloudflared/config.yml", "run"]
    volumes:
      - ./data/cloudflared-front:/etc/cloudflared:ro
    depends_on:
      - web
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}
    mem_limit: 128m

  # Cell A's database, reached through Cloudflare, for the subscription that copies it here
  pgpeer:
    image: cloudflare/cloudflared:2025.8.1
    command: ["access", "tcp", "--hostname", "pg-a-saiworks.nncs.in", "--url", "0.0.0.0:5432"]
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}
    mem_limit: 128m

  # Watches both cells; fences this one, or takes cell A over (deploy/cells/cellwatch.py)
  cellwatch:
    image: postgres:18-alpine
    entrypoint: ["sh", "-c", "apk add --no-cache python3 >/dev/null && exec python3 /cells/cellwatch.py"]
    environment:
      CELL: b
      PEER: a
      SELF_URL: https://sprout-b-saiworks.nncs.in
      PEER_URL: https://sprout-a-saiworks.nncs.in
      LOCAL_CHECK: http://edge:8100/api/marketdata/v1/market
      STATUS_FILE: /state/status.json
      ROUTES_FILE: /state/routes.conf
      CELLS_FILE: /state/cells.json
      STATE_FILE: /state/state.json
      LOG_FILE: /state/cellwatch.log
      FENCE_FILE: /journal/fenced
      JOURNAL_DIR: /journal
      WEIGHTS: ${CELL_WEIGHTS}
      CELL_KEY: ${CELL_KEY}
      PGPASSWORD: ${SPROUT_DB_PASSWORD}
      REPLICA_PSQL: psql -h postgres -U sprout -d sprout_a -v ON_ERROR_STOP=1 -q
      STANDBY_START: python3 /cells/dockerctl.py start sprout-laptop-standby-1
      STANDBY_STOP: python3 /cells/dockerctl.py stop sprout-laptop-standby-1
      STANDBY_GATEWAY: http://standby:8100
      STANDBY_CHECK: http://standby:8100/api/marketdata/v1/market
      RELOAD_ROUTES: python3 /cells/dockerctl.py exec sprout-laptop-web-1 nginx -s reload
    volumes:
      - ../cells:/cells:ro
      - ./data/cells:/state
      - ./data/journal:/journal
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on:
      - web
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}
    mem_limit: 96m

  # Cell A's services on this cell's copy of cell A's database, with cell A's own keys (data/cell-a, from the phone):
  # created by up.sh, started by cellwatch only when cell A is lost
  standby:
    profiles: ["standby"]
    build:
      context: ../..
      dockerfile: preprod/Dockerfile.host
      args:
        HOST: cell
        XMX: 220m
    env_file:
      - path: ./data/cell-a/cell-a.env      # written by deploy/cells/exchange-secrets.sh
        required: false
    environment:
      SPROUT_SANDBOX: "true"
      GATEWAY_CELL_ID: a
      GATEWAY_CELL_KEY: ${CELL_KEY}
      GATEWAY_CELL_JOURNAL_DIR: /tmp/journal
      GATEWAY_CELL_FENCE_FILE: /journal/fenced-a     # failback pauses cell A's writes here while moving them home
      GATEWAY_TRUST_CF_IP: "true"
      GATEWAY_BIND: 0.0.0.0
      IDENTITY_SIGNING_KEY_PATH: /keys/signing.pem
      IDENTITY_DEMO_ENABLED: "true"
      SANDBOX_EVERY: 5s
      MARKETDATA_CLOCK: ACCELERATED
      MARKETDATA_SPEED: ${MARKETDATA_SPEED:-30}
      LOG_FORMAT: ecs
      IDENTITY_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=identity
      IDENTITY_DB_USER: sprout
      IDENTITY_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      SANDBOX_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=sandbox
      SANDBOX_DB_USER: sprout
      SANDBOX_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      OMS_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=oms
      OMS_DB_USER: sprout
      OMS_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      PLANS_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=plans
      PLANS_DB_USER: sprout
      PLANS_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      HABITS_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=habits
      HABITS_DB_USER: sprout
      HABITS_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      REWARDS_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=rewards
      REWARDS_DB_USER: sprout
      REWARDS_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      LEDGER_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=ledger
      LEDGER_DB_USER: sprout
      LEDGER_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      ACCOUNTS_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=accounts
      ACCOUNTS_DB_USER: sprout
      ACCOUNTS_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      PAYMENTS_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=payments
      PAYMENTS_DB_USER: sprout
      PAYMENTS_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      SETTLEMENT_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=settlement
      SETTLEMENT_DB_USER: sprout
      SETTLEMENT_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      RECON_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=recon
      RECON_DB_USER: sprout
      RECON_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      GOALS_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=goals
      GOALS_DB_USER: sprout
      GOALS_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      BANK_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=bank
      BANK_DB_USER: sprout
      BANK_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      EXCHANGE_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=exchange
      EXCHANGE_DB_USER: sprout
      EXCHANGE_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      DEPOSITORY_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=depository
      DEPOSITORY_DB_USER: sprout
      DEPOSITORY_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
      CLEARING_DB_URL: jdbc:postgresql://postgres:5432/sprout_a?currentSchema=clearing
      CLEARING_DB_USER: sprout
      CLEARING_DB_PASSWORD: ${SPROUT_DB_PASSWORD}
    volumes:
      - ./data/cell-a/keys:/keys:ro
      - ./data/journal:/journal
    mem_limit: 700m
    restart: "no"
    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}

volumes:
  pgdata:
''' % (HERE / 'web.version').read_text().strip()
    return text, needed


def ensure_env(needed: set[str]) -> list[str]:
    """Adds whichever secrets and settings aren't in data/.env yet, never changing one that is. Returns the names added."""
    DATA.mkdir(exist_ok=True)
    env = DATA / '.env'
    have: dict[str, str] = {}
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                have[k] = v
    added = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for name in sorted(needed - set(have)):
        if name == 'IDENTITY_TOTP_KEY':
            value = base64.b64encode(secrets.token_bytes(32)).decode()
        elif name == 'MARKETDATA_START_DATE':
            value = now.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).date().isoformat()
        elif name == 'MARKETDATA_EPOCH':
            value = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        elif name == 'SPROUT_HOSTNAME':
            value = 'sprout-saiworks.nncs.in'
        else:
            value = secrets.token_hex(24)
        have[name] = value
        added.append(name)
    if added:
        with env.open('a', encoding='utf-8', newline='\n') as f:
            if env.stat().st_size == 0:
                f.write('# Generated by deploy/laptop/render.py. Real secrets: never commit, never paste anywhere.\n')
            for name in added:
                f.write(f'{name}={have[name]}\n')
    return added


if __name__ == '__main__':
    compose, needed = build()
    added = ensure_env(needed)
    (HERE / 'docker-compose.yml').write_text(compose, encoding='utf-8', newline='\n')
    print(f'wrote docker-compose.yml; {len(needed)} settings, {len(added)} newly generated: {", ".join(a for a in added if not a.startswith("S_") and a != "SPROUT_DB_PASSWORD") or "secrets only"}')
