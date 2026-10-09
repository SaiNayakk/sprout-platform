"""Starts, stops and runs a command in a container through Docker's API socket, with Python's standard library only.

cellwatch.py runs in a container on the laptop; this is how it starts the standby and makes the web server reload its
routes (ADR-027) without a Docker client installed.

    python3 dockerctl.py start CONTAINER
    python3 dockerctl.py stop CONTAINER
    python3 dockerctl.py exec CONTAINER COMMAND [ARGS...]
"""
import http.client
import json
import socket
import sys

SOCKET = '/var/run/docker.sock'


class UnixConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__('localhost', timeout=120)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(120)
        self.sock.connect(SOCKET)


def call(method, path, body=None):
    c = UnixConnection()
    c.request(method, path, body=json.dumps(body) if body is not None else None,
              headers={'Content-Type': 'application/json'} if body is not None else {})
    r = c.getresponse()
    data = r.read()
    if r.status >= 400 and r.status != 304:     # 304: already started / already stopped
        sys.exit(f'{method} {path}: {r.status} {data[:300]!r}')
    return data


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    action, container = sys.argv[1], sys.argv[2]
    if action == 'start':
        call('POST', f'/containers/{container}/start')
    elif action == 'stop':
        call('POST', f'/containers/{container}/stop?t=10')
    elif action == 'exec':
        made = json.loads(call('POST', f'/containers/{container}/exec',
                               {'Cmd': sys.argv[3:], 'AttachStdout': True, 'AttachStderr': True}))
        call('POST', f'/exec/{made["Id"]}/start', {'Detach': False, 'Tty': False})
        result = json.loads(call('GET', f'/exec/{made["Id"]}/json'))
        if result.get('ExitCode'):
            sys.exit(f'{" ".join(sys.argv[3:])} exited {result["ExitCode"]}')
    else:
        sys.exit(f'unknown action {action}')


if __name__ == '__main__':
    main()
