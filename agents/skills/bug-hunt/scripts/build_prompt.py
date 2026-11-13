#!/usr/bin/env python3
"""Assembles a self-contained bug-hunting prompt for a headless model run.

Used when step 5 runs through another model family (model inversion) or in
the eval harness. The prompt text itself lives in subskills/05-analyse.md
between the prompt markers, so tuning the analysis prompt changes both the
in-session and the headless behaviour. Placeholders ({{diff}}, {{intent}},
{{context_pack}}, {{catalog}}, {{nitpicks}}, {{schema}}, {{explaining}},
{{blind_spots}}, {{author_family}}, {{depth}}, {{changed_files}}) are filled
from .review/tmp/ and the skill's references.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

import review_common as rc

PROMPT_START = "<!-- prompt:start -->"
PROMPT_END = "<!-- prompt:end -->"


def between(text: str, start: str, end: str, what: str) -> str:
    match = re.search(re.escape(start) + r"\n?(.*?)\n?" + re.escape(end), text, re.S)
    if not match:
        raise SystemExit(f"{what}: markers {start} .. {end} not found")
    return match.group(1).strip("\n")


def changed_files_table(change: dict) -> str:
    rows = []
    for item in change.get("changed_files", []):
        flag = f" (skipped: {item['skipped']})" if item.get("skipped") else ""
        rename = f" (was {item['old_path']})" if item.get("old_path") else ""
        rows.append(f"- {item['status']} {item['path']}{rename} +{item['additions']} -{item['deletions']}{flag}")
    return "\n".join(rows) or "- (none)"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review-dir")
    parser.add_argument("--change", help="change.json (default: <review-dir>/tmp/change.json)")
    parser.add_argument("--author", help="author.json (default: <review-dir>/tmp/author.json if present)")
    parser.add_argument("--intent", help="intent markdown file (default: <review-dir>/tmp/intent.md)")
    parser.add_argument("--context", help="context pack markdown (default: <review-dir>/tmp/context.md)")
    parser.add_argument("--out", help="output path (default: <review-dir>/tmp/prompt.md)")
    parser.add_argument("--max-diff-chars", type=int, default=400_000)
    parser.add_argument("--incremental", action="store_true",
                        help="use the re-review diff (new commits only) when change.json has one")
    args = parser.parse_args(argv)

    root, _ = rc.find_repo_root()
    rd = rc.review_dir(root, args.review_dir)
    change = rc.load_json(pathlib.Path(args.change) if args.change else rd / "tmp" / "change.json")
    author_path = pathlib.Path(args.author) if args.author else rd / "tmp" / "author.json"
    author = rc.load_json(author_path) if author_path.exists() else {}

    intent_path = pathlib.Path(args.intent) if args.intent else rd / "tmp" / "intent.md"
    context_path = pathlib.Path(args.context) if args.context else rd / "tmp" / "context.md"
    intent = rc.read_text(intent_path, "(no intent statement was written; status unknown)")
    context_pack = rc.read_text(context_path, "(no context pack; judge from the diff alone and say so in coverage.not_checked)")

    subskill = rc.read_text(rc.SUBSKILLS_DIR / "05-analyse.md")
    template = between(subskill, PROMPT_START, PROMPT_END, "05-analyse.md")
    catalog = rc.read_text(rc.REFERENCES_DIR / "bug-catalog.md")
    local_catalog = rc.read_text(rd / "bug-catalog.local.md").strip()
    if local_catalog:
        catalog += "\n\n## Repo-specific classes\n\n" + local_catalog
    nitpicks = rc.read_text(rc.REFERENCES_DIR / "nitpicks.md")
    explaining = rc.read_text(rc.REFERENCES_DIR / "explaining.md")
    output_ref = rc.read_text(rc.REFERENCES_DIR / "output.md")
    schema = between(output_ref, "<!-- draft-schema:start -->", "<!-- draft-schema:end -->", "output.md")

    diff = change.get("diff", "")
    diff_note = ""
    if args.incremental and (change.get("rereview") or {}).get("diff"):
        diff = change["rereview"]["diff"]
        diff_note = (f"This is a re-review: only the commits since {change['rereview']['from'][:12]} "
                     "are shown. Prior findings are handled separately.\n\n")
    if len(diff) > args.max_diff_chars:
        diff = diff[:args.max_diff_chars] + "\n\n[diff truncated by build_prompt.py; list the remaining files under coverage.not_checked]\n"

    blind = author.get("blind_spot_classes") or []
    blind_text = ", ".join(f"`{c}`" for c in blind) if blind else (
        "(none documented for this family; for the second pass take `ai-artifacts` plus the two "
        "catalog classes most relevant to the changed files)")
    values = {
        "depth": (change.get("triage") or {}).get("depth", "standard"),
        "branch": change.get("branch", ""),
        "head_sha": str(change.get("head_sha", ""))[:12],
        "author_family": author.get("family", "unknown"),
        "blind_spots": blind_text,
        "changed_files": changed_files_table(change),
        "diff": diff_note + diff,
        "intent": intent.strip(),
        "context_pack": context_pack.strip(),
        "catalog": catalog.strip(),
        "nitpicks": nitpicks.strip(),
        "explaining": explaining.strip(),
        "schema": schema.strip(),
    }
    prompt = template
    for key, value in values.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"{{([a-z_]+)}}", prompt)))
    if unresolved:
        raise SystemExit(f"05-analyse.md uses unknown placeholders: {unresolved}")

    out_path = pathlib.Path(args.out) if args.out else rd / "tmp" / "prompt.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt + "\n", encoding="utf-8")
    rc.eprint(f"prompt.md -> {out_path} ({len(prompt):,} chars, ~{len(prompt) // 4:,} tokens)")
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
