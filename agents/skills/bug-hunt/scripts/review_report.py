#!/usr/bin/env python3
"""Turns a draft review into review.json + review.md and updates state.

Subcommands:
  finalize DRAFT   compute stable IDs, merge prior state, enforce caps and the
                   plain-language rule, write review.json/review.md, save state
  validate FILE    check a draft or review file against the schema rules
  render FILE      render review.json to markdown
  dismiss ID       mark a finding as dismissed so re-runs never raise it again
  id               print the stable ID for --class/--file/--code
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import review_common as rc

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}
CONFIDENCE_RANK = {"confirmed": 0, "traced": 1, "suspected": 2}
INTENT_STATUS = ("met", "partial", "not_met", "unknown")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_finding(f: dict, idx: int) -> tuple[list[str], list[str]]:
    """Returns (errors, drop_reasons). Errors must be fixed; drops are applied."""
    errors: list[str] = []
    drops: list[str] = []
    tag = f"finding[{idx}] {f.get('title') or f.get('file') or ''}".strip()
    for key in ("class", "file", "title", "failure_scenario", "evidence", "suggested_fix"):
        if not str(f.get(key) or "").strip():
            errors.append(f"{tag}: missing {key}")
    sev = f.get("severity")
    if sev not in SEVERITY_RANK:
        drops.append(f"{tag}: severity {sev!r} is below medium or invalid; nothing below medium is reported")
    conf = f.get("confidence")
    if conf not in CONFIDENCE_RANK:
        errors.append(f"{tag}: confidence must be confirmed|traced|suspected, got {conf!r}")
    elif conf == "suspected" and sev == "medium":
        drops.append(f"{tag}: suspected confidence is only allowed for critical/high; trace it or omit it")
    lines = f.get("lines")
    if not (isinstance(lines, list) and len(lines) == 2 and all(isinstance(n, int) for n in lines)):
        errors.append(f"{tag}: lines must be [start, end] integers")
    expl = f.get("explanation") or {}
    steps = expl.get("steps") if isinstance(expl, dict) else None
    if not isinstance(expl, dict) or not steps or not all(str(s).strip() for s in steps):
        errors.append(f"{tag}: explanation.steps is required (plain-language, step-by-step; see references/explaining.md)")
    if isinstance(expl, dict) and not str(expl.get("why_it_matters") or "").strip():
        errors.append(f"{tag}: explanation.why_it_matters is required")
    concepts = expl.get("concepts", []) if isinstance(expl, dict) else []
    for c in concepts or []:
        if not isinstance(c, dict) or not c.get("term") or not c.get("meaning"):
            errors.append(f"{tag}: each explanation.concepts item needs term and meaning")
            break
    if not str(f.get("code") or "").strip():
        errors.append(f"{tag}: code (the offending snippet) is required so the finding ID stays stable")
    return errors, drops


def validate_review(data: dict, final: bool) -> list[str]:
    errors: list[str] = []
    intent = data.get("intent") or {}
    if not isinstance(intent, dict):
        errors.append("intent must be an object")
    else:
        if intent.get("status") not in INTENT_STATUS:
            errors.append(f"intent.status must be one of {INTENT_STATUS}")
        if intent.get("status") != "unknown" and not str(intent.get("statement") or "").strip():
            errors.append("intent.statement is required unless status is unknown")
    coverage = data.get("coverage") or {}
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
    else:
        if not isinstance(coverage.get("not_checked"), list):
            errors.append("coverage.not_checked must be a list (empty only if truly everything was checked)")
        if not isinstance(coverage.get("runtime_level"), int) or not 0 <= coverage["runtime_level"] <= 4:
            errors.append("coverage.runtime_level must be an integer 0..4")
    if not isinstance(data.get("findings"), list):
        errors.append("findings must be a list")
    else:
        for i, f in enumerate(data["findings"]):
            e, d = validate_finding(f, i)
            errors.extend(e)
            if final:
                errors.extend(d)
            if final and not f.get("id"):
                errors.append(f"finding[{i}]: missing id")
    if final:
        for key in ("head_sha", "author_family", "reviewer_model", "prior_findings"):
            if key not in data:
                errors.append(f"missing {key}")
        if data.get("author_family") not in rc.FAMILIES:
            errors.append(f"author_family must be one of {rc.FAMILIES}")
    return errors


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


def state_paths(rd: pathlib.Path, state_key: str) -> tuple[pathlib.Path, pathlib.Path]:
    return rd / "state" / (rc.safe_name(state_key) + ".json"), rd / "state" / "dismissed.json"


def load_dismissed(path: pathlib.Path) -> dict:
    if path.exists():
        try:
            return rc.load_json(path)
        except json.JSONDecodeError:
            return {}
    return {}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_markdown(review: dict) -> str:
    findings = review.get("findings", [])
    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEVERITY_RANK}
    count_text = ", ".join(f"{n} {s}" for s, n in counts.items() if n) or "none"
    intent = review.get("intent") or {}
    coverage = review.get("coverage") or {}
    head = str(review.get("head_sha", ""))[:12]
    out = [f"# Code review — {review.get('branch', '')} @ {head}", ""]
    if findings:
        out.append(f"**{len(findings)} finding{'s' if len(findings) != 1 else ''}** ({count_text}). "
                   f"Intent: **{intent.get('status', 'unknown')}**.")
    else:
        out.append(f"**No findings that pass the reportability test.** Intent: **{intent.get('status', 'unknown')}**. "
                   "No findings does not mean no bugs; see what was not checked below.")
    reviewer = review.get("reviewer_model") or f"current model ({review.get('reviewer_family', 'unknown')})"
    route = review.get("route", "none")
    route_text = {
        "none": "no inversion (human or unknown author)",
        "cross-family": "cross-family: author and reviewer are different families",
        "inverted-cli": "inverted: step 5 ran on another family's model",
        "blind-spot": "same family, blind-spot pass instead of inversion",
    }.get(route, route)
    out += ["",
            "| | |", "|---|---|",
            f"| Depth | {review.get('depth', '')} |",
            f"| Author | {review.get('author_family', 'unknown')} |",
            f"| Reviewer | {reviewer}; {route_text} |",
            f"| Runtime level | {coverage.get('runtime_level', 0)} |",
            f"| Base..head | `{str(review.get('base_sha', ''))[:12]}..{head}` |",
            ""]
    out += ["## Intent", "", intent.get("statement") or "_No stated intent was found; nothing was invented._", ""]
    if intent.get("sources"):
        out.append("Sources: " + "; ".join(str(s) for s in intent["sources"]))
        out.append("")
    out += ["## Findings", ""]
    if not findings:
        out += ["_None._", ""]
    for i, f in enumerate(findings, 1):
        lines = f.get("lines") or [0, 0]
        loc = f"{f.get('file')}:{lines[0]}" + (f"-{lines[1]}" if lines[1] and lines[1] != lines[0] else "")
        out.append(f"### {i}. {f.get('title')}")
        out.append("")
        out.append(f"`{f.get('severity')}` · `{f.get('confidence')}` · class `{f.get('class')}` · id `{f.get('id')}`  ")
        out.append(f"`{loc}`")
        out.append("")
        out.append(f"**What goes wrong:** {f.get('failure_scenario')}")
        out.append("")
        expl = f.get("explanation") or {}
        out.append("**In plain language**")
        out.append("")
        concepts = expl.get("concepts") or []
        if concepts:
            out.append("Words to know:")
            out.append("")
            for c in concepts:
                out.append(f"- **{c.get('term')}** — {c.get('meaning')}")
            out.append("")
        out.append("Step by step:")
        out.append("")
        for n, step in enumerate(expl.get("steps") or [], 1):
            out.append(f"{n}. {step}")
        out.append("")
        out.append(f"Why it matters: {expl.get('why_it_matters', '')}")
        out.append("")
        if f.get("code"):
            out.append("```")
            out.append(str(f["code"]).rstrip())
            out.append("```")
            out.append("")
        out.append(f"**Evidence:** {f.get('evidence')}")
        out.append("")
        out.append(f"**Suggested fix:** {f.get('suggested_fix')}")
        if f.get("verified_by"):
            out.append("")
            out.append(f"**Verified by:** {f['verified_by']}")
        out.append("")
    omitted = review.get("omitted_findings") or []
    if omitted:
        out += ["### Over the cap", ""]
        out.append(f"{len(omitted)} further finding(s) were held back by the cap; fix the ones above first.")
        for f in omitted:
            out.append(f"- `{f.get('id')}` {f.get('severity')} — {f.get('title')} ({f.get('file')})")
        out.append("")
    out += ["## Coverage", ""]
    if coverage.get("checked"):
        out.append("Checked:")
        out.append("")
        out += [f"- {c}" for c in coverage["checked"]]
        out.append("")
    out.append("Not checked:")
    out.append("")
    out += [f"- {c}" for c in (coverage.get("not_checked") or ["(nothing was left unchecked)"])]
    out.append("")
    prior = review.get("prior_findings") or []
    if prior:
        out += ["## Prior findings", ""]
        for p in prior:
            out.append(f"- `{p.get('id')}` — {p.get('status')}" + (f": {p['title']}" if p.get("title") else ""))
        out.append("")
    kb = review.get("kb_updates") or []
    if kb:
        out += ["## Knowledge base updates proposed", ""]
        for item in kb:
            out.append(f"- **{item.get('entry')}**: {item.get('proposal')}")
        out.append("")
    cost = review.get("cost") or {}
    if any(cost.get(k) is not None for k in ("usd", "tokens", "wall_seconds")):
        out.append(f"_Cost: usd={cost.get('usd')} tokens={cost.get('tokens')} wall_seconds={cost.get('wall_seconds')}_")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_finalize(args: argparse.Namespace) -> int:
    root, _ = rc.find_repo_root()
    rd = rc.review_dir(root, args.review_dir)
    config = rc.load_config(rd)
    draft = rc.load_json(pathlib.Path(args.draft))
    change_path = pathlib.Path(args.change) if args.change else rd / "tmp" / "change.json"
    change = rc.load_json(change_path) if change_path.exists() else {}
    author_path = pathlib.Path(args.author) if args.author else rd / "tmp" / "author.json"
    author = rc.load_json(author_path) if author_path.exists() else {}

    errors: list[str] = []
    warnings: list[str] = []
    kept: list[dict] = []
    for i, f in enumerate(draft.get("findings") or []):
        e, d = validate_finding(f, i)
        errors.extend(e)
        if d:
            warnings.extend(d)
            continue
        f = dict(f)
        f["id"] = rc.finding_id(f.get("class", ""), f.get("file", ""), f.get("code", ""))
        kept.append(f)
    if errors:
        rc.eprint("draft has errors; fix them and re-run finalize:")
        for e in errors:
            rc.eprint("  - " + e)
        return 1

    # De-duplicate by ID, keeping the most severe / most confident copy.
    by_id: dict[str, dict] = {}
    for f in kept:
        cur = by_id.get(f["id"])
        if cur is None or (SEVERITY_RANK[f["severity"]], CONFIDENCE_RANK[f["confidence"]]) < (
                SEVERITY_RANK[cur["severity"]], CONFIDENCE_RANK[cur["confidence"]]):
            by_id[f["id"]] = f
        else:
            warnings.append(f"duplicate finding {f['id']} ({f.get('title')}) merged")
    findings = list(by_id.values())

    state_key = change.get("branch") or draft.get("branch") or "unnamed"
    state_path, dismissed_path = state_paths(rd, state_key)
    dismissed = load_dismissed(dismissed_path)
    prior_state = rc.load_json(state_path) if state_path.exists() else {}
    prior_findings = prior_state.get("findings", [])

    prior_out: list[dict] = []
    new_ids = {f["id"] for f in findings}
    for p in prior_findings:
        pid = p.get("id")
        if pid in dismissed:
            status = "dismissed"
        elif pid in new_ids:
            status = "still-present"
        else:
            status = "resolved"
        prior_out.append({"id": pid, "status": status, "title": p.get("title"), "file": p.get("file")})
    for f in findings:
        if f["id"] in dismissed and f["id"] not in {p["id"] for p in prior_out}:
            prior_out.append({"id": f["id"], "status": "dismissed", "title": f.get("title"), "file": f.get("file")})
    findings = [f for f in findings if f["id"] not in dismissed]

    findings.sort(key=lambda f: (SEVERITY_RANK[f["severity"]], CONFIDENCE_RANK[f["confidence"]], f["file"], f["lines"][0]))
    cap = int(config["limits"]["max_findings"])
    omitted = [{"id": f["id"], "severity": f["severity"], "title": f["title"], "file": f["file"]}
               for f in findings[cap:]]
    findings = findings[:cap]

    coverage = dict(draft.get("coverage") or {})
    coverage.setdefault("checked", [])
    coverage.setdefault("not_checked", [])
    coverage.setdefault("runtime_level", 0)
    review = {
        "schema": "code-review/review/v1",
        "generated_at": rc.now_iso(),
        "repo_root": change.get("repo_root", str(root)),
        "branch": state_key,
        "base_sha": change.get("base_sha", draft.get("base_sha", "")),
        "head_sha": change.get("head_sha", draft.get("head_sha", "")),
        "depth": draft.get("depth") or (change.get("triage") or {}).get("depth", "standard"),
        "author_family": draft.get("author_family") or author.get("family", "unknown"),
        "reviewer_model": draft.get("reviewer_model", ""),
        "reviewer_family": author.get("reviewer_family") or author.get("self_family") or "unknown",
        "route": author.get("route", "none"),
        "inverted": bool(draft.get("inverted", author.get("inverted", False))),
        "intent": draft.get("intent") or {"statement": "", "sources": [], "status": "unknown"},
        "findings": findings,
        "omitted_findings": omitted,
        "coverage": coverage,
        "prior_findings": prior_out,
        "kb_updates": draft.get("kb_updates") or [],
        "cost": draft.get("cost") or {"usd": None, "tokens": None, "wall_seconds": None},
    }
    errors = validate_review(review, final=True)
    if errors:
        rc.eprint("final review failed validation:")
        for e in errors:
            rc.eprint("  - " + e)
        return 1

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else rd / "tmp"
    rc.write_json(out_dir / "review.json", review)
    (out_dir / "review.md").write_text(render_markdown(review), encoding="utf-8")

    if not args.no_state:
        history = prior_state.get("history", [])
        history.append({"head_sha": review["head_sha"], "reviewed_at": review["generated_at"],
                        "findings": [f["id"] for f in findings]})
        state = {
            "schema": "code-review/state/v1",
            "branch": state_key,
            "head_sha": review["head_sha"],
            "reviewed_at": review["generated_at"],
            "findings": [{"id": f["id"], "class": f["class"], "file": f["file"], "lines": f["lines"],
                          "title": f["title"], "severity": f["severity"]} for f in findings + [
                              {**o, "class": "", "lines": [0, 0]} for o in omitted]],
            "history": history[-20:],
        }
        rc.write_json(state_path, state)

    for w in warnings:
        rc.eprint("warning: " + w)
    rc.eprint(f"review.json -> {out_dir / 'review.json'}")
    rc.eprint(f"review.md   -> {out_dir / 'review.md'}")
    rc.eprint(f"findings: {len(findings)} reported, {len(omitted)} over cap, "
              f"{sum(1 for p in prior_out if p['status'] == 'resolved')} prior resolved, "
              f"{sum(1 for p in prior_out if p['status'] == 'dismissed')} dismissed")
    print(out_dir / "review.json")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data = rc.load_json(pathlib.Path(args.file))
    final = "prior_findings" in data or args.final
    errors = validate_review(data, final=final)
    drops: list[str] = []
    if not final:
        for i, f in enumerate(data.get("findings") or []):
            drops.extend(validate_finding(f, i)[1])
    for d in drops:
        rc.eprint("would drop: " + d)
    if errors:
        for e in errors:
            rc.eprint("error: " + e)
        return 1
    rc.eprint(f"ok: {len(data.get('findings') or [])} findings, {len(drops)} would be dropped at finalize")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    review = rc.load_json(pathlib.Path(args.file))
    text = render_markdown(review)
    if args.out:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
        print(args.out)
    else:
        sys.stdout.write(text)
    return 0


def cmd_dismiss(args: argparse.Namespace) -> int:
    root, _ = rc.find_repo_root()
    rd = rc.review_dir(root, args.review_dir)
    dismissed_path = rd / "state" / "dismissed.json"
    dismissed = load_dismissed(dismissed_path)
    dismissed[args.id] = {"reason": args.reason or "", "dismissed_at": rc.now_iso()}
    rc.write_json(dismissed_path, dismissed)
    rc.eprint(f"{args.id} dismissed; it will not be raised again ({dismissed_path})")
    return 0


def cmd_id(args: argparse.Namespace) -> int:
    print(rc.finding_id(args.klass, args.file, args.code))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("finalize", help="produce review.json/review.md from a draft and save state")
    p.add_argument("draft")
    p.add_argument("--review-dir")
    p.add_argument("--change")
    p.add_argument("--author")
    p.add_argument("--out-dir")
    p.add_argument("--no-state", action="store_true", help="do not write .review/state (evals use this)")
    p.set_defaults(func=cmd_finalize)

    p = sub.add_parser("validate", help="validate a draft or final review file")
    p.add_argument("file")
    p.add_argument("--final", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("render", help="render review.json as markdown")
    p.add_argument("file")
    p.add_argument("--out")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("dismiss", help="never raise this finding ID again")
    p.add_argument("id")
    p.add_argument("--reason")
    p.add_argument("--review-dir")
    p.set_defaults(func=cmd_dismiss)

    p = sub.add_parser("id", help="compute a stable finding ID")
    p.add_argument("--class", dest="klass", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--code", required=True)
    p.set_defaults(func=cmd_id)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
