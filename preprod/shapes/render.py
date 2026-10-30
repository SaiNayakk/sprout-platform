"""Renders pre-prod's compose file as the three deployment shapes the shapes experiment compares
(docs/architecture/shapes.md). The services, their versions and their configuration are pre-prod's; only how they
are packed into processes changes.

  four-hosts    pre-prod as it is: edge, trading, money and street, four JVMs (what the phone runs)
  one-jvm       every service in one JVM, the cell host (what a cell's standby runs)
  per-service   every service in its own JVM, nineteen of them

Memory limits are lifted and every JVM gets a heap cap that never binds, because the experiment measures what each
shape uses rather than whether it fits a budget. Each shape is a separate compose project, run one at a time.

    python preprod/shapes/render.py            writes preprod/shapes/out/<shape>.yml
"""
import copy
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent / 'out'

# Which services each host runs, in the order it starts them, and the port each listens on.
HOSTS = {
    'edge': {'identity': 8101, 'gateway': 8100, 'sandbox': 8119},
    'trading': {'marketdata': 8103, 'oms': 8109, 'plans': 8115, 'habits': 8116, 'rewards': 8118},
    'money': {'ledger': 8106, 'accounts': 8104, 'payments': 8105, 'settlement': 8112, 'statements': 8113,
              'recon': 8114, 'goals': 8117},
    'street': {'bank': 8107, 'exchange': 8108, 'depository': 8111, 'clearing': 8110},
}
PORTS = {port: name for services in HOSTS.values() for name, port in services.items()}
PORTS_BY_NAME = {name: port for services in HOSTS.values() for name, port in services.items()}
HOST_OF = {name: host for host, services in HOSTS.items() for name in services}
HEALTH = {'gateway': 8190}   # the gateway answers health on its management port

HEAP = {'four-hosts': '256m', 'one-jvm': '768m', 'per-service': '128m'}
FLAGS = ('-XX:+UseSerialGC -Xms32m -Xmx{heap} -Xss512k -XX:MaxMetaspaceSize=192m -XX:ReservedCodeCacheSize=48m '
         '-XX:TieredStopAtLevel=1')
SERVICE_MAIN = ('exec java $$JAVA_OPTS -Dloader.main=app.sprout.hosts.cell.ServiceHost '
                '-cp /app/host.jar org.springframework.boot.loader.launch.PropertiesLauncher')

ADDRESS = re.compile(r'\b(edge|trading|money|street|127\.0\.0\.1|localhost):(8\d{3})\b')


def readdress(value, own_ports=()):
    """Points every service address at the container that runs the service on that port."""
    def swap(m):
        port = int(m.group(2))
        if port not in PORTS or (port in own_ports and m.group(1) in ('127.0.0.1', 'localhost')):
            return m.group(0)
        return f'{PORTS[port]}:{port}'
    if isinstance(value, str):
        return ADDRESS.sub(swap, value)
    if isinstance(value, list):
        return [readdress(v, own_ports) for v in value]
    if isinstance(value, dict):
        return {k: readdress(v, own_ports) for k, v in value.items()}
    return value


def health(ports):
    probes = ' && '.join(f'wget -qO- http://127.0.0.1:{p}/actuator/health >/dev/null' for p in ports)
    return {'test': ['CMD-SHELL', probes], 'interval': '3s', 'timeout': '3s', 'retries': 100, 'start_period': '20s'}


def jvm(service, host, heap):
    s = copy.deepcopy(service)
    s.pop('mem_limit', None)
    s['build'] = {**s['build'], 'args': {'HOST': host, 'XMX': heap}}
    s['environment'] = {**s['environment'], 'JAVA_OPTS': FLAGS.format(heap=heap)}
    return s


def four_hosts(base):
    c = copy.deepcopy(base)
    for host in HOSTS:
        c['services'][host] = jvm(c['services'][host], host, HEAP['four-hosts'])
    return c


def one_jvm(base):
    c = copy.deepcopy(base)
    env, volumes, ports, depends = {}, [], [], {}
    for host in HOSTS:
        s = c['services'].pop(host)
        env.update(s['environment'])
        volumes += s.get('volumes', [])
        ports += s.get('ports', [])
        depends.update(s.get('depends_on', {}))
    cell = jvm({'build': base['services']['edge']['build'], 'environment': env}, 'cell', HEAP['one-jvm'])
    cell.update({
        'volumes': volumes, 'ports': ports, 'depends_on': depends,
        # the other containers still call edge, trading, money and street: all four names reach this one
        'networks': {'default': {'aliases': list(HOSTS)}},
        'healthcheck': health(sorted(HEALTH.get(n, p) for h in HOSTS.values() for n, p in h.items())),
    })
    c['services']['cell'] = cell
    return c


def per_service(base):
    c = copy.deepcopy(base)
    started = []
    for host, services in HOSTS.items():
        s = c['services'].pop(host)
        for name, port in services.items():
            one = jvm(s, 'cell', HEAP['per-service'])
            one['environment'] = readdress({**one['environment'], 'SPROUT_SERVICE': name}, own_ports={port})
            one['entrypoint'] = ['sh', '-c', SERVICE_MAIN]
            one['healthcheck'] = health([HEALTH.get(name, port)])
            one['ports'] = [p for p in s.get('ports', []) if p.split(':')[-1] == str(port)]
            if name != 'identity':
                one.pop('volumes', None)   # only identity reads the signing key
            one['depends_on'] = dict(s.get('depends_on', {}))
            c['services'][name] = one
            started.append(name)
    # The gateway starts last, as in the hosts, and the sandbox after it: they call everything else at start.
    for name in ('gateway', 'sandbox'):
        before = [n for n in started if n not in ('gateway', 'sandbox')] + (['gateway'] if name == 'sandbox' else [])
        c['services'][name]['depends_on'].update({n: {'condition': 'service_healthy'} for n in before})
    for name in ('k6', 'loadgen'):
        c['services'][name] = readdress(c['services'][name])
    return c


def main():
    base = yaml.safe_load((ROOT / 'preprod' / 'docker-compose.yml').read_text(encoding='utf-8'))
    # build contexts are relative to preprod/; the rendered files live one level down
    for s in base['services'].values():
        if 'build' in s:
            s['build']['context'] = '../../..'
            s['build']['dockerfile'] = 'preprod/Dockerfile.host'
        s['volumes'] = ['../../' + v if isinstance(v, str) and v.startswith('.') else v for v in s.get('volumes', [])]
        if not s['volumes']:
            s.pop('volumes')
    OUT.mkdir(exist_ok=True)
    for shape, render in (('four-hosts', four_hosts), ('one-jvm', one_jvm), ('per-service', per_service)):
        c = render(base)
        c['name'] = f'sprout-shape-{shape}'
        (OUT / f'{shape}.yml').write_text(
            f'# Rendered by preprod/shapes/render.py from preprod/docker-compose.yml; do not edit.\n'
            + yaml.safe_dump(c, sort_keys=False, width=200), encoding='utf-8')
        jvms = [n for n, s in c['services'].items() if 'JAVA_OPTS' in (s.get('environment') or {})]
        print(f'{shape}: {len(jvms)} JVMs ({", ".join(jvms)})')


if __name__ == '__main__':
    main()
