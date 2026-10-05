"""Turns a pre-prod run's raw output into the evidence page under docs/reliability/runs/<run>/.

usage: report.py <out dir> <run dir> <run id> <hosts dir>
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

out, run_dir, run_id, hosts_dir = sys.argv[1:5]
os.makedirs(run_dir, exist_ok=True)


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def load(path):
    text = read(path)
    return json.loads(text) if text.strip() else None


mark = lambda ok: "✅ pass" if ok else "❌ fail"
ms = lambda v: "n/a" if v is None else f"{v:,.0f} ms"

stages = dict(line.strip().split("=", 1) for line in read(os.path.join(out, "stages.txt")).splitlines() if "=" in line)

# ── what was tested: every host's manifest ───────────────────────────────────
releases = []
for pom in sorted(glob.glob(os.path.join(hosts_dir, "*", "pom.xml"))):
    host = os.path.basename(os.path.dirname(pom))
    for svc, version in re.findall(r"<(sprout-[a-z-]+)\.version>([^<]+)<", read(pom)):
        releases.append((host, svc, version))
try:
    platform = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True, text=True,
                              cwd=hosts_dir).stdout.strip() or "unknown"
except OSError:
    platform = "unknown"

# ── end-to-end ───────────────────────────────────────────────────────────────
cases = []
for xml_file in sorted(glob.glob(os.path.join(out, "e2e", "TEST-*.xml"))):
    for tc in ET.parse(xml_file).getroot().iter("testcase"):
        failed = tc.find("failure") is not None or tc.find("error") is not None
        m = re.match(r"(E2E-\d+)\s*(.*)", tc.get("name", ""))
        if m:
            cases.append((m.group(1), m.group(2), float(tc.get("time", 0)), not failed))
cases.sort(key=lambda c: int(c[0].split("-")[1]))

# ── performance ──────────────────────────────────────────────────────────────
k6 = (load(os.path.join(out, "perf-01-k6-summary.json")) or {}).get("metrics", {})


def phase(scenario):
    dur = k6.get(f"http_req_duration{{scenario:{scenario}}}", {}).get("values", {})
    failed = k6.get(f"http_req_failed{{scenario:{scenario}}}", {}).get("values", {})
    return {"p50": dur.get("med"), "p95": dur.get("p(95)"), "p99": dur.get("p(99)"), "max": dur.get("max"),
            "failRate": failed.get("rate"), "count": (failed.get("passes") or 0) + (failed.get("fails") or 0)}


warm, steady = phase("warmup"), phase("steady")
thresholds = [(name, rule, t.get("ok", False)) for name, m in k6.items() for rule, t in m.get("thresholds", {}).items()]
fanout = load(os.path.join(out, "perf-03-summary.json"))
orders = load(os.path.join(out, "perf-04-summary.json"))
cold_k6 = (load(os.path.join(out, "perf-02-k6-summary.json")) or {}).get("metrics", {})
cold_dur = cold_k6.get("http_req_duration{scenario:cold}", {}).get("values", {})
cold_failed = cold_k6.get("http_req_failed{scenario:cold}", {}).get("values", {})
cold_thresholds = [(n, r, t.get("ok", False)) for n, m in cold_k6.items() for r, t in m.get("thresholds", {}).items()]


def peak_memory(host):
    peak = 0.0
    for line in read(os.path.join(out, "memory-during.txt")).splitlines():
        if host in line:
            m = re.search(r"([\d.]+)(MiB|GiB)", line)
            if m:
                peak = max(peak, float(m.group(1)) * (1024 if m.group(2) == "GiB" else 1))
    return peak


chaos = [load(p) for p in sorted(glob.glob(os.path.join(out, "trace-*.json"))) + sorted(glob.glob(os.path.join(out, "chaos-*.json")) + glob.glob(os.path.join(out, "settle-*.json"))
                                  + glob.glob(os.path.join(out, "recon-*.json")))]
chaos = [c for c in chaos if c]

# ── the page ─────────────────────────────────────────────────────────────────
L = [f"# Pre-prod run {run_id}", "",
     "A fresh environment built from the pinned releases, tested, then destroyed. Raw evidence sits next to this page.", "",
     "## Release under test", "", "| Host | Service | Version |", "|---|---|---|",
     *[f"| {h} | {s} | `{v}` |" for h, s, v in releases],
     f"| | sprout-platform | `{platform}` |", "",
     "## Result", "", "| Stage | Result |", "|---|---|",
     *[f"| {k} | {mark(v == 'pass')} |" for k, v in stages.items()], "",
     "## End-to-end suite", "", f"{sum(1 for c in cases if c[3])} of {len(cases)} passed.", "",
     "| Id | Journey or edge case | Time | Result |", "|---|---|---|---|",
     *[f"| [{i}](../../../testing/e2e.md#{i.lower()}) | {n} | {t:.1f} s | {mark(ok)} |" for i, n, t, ok in cases], ""]

L += ["## PERF-01: sign-in throughput", "",
      "First 30 s: ramp from 2 to 10 sign-ins a second. Then 60 s steady at 10 a second (half the edge host's capacity). "
      "Every request from a different client.", "",
      "| Measure | Warm-up (30 s) | Steady (60 s) |", "|---|---|---|",
      *[f"| {label} | {ms(warm.get(k))} | {ms(steady.get(k))} |"
        for label, k in (("Median", "p50"), ("p95", "p95"), ("p99", "p99"), ("Slowest", "max"))],
      f"| Requests | {warm['count']} | {steady['count']} |",
      f"| Failed | {(warm['failRate'] or 0) * 100:.2f}% | {(steady['failRate'] or 0) * 100:.2f}% |", "",
      "| Threshold | Rule | Result |", "|---|---|---|",
      *[f"| `{n}` | `{r}` | {mark(ok)} |" for n, r, ok in thresholds], ""]

if cold_dur:
    L += ["## PERF-02: sign-in straight after a restart", "",
          "The edge host is restarted (it warms itself up before reporting ready), then gets 10 sign-ins a "
          "second for 30 s from the moment it is ready.", "",
          "| Measure | Value |", "|---|---|",
          f"| Median / p95 / p99 / slowest | {ms(cold_dur.get('med'))} / {ms(cold_dur.get('p(95)'))} / "
          f"{ms(cold_dur.get('p(99)'))} / {ms(cold_dur.get('max'))} |",
          f"| Failed | {(cold_failed.get('rate') or 0) * 100:.2f}% |", "",
          "| Threshold | Rule | Result |", "|---|---|---|",
          *[f"| `{n}` | `{r}` | {mark(ok)} |" for n, r, ok in cold_thresholds], ""]

if fanout:
    L += ["## PERF-03: price fan-out", "",
          f"{fanout['clients']} clients, each streaming {fanout['symbolsPerClient']} symbols through the gateway for "
          f"{fanout['seconds']} s. Latency is from the moment market data produced a tick to the moment a client "
          "read it, measured on one clock.", "",
          "| Measure | Value |", "|---|---|",
          f"| Streams opened | {fanout['opened']} of {fanout['clients']} |",
          f"| Streams that ended early | {fanout['endedEarly']} |",
          f"| Ticks delivered | {fanout['ticksReceived']:,} ({fanout['ticksPerSecond']:,.0f} a second) |",
          f"| Delivery latency p50 / p95 / p99 / max | {ms(fanout['p50Ms'])} / {ms(fanout['p95Ms'])} / {ms(fanout['p99Ms'])} / {ms(fanout['maxMs'])} |",
          f"| Conflated (a client got only the newest price) | {fanout['seqGaps']:,} times, "
          f"{fanout['seqGaps'] / max(1, fanout['ticksReceived']) * 100:.1f}% of ticks |", "",
          "Pass when every stream opens and stays open, p95 is under 250 ms and p99 under 1 s.", ""]

if orders:
    L += ["## PERF-04: orders under load", "",
          f"{orders['customers']} funded customers place market buys through the gateway at a steady {orders['ordersPerSecond']} "
          f"orders a second for {orders['seconds']} s, each through the risk checks, the ledger and the exchange. Afterwards "
          "every customer's holdings are compared with what their filled orders bought.", "",
          "| Measure | Value |", "|---|---|",
          f"| Orders filled | {orders['filled']} of {orders['orders']} |",
          f"| Placement latency p50 / p95 / p99 / max | {ms(orders['p50Ms'])} / {ms(orders['p95Ms'])} / {ms(orders['p99Ms'])} / {ms(orders['maxMs'])} |",
          f"| Server errors / failed calls | {orders['serverErrors']} / {orders['clientErrors']} |",
          f"| Holdings that don't match what was bought | {orders['holdingsMismatched']} |", "",
          "Pass when every order fills, nothing fails server-side, holdings match exactly, p95 is under 1 s and p99 under 2 s.", ""]

L += ["## Memory under load", "", "| Host | Peak | Limit |", "|---|---|---|"]
for host, limit in (("edge", 384), ("trading", 320), ("money", 320), ("street", 320)):
    peak = peak_memory(host)
    L.append(f"| {host} | {f'{peak:.0f} MiB' if peak else 'n/a'} | {limit} MiB |")
L.append("")

for c in chaos:
    L += [f"## {c['id']}: {c['title']}", "",
          f"Hypothesis: {c['hypothesis']}", "", "| Observed | |", "|---|---|",
          *[f"| {o['what']} | {o['value']} |" for o in c["observations"]], "",
          "| Check | Result |", "|---|---|", *[f"| {k['what']} | {mark(k['pass'])} |" for k in c["checks"]], ""]

if os.path.exists(os.path.join(out, "grafana-edge.png")):
    L += ["## Dashboard", "", "The Grafana dashboard for the whole run, captured automatically.", "",
          "![Grafana dashboard for this run](grafana-edge.png)", ""]

L += ["## Files", "", "- `e2e/`: JUnit reports", "- `perf-01-k6-summary.json`: every k6 metric",
      "- `perf-02-k6-summary.json`: sign-in straight after a restart",
      "- `perf-03-summary.json`: the fan-out result", "- `perf-04-summary.json`: the order load result", "- `memory-during.txt`: host memory and CPU every 5 s under load",
      "- `trace-*.json`, `chaos-*.json`, `settle-*.json`, `recon-*.json`: each experiment's observations and checks",
      "- `edge.log`, `trading.log`, `money.log`, `street.log`: the hosts' structured logs for the whole run"]
if os.path.exists(os.path.join(out, "metrics.jsonl")):
    L.append("- `metrics.jsonl`: counters queried from Prometheus at the end of the run")

with open(os.path.join(run_dir, "index.md"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(L) + "\n")

os.makedirs(os.path.join(run_dir, "e2e"), exist_ok=True)
for xml_file in glob.glob(os.path.join(out, "e2e", "TEST-*.xml")):
    shutil.copy(xml_file, os.path.join(run_dir, "e2e"))
for name in os.listdir(out):
    if name.endswith((".json", ".jsonl", ".log", ".png")) or name == "memory-during.txt":
        shutil.copy(os.path.join(out, name), run_dir)
print(f"wrote {os.path.join(run_dir, 'index.md')}")

# ── the list of all runs, newest first ───────────────────────────────────────
runs_root = os.path.dirname(os.path.abspath(run_dir))
rows = []
for name in sorted(os.listdir(runs_root), reverse=True):
    page = read(os.path.join(runs_root, name, "index.md"))
    if not page:
        continue
    results = dict(re.findall(r"^\| ([a-z0-9-]+) \| (?:✅|❌) (pass|fail) \|$", page, re.M))
    release = ", ".join(f"{s.removeprefix('sprout-')} {v}" for s, v in
                        re.findall(r"^\| (?:[a-z]+ )?\| (sprout-(?!platform)[a-z-]+) \| `([^`]+)` \|$", page, re.M))
    if not release:  # pages from before hosts were listed
        release = ", ".join(f"{s.removeprefix('sprout-')} {v}" for s, v in
                            re.findall(r"^\| (sprout-(?!platform)[a-z-]+) \| `([^`]+)` \|$", page, re.M))
    failed = [k for k, v in results.items() if v != "pass"]
    verdict = "✅ passed" if results and not failed else "❌ failed"
    rows.append(f"| [{name}]({name}/index.md) | {release} | {verdict}{' (' + ', '.join(failed) + ')' if failed else ''} |")

with open(os.path.join(runs_root, "index.md"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join([
        "# Evidence from runs", "",
        "Every pre-prod run writes its evidence here: the release it tested, every end-to-end case, the "
        "performance numbers, the chaos experiments, and the raw files behind them. These pages are generated "
        "by `preprod/report.py`, not written by hand.", "",
        "| Run (UTC) | Release | Result |", "|---|---|---|", *rows]) + "\n")
