"""Turns a pre-prod run's raw output into the evidence page under docs/reliability/runs/<run>/.

usage: report.py <out dir> <run dir> <run id> <host pom>
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

out, run_dir, run_id, host_pom = sys.argv[1:5]
os.makedirs(run_dir, exist_ok=True)


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


stages = dict(line.strip().split("=", 1) for line in read(os.path.join(out, "stages.txt")).splitlines() if "=" in line)
pom = read(host_pom)
versions = dict(re.findall(r"<(sprout-[a-z-]+)\.version>([^<]+)<", pom))
try:
    platform_sha = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True, text=True,
                                  cwd=os.path.dirname(host_pom)).stdout.strip() or "unknown"
except OSError:
    platform_sha = "unknown"

# ── end-to-end ───────────────────────────────────────────────────────────────
cases = []
for xml_file in sorted(glob.glob(os.path.join(out, "e2e", "TEST-*.xml"))):
    for tc in ET.parse(xml_file).getroot().iter("testcase"):
        failed = tc.find("failure") is not None or tc.find("error") is not None
        name = tc.get("name", "")
        m = re.match(r"(E2E-\d+)\s*(.*)", name)
        cases.append((m.group(1) if m else "", m.group(2) if m else name, float(tc.get("time", 0)), not failed))
cases.sort(key=lambda c: int(c[0].split("-")[1]) if c[0] else 999)

# ── performance ──────────────────────────────────────────────────────────────
perf = {}
summary = read(os.path.join(out, "perf-01-k6-summary.json"))
if summary:
    metrics = json.loads(summary).get("metrics", {})

    def phase(scenario):
        dur = metrics.get(f"http_req_duration{{scenario:{scenario}}}", {}).get("values", {})
        failed = metrics.get(f"http_req_failed{{scenario:{scenario}}}", {}).get("values", {})
        return {"p50": dur.get("med"), "p95": dur.get("p(95)"), "p99": dur.get("p(99)"), "max": dur.get("max"),
                "failRate": failed.get("rate"), "count": (failed.get("passes") or 0) + (failed.get("fails") or 0)}

    perf = {
        "warmup": phase("warmup"), "steady": phase("steady"),
        "thresholds": [(name, rule, t.get("ok", False)) for name, m in metrics.items()
                       for rule, t in m.get("thresholds", {}).items()],
    }

def peak_memory():
    peak = 0.0
    for line in read(os.path.join(out, "memory-during.txt")).splitlines():
        m = re.search(r"([\d.]+)(MiB|GiB)", line)
        if m:
            v = float(m.group(1)) * (1024 if m.group(2) == "GiB" else 1)
            peak = max(peak, v)
    return peak

chaos = json.loads(read(os.path.join(out, "chaos-01.json"), "{}") or "{}")


def probe(result):
    """'503 2.036427' (status, seconds) as '503 in 2,036 ms'."""
    try:
        code, seconds = result.split()
        return f"`{code}` in {float(seconds) * 1000:,.0f} ms"
    except (AttributeError, ValueError):
        return "n/a"


# ── write the page ───────────────────────────────────────────────────────────
mark = lambda ok: "✅ pass" if ok else "❌ fail"
fmt = lambda v, unit="ms": "n/a" if v is None else f"{v:.0f} {unit}"
lines = [
    f"# Pre-prod run {run_id}",
    "",
    "A fresh environment built from the pinned release, tested, then destroyed. "
    "Raw evidence sits next to this page.",
    "",
    "## Release under test",
    "",
    "| Component | Version |",
    "|---|---|",
    *[f"| {k} | `{v}` |" for k, v in sorted(versions.items())],
    f"| sprout-platform | `{platform_sha}` |",
    "",
    "## Result",
    "",
    "| Stage | Result |",
    "|---|---|",
    *[f"| {k} | {mark(v == 'pass')} |" for k, v in stages.items()],
    "",
    "## End-to-end suite",
    "",
    f"{sum(1 for c in cases if c[3])} of {len(cases)} passed.",
    "",
    "| Id | Journey or edge case | Time | Result |",
    "|---|---|---|---|",
    *[f"| {i} | {n} | {t:.1f} s | {mark(ok)} |" for i, n, t, ok in cases],
    "",
    "## PERF-01: sign-in throughput",
    "",
    "First 30 s: ramp from 2 to 20 sign-ins a second on a freshly started JVM. Then 60 s steady at 20 a "
    "second. Every request from a different client.",
    "",
    "| Measure | Warm-up (30 s) | Steady (60 s) |",
    "|---|---|---|",
    *[f"| {label} | {fmt(perf.get('warmup', {}).get(key))} | {fmt(perf.get('steady', {}).get(key))} |"
      for label, key in (("Median", "p50"), ("p95", "p95"), ("p99", "p99"), ("Slowest", "max"))],
    f"| Requests | {perf.get('warmup', {}).get('count', 'n/a')} | {perf.get('steady', {}).get('count', 'n/a')} |",
    f"| Failed | {(perf.get('warmup', {}).get('failRate') or 0) * 100:.2f}% | {(perf.get('steady', {}).get('failRate') or 0) * 100:.2f}% |",
    "",
    f"Edge host peak memory: {f'{peak_memory():.0f} MiB of a 384 MiB limit' if peak_memory() else 'n/a'}.",
    "",
    "| Threshold | Rule | Result |",
    "|---|---|---|",
    *[f"| `{name}` | `{rule}` | {mark(ok)} |" for name, rule, ok in perf.get("thresholds", [])],
    "",
    "## CHAOS-01: the database goes away",
    "",
    "Hypothesis: with Postgres stopped, sign-in answers `503` with `Retry-After` in under 3 s (it never hangs "
    "until the gateway's 5 s timeout), and recovers within 30 s of Postgres returning, without a restart.",
    "",
    "| Moment | Status and time |",
    "|---|---|",
    f"| Before (wrong password, so `401` is healthy) | {probe(chaos.get('before'))} |",
    *[f"| Database down, try {n + 1} | {probe(d)} |" for n, d in enumerate(chaos.get("down", []))],
    f"| `Retry-After` header | {chaos.get('retryAfter', 'n/a')} s |",
    f"| Answering normally again after Postgres started | {chaos.get('recoveredAfterSeconds', 'n/a')} s |",
    f"| Edge host restarts | {chaos.get('edgeRestarts', 'n/a')} |",
    "",
    *(["## Dashboard", "",
        "The edge host's Grafana dashboard for the whole run, captured automatically: the sign-in load, "
        "then the database outage.", "",
        "![Grafana dashboard for this run](grafana-edge.png)", ""]
      if os.path.exists(os.path.join(out, "grafana-edge.png")) else []),
    "## Files",
    "",
    "- `e2e/`: JUnit reports",
    "- `perf-01-k6-summary.json`: every k6 metric",
    "- `memory-during.txt`: edge host memory and CPU every 5 s under load",
    "- `chaos-01.json`: raw chaos timings",
    "- `edge.log`: the edge host's structured logs for the whole run",
]
if os.path.exists(os.path.join(out, "metrics.jsonl")):
    lines.append("- `metrics.jsonl`: counters queried from Prometheus at the end of the run")

with open(os.path.join(run_dir, "index.md"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")

os.makedirs(os.path.join(run_dir, "e2e"), exist_ok=True)
for xml_file in glob.glob(os.path.join(out, "e2e", "TEST-*.xml")):
    shutil.copy(xml_file, os.path.join(run_dir, "e2e"))
for name in ("perf-01-k6-summary.json", "memory-during.txt", "chaos-01.json", "edge.log", "metrics.jsonl",
             "grafana-edge.png"):
    if os.path.exists(os.path.join(out, name)):
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
    release = ", ".join(f"{k.removeprefix('sprout-')} {v}" for k, v in
                        re.findall(r"^\| (sprout-(?!platform)[a-z-]+) \| `([^`]+)` \|$", page, re.M))
    verdict = "✅ passed" if results and all(v == "pass" for v in results.values()) else "❌ failed"
    failed = [k for k, v in results.items() if v != "pass"]
    rows.append(f"| [{name}]({name}/index.md) | {release} | {verdict}{' (' + ', '.join(failed) + ')' if failed else ''} |")

with open(os.path.join(runs_root, "index.md"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join([
        "# Evidence from runs",
        "",
        "Every pre-prod run writes its evidence here: the release it tested, every end-to-end case, the "
        "performance numbers, the chaos timings, and the raw files behind them. These pages are generated "
        "by `preprod/report.py`, not written by hand.",
        "",
        "| Run (UTC) | Release | Result |",
        "|---|---|---|",
        *rows,
    ]) + "\n")
