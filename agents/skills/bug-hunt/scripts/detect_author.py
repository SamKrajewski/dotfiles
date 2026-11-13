#!/usr/bin/env python3
"""Detects which model family (or human) wrote a change and picks the reviewer.

Reads .review/tmp/change.json and applies the fingerprint table from
references/inversion.md, in the order the skill prescribes: explicit label or
override, commit/PR text, branch prefix, bot logins and emails, registry.
Code style is never inspected. Output goes to .review/tmp/author.json.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

import review_common as rc

ALIASES = {
    "claude": "claude", "anthropic": "claude", "claude-code": "claude",
    "gpt": "gpt", "openai": "gpt", "codex": "gpt", "chatgpt": "gpt", "copilot": "gpt",
    "gemini": "gemini", "google": "gemini", "jules": "gemini", "jetski": "gemini",
    "human": "human", "none": "human", "other": "other", "unknown": "unknown",
}
CONF_ORDER = {"high": 3, "medium": 2, "low": 1, "none": 0}
SOURCE_ORDER = ["label", "message", "branch", "login", "email", "author", "registry"]


def normalise_family(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if raw in ALIASES:
        return ALIASES[raw]
    for key, value in ALIASES.items():
        if key in raw:
            return value
    return "other" if raw else "unknown"


def parse_table(text: str, start: str, end: str) -> list[list[str]]:
    """Extracts rows of the markdown table between two HTML comment markers."""
    match = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
    if not match:
        raise SystemExit(f"table markers {start!r}..{end!r} not found in inversion.md")
    rows = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue  # not a table row, or the header separator row
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    return rows[1:] if rows else []  # drop the header row


def load_fingerprints() -> list[dict]:
    text = rc.read_text(rc.REFERENCES_DIR / "inversion.md")
    fingerprints = []
    for cells in parse_table(text, "<!-- fingerprints:start -->", "<!-- fingerprints:end -->"):
        if len(cells) < 4:
            continue
        source, pattern, family, confidence = cells[:4]
        pattern = pattern.strip("`")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            rc.eprint(f"inversion.md: bad regex {pattern!r}: {exc}")
            continue
        fingerprints.append({"source": source.lower(), "regex": regex, "pattern": pattern,
                             "family": family.strip(), "confidence": confidence.lower()})
    if not fingerprints:
        raise SystemExit("inversion.md: fingerprint table is empty")
    return fingerprints


def load_blind_spots() -> dict[str, list[str]]:
    text = rc.read_text(rc.REFERENCES_DIR / "inversion.md")
    spots: dict[str, list[str]] = {}
    for cells in parse_table(text, "<!-- blindspots:start -->", "<!-- blindspots:end -->"):
        if len(cells) < 2:
            continue
        classes = [c.strip().strip("`") for c in cells[1].split(",")]
        spots[cells[0].strip().lower()] = [c for c in classes if c and not c.startswith("(")]
    return spots


def gather_texts(change: dict) -> dict[str, list[str]]:
    """Builds the candidate strings for each fingerprint source."""
    pr = change.get("pr") or {}
    messages: list[str] = []
    emails: list[str] = []
    authors: list[str] = []
    for commit in change.get("commits", []):
        messages.append(commit.get("subject") or "")
        messages.extend((commit.get("body") or "").splitlines())
        emails.append(commit.get("author_email") or "")
        authors.append(commit.get("author_name") or "")
    if pr:
        messages.append(pr.get("title") or "")
        messages.extend((pr.get("body") or "").splitlines())
    branches = [change.get("branch") or ""]
    if pr.get("head_ref"):
        branches.append(pr["head_ref"])
    return {
        "label": [str(l) for l in pr.get("labels", []) if l],
        "message": [m for m in messages if m.strip()],
        "branch": [b for b in branches if b],
        "login": [pr["author_login"]] if pr.get("author_login") else [],
        "email": [e for e in emails if e],
        "author": [a for a in authors if a],
    }


def match_signals(texts: dict[str, list[str]], fingerprints: list[dict]) -> list[dict]:
    signals = []
    for fp in fingerprints:
        for candidate in texts.get(fp["source"], []):
            match = fp["regex"].search(candidate)
            if not match:
                continue
            family = fp["family"]
            if family.startswith("$"):
                try:
                    family = match.group(int(family[1:]))
                except (IndexError, ValueError):
                    family = "other"
            signals.append({"source": fp["source"], "pattern": fp["pattern"],
                            "match": candidate.strip()[:160],
                            "family": normalise_family(family), "confidence": fp["confidence"]})
    return signals


def registry_signals(change: dict, config: dict, texts: dict[str, list[str]]) -> list[dict]:
    path = (config.get("inversion", {}).get("registry") or "").strip()
    if not path:
        return []
    reg_path = pathlib.Path(path).expanduser()
    if not reg_path.is_absolute():
        reg_path = pathlib.Path(change.get("repo_root", ".")) / reg_path
    if not reg_path.exists():
        return [{"source": "registry", "pattern": str(reg_path), "match": "missing file",
                 "family": "unknown", "confidence": "none"}]
    raw = rc.read_text(reg_path)
    data = json.loads(raw) if reg_path.suffix == ".json" else rc.parse_yaml(raw)
    if not isinstance(data, dict):
        return []
    lookup = {str(k).lower(): normalise_family(str(v)) for k, v in data.items()}
    signals = []
    for key in texts["email"] + texts["login"] + texts["author"]:
        family = lookup.get(key.lower())
        if family:
            signals.append({"source": "registry", "pattern": key, "match": key,
                            "family": family, "confidence": "medium"})
    return signals


def decide(signals: list[dict]) -> tuple[str, str, str]:
    """Returns (family, confidence, note) using the first source with a hit."""
    for source in SOURCE_ORDER:
        hits = [s for s in signals if s["source"] == source and s["confidence"] != "none"]
        if not hits:
            continue
        best = max(CONF_ORDER[h["confidence"]] for h in hits)
        top = [h for h in hits if CONF_ORDER[h["confidence"]] == best]
        families = {h["family"] for h in top}
        if len(families) == 1:
            return top[0]["family"], top[0]["confidence"], f"decided by {source}"
        return "other", "low", f"{source} signals disagree: {sorted(families)}"
    return "unknown", "none", "no agent fingerprints found (code style is never used)"


def route(family: str, self_family: str, reviewers: dict, blind_spots: dict[str, list[str]]) -> dict:
    self_family = normalise_family(self_family) if self_family else "unknown"
    weak = blind_spots.get(family, [])
    if family in ("human", "unknown"):
        return {"route": "none", "inverted": False, "reviewer_family": self_family,
                "reviewer_command": "", "blind_spot_classes": [],
                "explanation": "human or unknown author: review with the current model, no inversion"}
    if self_family in ("unknown", "other", "human"):
        return {"route": "blind-spot", "inverted": False, "reviewer_family": self_family,
                "reviewer_command": "", "blind_spot_classes": weak,
                "explanation": "inversion.self_family is not set, so same-family cannot be ruled out; "
                               "run the blind-spot pass"}
    if family != self_family:
        return {"route": "cross-family", "inverted": True, "reviewer_family": self_family,
                "reviewer_command": "", "blind_spot_classes": weak,
                "explanation": f"author is {family} and the reviewer is {self_family}: already a different "
                               "family; step 5 still runs the second pass over the author's weak classes"}
    for other, command in (reviewers or {}).items():
        other_norm = normalise_family(other)
        if command and command.strip() and other_norm != self_family:
            return {"route": "inverted-cli", "inverted": True, "reviewer_family": other_norm,
                    "reviewer_command": command.strip(), "blind_spot_classes": weak,
                    "explanation": f"author and reviewer are both {family}; run step 5 through the "
                                   f"configured {other_norm} command"}
    return {"route": "blind-spot", "inverted": False, "reviewer_family": self_family,
            "reviewer_command": "", "blind_spot_classes": weak,
            "explanation": f"author and reviewer are both {family} and no other-family command is "
                           "configured; add a blind-spot pass on the weak classes"}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--change", help="path to change.json (default: <review-dir>/tmp/change.json)")
    parser.add_argument("--review-dir")
    parser.add_argument("--family", help="override the detected family (explicit user statement)")
    parser.add_argument("--self-family", help="family of the reviewing model (default: config inversion.self_family)")
    parser.add_argument("--out", help="output path (default: <review-dir>/tmp/author.json)")
    args = parser.parse_args(argv)

    root, _ = rc.find_repo_root()
    rd = rc.review_dir(root, args.review_dir)
    config = rc.load_config(rd)
    change_path = pathlib.Path(args.change) if args.change else rd / "tmp" / "change.json"
    change = rc.load_json(change_path)

    fingerprints = load_fingerprints()
    texts = gather_texts(change)
    signals = match_signals(texts, fingerprints)
    signals += registry_signals(change, config, texts)

    override = (args.family or os.environ.get("CODE_REVIEW_AUTHOR_FAMILY")
                or config.get("inversion", {}).get("author_override") or "")
    if override:
        family, confidence, note = normalise_family(override), "high", "explicit override"
        signals.insert(0, {"source": "override",
                           "pattern": "--family / $CODE_REVIEW_AUTHOR_FAMILY / inversion.author_override",
                           "match": override, "family": family, "confidence": "high"})
    else:
        family, confidence, note = decide(signals)

    self_family = args.self_family or config.get("inversion", {}).get("self_family") or ""
    routing = route(family, self_family, config.get("inversion", {}).get("reviewers", {}),
                    load_blind_spots())
    result = {
        "schema": "code-review/author/v1",
        "family": family,
        "confidence": confidence,
        "note": note,
        "signals": signals,
        "self_family": normalise_family(self_family) if self_family else "unknown",
        **routing,
    }
    out_path = pathlib.Path(args.out) if args.out else rd / "tmp" / "author.json"
    rc.write_json(out_path, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
