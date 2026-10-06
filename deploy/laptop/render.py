"""Makes the laptop's docker-compose.yml from pre-prod's, so what runs for visitors is wired exactly as every
release was tested, and only what has to differ differs:

  - every throwaway secret ("preprod-only-...") becomes a real one, generated once into data/.env
  - the data lives on volumes, so a restart or a reboot loses nothing
  - nothing is published but the web app (to this machine only; the tunnel reaches it by name)
  - the demo market keeps its place across restarts (its epoch and start date are fixed once)
  - the bank's payment requests wait 5 minutes (pre-prod's 30 seconds is for tests)
  - the web app and the Cloudflare tunnel are added; the load-test and observability tools are not

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
                        'S_PAYROLL_PARTNER_KEY', 'S_PAYROLL_WEBHOOK_SECRET'}

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
    text = must(text, '    mem_limit: 256m\n', '    mem_limit: 256m\n    volumes:\n      - pgdata:/var/lib/postgresql\n')
    text = must(text, '      - ./out/keys:/keys:ro', '      - ./data/keys:/keys:ro')

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

    # come back by themselves, and never fill the disk with logs: each service keeps at most 30 MB of them
    text = text.replace('    mem_limit:', '    restart: unless-stopped\n    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}\n    mem_limit:')

    text += '''
  # The web app, from the release tag it names (SPROUT_WEB_SRC points at a local checkout while developing).
  web:
    build:
      context: ${SPROUT_WEB_SRC:-https://github.com/SaiNayakk/sprout-web.git#v0.1.0}
    environment:
      SPROUT_API: http://edge:8100
    ports:
      - "127.0.0.1:18080:80"
    depends_on:
      edge:
        condition: service_healthy
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}
    mem_limit: 64m

  # The way in from the internet: a Cloudflare tunnel to the web app. Nothing else is reachable.
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

volumes:
  pgdata:
'''
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
