"""Rehearses a deploy's database migrations on a copy of the phone's data, before the phone runs them.

Pre-prod starts from an empty database, so a migration that only fails on real rows passes there. On
2026-10-08 two did: a rename the ledger's immutable journal refused, and one a foreign key refused. Each
took Sprout down on the phone until it was rolled back. This finds those first.

    python deploy/phone/rehearse.py phone.dump hosts/*/target/*-host.jar

It restores the dump into a throwaway Postgres 18 container, reads every service's migrations out of the host
jars, and for each schema applies the ones its flyway_schema_history doesn't have yet, in version order, each
in one transaction, as Flyway would. It prints what it applied and stops at the first failure.
Needs Docker. Take the dump with:  ssh phone 'pg_dump -Fc -d sprout' > phone.dump
"""
import io
import os
import re
import subprocess
import sys
import time
import zipfile

CONTAINER = 'sprout-rehearse'


def sh(args, stdin=None, check=True):
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    r = subprocess.run(args, input=stdin, capture_output=True, text=True, encoding='utf-8', env=env)
    if check and r.returncode != 0:
        sys.exit(f'{" ".join(args[:4])}... failed:\n{r.stdout}{r.stderr}')
    return r


def psql(sql, single_transaction=False):
    args = ['docker', 'exec', '-i', CONTAINER, 'psql', '-U', 'sprout', '-d', 'sprout', '-At', '-v', 'ON_ERROR_STOP=1', '-q']
    if single_transaction:
        args.append('-1')
    return sh(args, stdin=sql, check=False)


def migrations(jars):
    """schema -> [(version, name, sql)], read from the services' jars inside each host jar."""
    found = {}
    for jar in jars:
        with zipfile.ZipFile(jar) as host:
            for lib in host.namelist():
                if not re.match(r'BOOT-INF/lib/sprout-[a-z]+-[\d.]+\.jar$', lib):
                    continue
                with zipfile.ZipFile(io.BytesIO(host.read(lib))) as svc:
                    for name in svc.namelist():
                        m = re.match(r'db/([a-z]+)/V(\d+)__(.+)\.sql$', name)
                        if m:
                            found.setdefault(m.group(1), {})[int(m.group(2))] = (m.group(3), svc.read(name).decode('utf-8'))
    return {schema: sorted((v, n, s) for v, (n, s) in by_version.items()) for schema, by_version in found.items()}


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    dump, jars = sys.argv[1], sys.argv[2:]
    sh(['docker', 'rm', '-f', CONTAINER], check=False)
    sh(['docker', 'run', '-d', '--name', CONTAINER, '-e', 'POSTGRES_USER=sprout', '-e', 'POSTGRES_PASSWORD=rehearsal',
        '-e', 'POSTGRES_DB=sprout', 'postgres:18-alpine'])
    try:
        for _ in range(60):
            if sh(['docker', 'exec', CONTAINER, 'pg_isready', '-q', '-U', 'sprout'], check=False).returncode == 0:
                break
            time.sleep(1)
        sh(['docker', 'cp', dump, f'{CONTAINER}:/tmp/phone.dump'])
        sh(['docker', 'exec', CONTAINER, 'pg_restore', '-U', 'sprout', '-d', 'sprout', '--no-owner', '/tmp/phone.dump'])
        failed = False
        for schema, items in sorted(migrations(jars).items()):
            r = psql(f'SELECT version FROM {schema}.flyway_schema_history WHERE success')
            applied = {int(v) for v in r.stdout.split() if v.isdigit()} if r.returncode == 0 else set()
            for version, name, sql in items:
                if version in applied:
                    continue
                r = psql(f'SET search_path TO {schema};\n{sql}', single_transaction=True)
                if r.returncode != 0:
                    print(f'FAIL  {schema} V{version} {name}\n{r.stderr.strip()}')
                    failed = True
                    break
                print(f'ok    {schema} V{version} {name}')
            if failed:
                break
        print('Every pending migration applies to a copy of production.' if not failed else 'Don\'t deploy: fix the failing migration first.')
        sys.exit(1 if failed else 0)
    finally:
        sh(['docker', 'rm', '-f', CONTAINER], check=False)


if __name__ == '__main__':
    main()
