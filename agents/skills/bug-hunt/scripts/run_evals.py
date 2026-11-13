#!/usr/bin/env python3
"""Eval harness for the bug-hunt skill.

Subcommands:
  list                 show the cases under .review/evals/cases/
  mine                 propose cases from git history (fix/revert commits
                       blamed back to the change that introduced the bug,
                       plus clean controls)
  run                  run the headless review command on each case, repeat,
                       score, and write a report; --gate compares with a
                       baseline report and fails on regressions
  compare A B          compare two reports

A case directory holds case.yaml (see templates/eval-case.yaml). The review
command comes from .review/config.yaml evals.command or --command and may use
{base} {head} {case_id} {out} {repo} {review_dir} placeholders. It must leave
review.json at {out} (or at {review_dir}/tmp/review.json).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import itertools
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

import review_common as rc

FIX_PATTERNS = ["revert", "hotfix", "regression", "incident", "fix", "bug", "rollback", "outage"]


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------


def load_cases(rd: pathlib.Path, only: set[str] | None = None) -> list[dict]:
    cases = []
    for case_dir in sorted((rd / "evals" / "cases").glob("*")):
        case_file = case_dir / "case.yaml"
        if not case_file.exists():
            continue
        data = rc.parse_yaml(case_file.read_text(encoding="utf-8")) or {}
        data.setdefault("id", case_dir.name)
        data.setdefault("kind", "bug")
        data.setdefault("expected", [])
        data["_dir"] = case_dir
        if only and data["id"] not in only:
            continue
        cases.append(data)
    return cases


def validate_case(case: dict) -> list[str]:
    errors = []
    if case.get("kind") not in ("bug", "clean", "synthetic"):
        errors.append(f"{case['id']}: kind must be bug|clean|synthetic")
    if not case.get("head_sha"):
        errors.append(f"{case['id']}: head_sha is required")
    if case.get("kind") != "clean" and not case.get("expected"):
        errors.append(f"{case['id']}: bug cases need at least one expected finding")
    for i, exp in enumerate(case.get("expected") or []):
        if not exp.get("file") or not exp.get("class"):
            errors.append(f"{case['id']}: expected[{i}] needs file and class")
        lines = exp.get("lines")
        if lines is not None and not (isinstance(lines, list) and len(lines) == 2):
            errors.append(f"{case['id']}: expected[{i}].lines must be [start, end]")
    return errors


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def norm_path(path: str) -> str:
    return re.sub(r"^(\./|a/|b/)", "", path or "").strip()


def finding_matches(finding: dict, expected: dict, tolerance: int) -> bool:
    f_path, e_path = norm_path(finding.get("file", "")), norm_path(expected.get("file", ""))
    if not (f_path == e_path or f_path.endswith("/" + e_path) or e_path.endswith("/" + f_path)):
        return False
    accept = expected.get("accept_classes") or [expected.get("class")]
    if "any" not in accept and finding.get("class") not in accept:
        return False
    lines = expected.get("lines")
    if not lines:
        return True
    f_lines = finding.get("lines") or [0, 0]
    return not (f_lines[1] + tolerance < lines[0] or f_lines[0] - tolerance > lines[1])


def score_run(case: dict, review: dict | None, tolerance: int) -> dict:
    if review is None:
        return {"ok": False, "findings": 0, "ids": [], "hits": 0, "expected": len(case.get("expected") or []),
                "cost_usd": None, "tokens": None}
    findings = review.get("findings") or []
    hits = 0
    matched_ids = []
    for exp in case.get("expected") or []:
        for f in findings:
            if finding_matches(f, exp, tolerance):
                hits += 1
                matched_ids.append(f.get("id"))
                break
    cost = review.get("cost") or {}
    return {"ok": True, "findings": len(findings), "ids": sorted(str(f.get("id")) for f in findings),
            "hits": hits, "expected": len(case.get("expected") or []),
            "matched_ids": matched_ids, "cost_usd": cost.get("usd"), "tokens": cost.get("tokens"),
            "runtime_level": (review.get("coverage") or {}).get("runtime_level"),
            "inverted": review.get("inverted")}


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def summarise(case_results: list[dict]) -> dict:
    expected_total = hits_total = 0
    clean_runs = clean_fp_runs = clean_fp_findings = 0
    findings_counts: list[int] = []
    stabilities: list[float] = []
    costs: list[float] = []
    failures = 0
    runs = 0
    inverted_hits = inverted_expected = plain_hits = plain_expected = 0
    for case in case_results:
        ok_runs = [r for r in case["runs"] if r["ok"]]
        failures += len(case["runs"]) - len(ok_runs)
        runs += len(case["runs"])
        for r in ok_runs:
            findings_counts.append(r["findings"])
            if r.get("cost_usd") is not None:
                costs.append(float(r["cost_usd"]))
            if case["kind"] == "clean":
                clean_runs += 1
                if r["findings"]:
                    clean_fp_runs += 1
                    clean_fp_findings += r["findings"]
            else:
                expected_total += r["expected"]
                hits_total += r["hits"]
                if r.get("inverted"):
                    inverted_hits += r["hits"]
                    inverted_expected += r["expected"]
                else:
                    plain_hits += r["hits"]
                    plain_expected += r["expected"]
        if len(ok_runs) >= 2:
            pairs = [jaccard(a["ids"], b["ids"]) for a, b in itertools.combinations(ok_runs, 2)]
            stabilities.append(sum(pairs) / len(pairs))

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "runs": runs,
        "failed_runs": failures,
        "catch_rate": round(hits_total / expected_total, 4) if expected_total else None,
        "expected_total": expected_total,
        "hits_total": hits_total,
        "clean_fp_rate": round(clean_fp_runs / clean_runs, 4) if clean_runs else None,
        "clean_fp_findings_mean": round(clean_fp_findings / clean_runs, 4) if clean_runs else None,
        "findings_per_pr": mean([float(n) for n in findings_counts]),
        "stability": mean(stabilities),
        "cost_usd_mean": mean(costs),
        "catch_rate_inverted": round(inverted_hits / inverted_expected, 4) if inverted_expected else None,
        "catch_rate_not_inverted": round(plain_hits / plain_expected, 4) if plain_expected else None,
    }


def render_report(report: dict) -> str:
    s = report["summary"]

    def fmt(value, pct=False):
        if value is None:
            return "n/a"
        return f"{value * 100:.1f}%" if pct else f"{value}"

    out = [f"# Review evals — {report['generated_at']}", "",
           f"Command: `{report['command']}`  ", f"Repeats: {report['repeats']}  ",
           f"Cases: {len(report['cases'])} ({report['bug_cases']} bug, {report['clean_cases']} clean)", "",
           "| Metric | Value |", "|---|---|",
           f"| Catch rate | {fmt(s['catch_rate'], True)} ({s['hits_total']}/{s['expected_total']}) |",
           f"| Clean-control false-positive rate | {fmt(s['clean_fp_rate'], True)} |",
           f"| Findings per PR | {fmt(s['findings_per_pr'])} |",
           f"| Stability (mean Jaccard of finding IDs across repeats) | {fmt(s['stability'])} |",
           f"| Cost per PR (USD) | {fmt(s['cost_usd_mean'])} |",
           f"| Catch rate, inverted / not | {fmt(s['catch_rate_inverted'], True)} / {fmt(s['catch_rate_not_inverted'], True)} |",
           f"| Failed runs | {s['failed_runs']}/{s['runs']} |", "",
           "| Case | Kind | Hits | Findings per run | Stable | Notes |", "|---|---|---|---|---|---|"]
    for case in report["cases"]:
        ok = [r for r in case["runs"] if r["ok"]]
        hits = "/".join(str(r["hits"]) for r in ok) + (f" of {ok[0]['expected']}" if ok and case["kind"] != "clean" else "")
        per_run = "/".join(str(r["findings"]) for r in ok)
        stable = "yes" if len({tuple(r["ids"]) for r in ok}) <= 1 else "no"
        notes = "; ".join(case.get("notes") or [])
        out.append(f"| {case['id']} | {case['kind']} | {hits or '-'} | {per_run or '-'} | {stable} | {notes} |")
    if report.get("gate"):
        out += ["", "## Gate", "", report["gate"]["message"]]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def prepare_review_dir(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Seeds an isolated .review/ for a run: config, kb, flows, local catalog."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in ("config.yaml", "flows.yaml", "bug-catalog.local.md"):
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    if (src / "kb").exists():
        shutil.copytree(src / "kb", dst / "kb")
    for sub in ("state", "tmp", "evals/cases"):
        (dst / sub).mkdir(parents=True, exist_ok=True)


def run_case(case: dict, repeat: int, args: argparse.Namespace, root: pathlib.Path, rd: pathlib.Path,
             vcs: str | None, config: dict) -> tuple[dict, list[str]]:
    notes: list[str] = []
    run_dir = rd / "tmp" / "evals" / rc.safe_name(case["id"]) / f"run{repeat}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    iso_rd = run_dir / "review"
    prepare_review_dir(rd, iso_rd)

    checkout = args.checkout
    if checkout == "auto":
        configured = str(config["evals"].get("checkout") or "auto")
        checkout = configured if configured in ("worktree", "none") else ("worktree" if vcs == "git" else "none")
    repo = root
    worktree = None
    if checkout == "worktree":
        worktree = run_dir / "worktree"
        try:
            rc.run(["git", "worktree", "add", "--detach", str(worktree), case["head_sha"]], cwd=root)
            repo = worktree
        except subprocess.CalledProcessError as exc:
            notes.append(f"worktree failed: {exc.stderr.strip()[:200]}; running in the main checkout")
            worktree = None

    out_path = run_dir / "review.json"
    base = case.get("base_sha") or (case["head_sha"] + "~1" if vcs == "git" else f"({case['head_sha']})-")
    command = args.command.format(base=base, head=case["head_sha"], case_id=case["id"], out=str(out_path),
                                  repo=str(repo), review_dir=str(iso_rd))
    env = dict(os.environ)
    env["CODE_REVIEW_DIR"] = str(iso_rd)
    env["CODE_REVIEW_EVAL_CASE"] = case["id"]
    if case.get("intent"):
        (iso_rd / "tmp" / "intent.md").write_text(str(case["intent"]), encoding="utf-8")
    if case.get("author_family"):
        env["CODE_REVIEW_AUTHOR_FAMILY"] = str(case["author_family"])
    started = time.time()
    log_path = run_dir / "command.log"
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            proc = subprocess.run(command, shell=True, cwd=str(repo), env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=args.timeout, check=False)
            if proc.returncode != 0:
                notes.append(f"command exited {proc.returncode} (see {log_path})")
        except subprocess.TimeoutExpired:
            notes.append(f"command timed out after {args.timeout}s")
    # Asynchronous agents may return before writing the file; wait for it.
    deadline = started + args.timeout
    fallback = iso_rd / "tmp" / "review.json"
    while time.time() < deadline and not out_path.exists() and not fallback.exists():
        time.sleep(2)
    if not out_path.exists() and fallback.exists():
        shutil.copy2(fallback, out_path)
    review = None
    if out_path.exists():
        try:
            review = rc.load_json(out_path)
        except json.JSONDecodeError as exc:
            notes.append(f"review.json is not valid JSON: {exc}")
    else:
        notes.append("no review.json produced")
    result = score_run(case, review, int(config["evals"]["line_tolerance"]))
    result["wall_seconds"] = round(time.time() - started, 1)
    result["log"] = str(log_path)
    if worktree is not None and not args.keep:
        rc.try_run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root)
    return result, notes


def cmd_run(args: argparse.Namespace) -> int:
    root, vcs = rc.find_repo_root()
    rd = rc.review_dir(root, args.review_dir)
    config = rc.load_config(rd)
    args.command = args.command or config["evals"]["command"]
    if not args.command:
        raise SystemExit("no review command: set evals.command in .review/config.yaml or pass --command")
    args.timeout = args.timeout or int(config["evals"]["timeout_seconds"])
    repeats = args.repeats or int(config["evals"]["repeats"])
    cases = load_cases(rd, set(args.cases.split(",")) if args.cases else None)
    if not cases:
        raise SystemExit("no cases found under .review/evals/cases/")
    errors = [e for c in cases for e in validate_case(c)]
    if errors:
        for e in errors:
            rc.eprint("case error: " + e)
        return 1
    if args.dry_run:
        for c in cases:
            rc.eprint(f"{c['id']}: {c['kind']} {c.get('base_sha', '?')[:12]}..{c['head_sha'][:12]} "
                      f"expected={len(c['expected'])}")
        return 0

    case_results = []
    for case in cases:
        runs = []
        notes: list[str] = []
        for repeat in range(1, repeats + 1):
            rc.eprint(f"[{case['id']}] run {repeat}/{repeats} ...")
            result, run_notes = run_case(case, repeat, args, root, rd, vcs, config)
            runs.append(result)
            notes.extend(f"run{repeat}: {n}" for n in run_notes)
            rc.eprint(f"[{case['id']}] run {repeat}: {'ok' if result['ok'] else 'FAILED'} "
                      f"hits={result['hits']}/{result['expected']} findings={result['findings']} "
                      f"({result['wall_seconds']}s)")
        case_results.append({"id": case["id"], "kind": case["kind"], "runs": runs, "notes": notes})

    report = {
        "schema": "code-review/eval-report/v1",
        "generated_at": rc.now_iso(),
        "command": args.command,
        "repeats": repeats,
        "bug_cases": sum(1 for c in cases if c["kind"] != "clean"),
        "clean_cases": sum(1 for c in cases if c["kind"] == "clean"),
        "cases": case_results,
        "summary": summarise(case_results),
    }
    if args.baseline:
        report["gate"] = gate(rc.load_json(pathlib.Path(args.baseline))["summary"], report["summary"])
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    reports_dir = rd / "evals" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    rc.write_json(reports_dir / f"{stamp}.json", report)
    (reports_dir / f"{stamp}.md").write_text(render_report(report), encoding="utf-8")
    sys.stdout.write(render_report(report))
    rc.eprint(f"report -> {reports_dir / (stamp + '.json')}")
    if args.gate and report.get("gate") and not report["gate"]["passed"]:
        return 2
    return 0


def gate(baseline: dict, current: dict) -> dict:
    problems = []
    if baseline.get("catch_rate") is not None and current.get("catch_rate") is not None:
        if current["catch_rate"] < baseline["catch_rate"]:
            problems.append(f"catch rate fell {baseline['catch_rate']:.3f} -> {current['catch_rate']:.3f}")
    if baseline.get("clean_fp_rate") is not None and current.get("clean_fp_rate") is not None:
        if current["clean_fp_rate"] > baseline["clean_fp_rate"]:
            problems.append(f"clean-control false positives rose {baseline['clean_fp_rate']:.3f} -> {current['clean_fp_rate']:.3f}")
    passed = not problems
    message = "PASS: catch rate and clean-control false positives did not regress." if passed else \
        "FAIL: " + "; ".join(problems)
    return {"passed": passed, "message": message, "baseline": baseline, "current": current}


def cmd_compare(args: argparse.Namespace) -> int:
    a = rc.load_json(pathlib.Path(args.a))["summary"]
    b = rc.load_json(pathlib.Path(args.b))["summary"]
    keys = ["catch_rate", "clean_fp_rate", "findings_per_pr", "stability", "cost_usd_mean", "failed_runs"]
    print("| Metric | A | B |\n|---|---|---|")
    for key in keys:
        print(f"| {key} | {a.get(key)} | {b.get(key)} |")
    result = gate(a, b)
    print()
    print(result["message"])
    return 0 if result["passed"] else 2


# --------------------------------------------------------------------------
# Mining git history for cases
# --------------------------------------------------------------------------


def git_lines(root: pathlib.Path, *cmd: str) -> list[str]:
    out = rc.try_run(["git", *cmd], cwd=root, timeout=300)
    return out.splitlines() if out else []


def blame_introducers(root: pathlib.Path, fix_sha: str) -> tuple[collections.Counter, dict]:
    """For each line a fix commit removed, blame it in the parent to find the
    commit that introduced it. Returns (counter of shas, {sha: {file: [lines]}})."""
    counter: collections.Counter = collections.Counter()
    where: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    diff = rc.try_run(["git", "diff", "--unified=0", "--no-color", f"{fix_sha}~1", fix_sha], cwd=root) or ""
    current = None
    old_line = 0
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            current = line[6:]
        elif line.startswith("--- /dev/null"):
            current = None
        elif line.startswith("@@"):
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? ", line)
            old_line = int(match.group(1)) if match else 0
        elif line.startswith("-") and not line.startswith("---") and current:
            blame = rc.try_run(["git", "blame", "--porcelain", "-L", f"{old_line},{old_line}", f"{fix_sha}~1",
                                "--", current], cwd=root)
            if blame:
                sha = blame.split()[0]
                counter[sha] += 1
                where[sha][current].append(old_line)
            old_line += 1
        elif line.startswith(" "):
            old_line += 1
    return counter, where


def cmd_mine(args: argparse.Namespace) -> int:
    root, vcs = rc.find_repo_root()
    if vcs != "git":
        raise SystemExit("mine needs a git repository (jj: use `jj log` and write cases by hand)")
    rd = rc.review_dir(root, args.review_dir)
    grep_args = [f"--grep={p}" for p in (args.patterns.split(",") if args.patterns else FIX_PATTERNS)]
    log = git_lines(root, "log", f"--since={args.since}", "-i", "--no-merges", f"--max-count={args.max}",
                    "--format=%H%x1f%s%x1f%ad%x1f%b", "--date=short", *grep_args)
    proposals = []
    for record in log:
        parts = record.split("\x1f")
        if len(parts) < 3:
            continue
        sha, subject, date = parts[:3]
        body = parts[3] if len(parts) > 3 else ""
        reverted = re.search(r"This reverts commit ([0-9a-f]{7,40})", body)
        if reverted:
            intro = reverted.group(1)
            files = git_lines(root, "diff", "--name-only", f"{intro}~1", intro)
            expected = [{"file": f, "lines": None, "class": "TODO", "note": f"reverted by {sha[:12]} {subject}"} for f in files[:5]]
        else:
            counter, where = blame_introducers(root, sha)
            if not counter:
                continue
            intro, _ = counter.most_common(1)[0]
            expected = []
            for file, lines in where[intro].items():
                expected.append({"file": file, "lines": [min(lines), max(lines)], "class": "TODO",
                                 "note": f"lines removed by fix {sha[:12]} {subject}"})
        if intro.startswith(sha):
            continue
        proposals.append({"fix_sha": sha, "fix_subject": subject, "fix_date": date,
                          "head_sha": intro, "base_sha": f"{intro}~1", "expected": expected})
    clean = []
    if args.clean:
        for record in git_lines(root, "log", f"--since={args.since}", "--no-merges", f"--max-count={args.max * 4}",
                                "--format=%H%x1f%s%x1f%ad", "--date=short"):
            sha, subject, date = (record.split("\x1f") + ["", ""])[:3]
            if re.search("|".join(FIX_PATTERNS), subject, re.I):
                continue
            files = git_lines(root, "diff", "--name-only", f"{sha}~1", sha)
            if not files:
                continue
            later_fixes = git_lines(root, "log", "-i", "--format=%H", f"{sha}..HEAD",
                                    *[f"--grep={p}" for p in FIX_PATTERNS], "--", *files)
            if not later_fixes:
                clean.append({"head_sha": sha, "base_sha": f"{sha}~1", "subject": subject, "date": date})
            if len(clean) >= args.max:
                break

    print(f"## Bug case proposals ({len(proposals)})\n")
    for p in proposals:
        print(f"- fix {p['fix_sha'][:12]} {p['fix_date']} \"{p['fix_subject']}\" -> introduced by {p['head_sha'][:12]}")
        for e in p["expected"]:
            print(f"    {e['file']} {e['lines'] or ''}")
    if args.clean:
        print(f"\n## Clean control proposals ({len(clean)})\n")
        for c in clean:
            print(f"- {c['head_sha'][:12]} {c['date']} \"{c['subject']}\"")
    if args.write:
        written = 0
        for p in proposals:
            slug = re.sub(r"[^a-z0-9]+", "-", p["fix_subject"].lower())[:40].strip("-") or p["head_sha"][:8]
            case_dir = rd / "evals" / "cases" / f"{p['fix_date'][:7]}-{slug}"
            if case_dir.exists():
                continue
            case_dir.mkdir(parents=True)
            case = {"id": case_dir.name, "kind": "bug", "base_sha": p["base_sha"], "head_sha": p["head_sha"],
                    "author_family": "unknown", "source": f"fix commit {p['fix_sha']}: {p['fix_subject']}",
                    "expected": [{k: v for k, v in e.items() if v is not None} for e in p["expected"]]}
            (case_dir / "case.yaml").write_text(
                "# Draft mined from git history. Set class per references/bug-catalog.md and check the lines.\n"
                + rc.dump_yaml(case), encoding="utf-8")
            written += 1
        for c in clean:
            case_dir = rd / "evals" / "cases" / f"clean-{c['head_sha'][:10]}"
            if case_dir.exists():
                continue
            case_dir.mkdir(parents=True)
            case = {"id": case_dir.name, "kind": "clean", "base_sha": c["base_sha"], "head_sha": c["head_sha"],
                    "source": f"{c['date']} {c['subject']} (no later fix touched its files)", "expected": []}
            (case_dir / "case.yaml").write_text(rc.dump_yaml(case), encoding="utf-8")
            written += 1
        rc.eprint(f"wrote {written} draft case(s) under {rd / 'evals' / 'cases'}; edit class/lines before running")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root, _ = rc.find_repo_root()
    rd = rc.review_dir(root, args.review_dir)
    cases = load_cases(rd)
    if not cases:
        print("no cases")
        return 0
    print("| id | kind | base..head | expected | author |\n|---|---|---|---|---|")
    for c in cases:
        print(f"| {c['id']} | {c['kind']} | {str(c.get('base_sha', '?'))[:10]}..{str(c['head_sha'])[:10]} | "
              f"{len(c['expected'])} | {c.get('author_family', '')} |")
    errors = [e for c in cases for e in validate_case(c)]
    for e in errors:
        rc.eprint("case error: " + e)
    return 1 if errors else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list cases")
    p.add_argument("--review-dir")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("mine", help="propose cases from git history")
    p.add_argument("--since", default="2 years ago")
    p.add_argument("--max", type=int, default=30)
    p.add_argument("--patterns", help="comma-separated --grep patterns for fix commits")
    p.add_argument("--clean", action="store_true", help="also propose clean controls")
    p.add_argument("--write", action="store_true", help="write draft case.yaml files")
    p.add_argument("--review-dir")
    p.set_defaults(func=cmd_mine)

    p = sub.add_parser("run", help="run the review command over the cases and score it")
    p.add_argument("--cases", help="comma-separated case ids (default: all)")
    p.add_argument("--repeats", type=int)
    p.add_argument("--command", help="override evals.command")
    p.add_argument("--timeout", type=int, help="seconds per run (default evals.timeout_seconds)")
    p.add_argument("--checkout", choices=("auto", "worktree", "none"), default="auto")
    p.add_argument("--keep", action="store_true", help="keep worktrees for inspection")
    p.add_argument("--baseline", help="previous report.json to compare against")
    p.add_argument("--gate", action="store_true", help="exit 2 if catch rate drops or clean FPs rise vs baseline")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--review-dir")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("compare", help="compare two report.json files")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
