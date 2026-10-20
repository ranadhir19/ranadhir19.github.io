#!/usr/bin/env python3
"""Uniform validation harness for the ranadhir19.github.io hub repo.

Run from anywhere:  python3 validate.py

Stages (each prints a PASS/FAIL line; the final line is exactly
"HARNESS GREEN" or "HARNESS RED: <stage, ...>"; exit code 0 only when
every stage passes):

  1. html-parse   index.html parses with html.parser without errors
                  and its element nesting is balanced.
  2. links        every internal anchor (#...) has a matching id;
                  every github.com/ranadhir19/<repo> link names a repo
                  that exists on the account; every
                  ranadhir19.github.io/<path> link maps to a known
                  Pages path of an existing repo. Offline: nothing is
                  fetched; links are resolved against the known repo
                  and Pages structure recorded below.
  3. gate-scan    the standing employer-reference gate: every file in
                  the repo is passed to the gate scanner (located by
                  glob in ~/workspace/github-*-watch/). ANY candidate
                  hit fails this stage and is printed for human
                  judgment; the harness never auto-clears a hit.
  4. consistency  files named by README.md (relative markdown links
                  and backticked paths) exist, and the page the README
                  describes (index.html) is present.

Deterministic and offline.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()

# Repositories that exist on the ranadhir19 GitHub account.
KNOWN_REPOS = {
    "agentic-systems-lab", "governed-agents", "llm-inference-engine",
    "research", "open-managed-agents", "snowflake-assignment",
    "ranadhir19.github.io", "journal", "banf1", "banf1-wix", "banf",
    "banf2", "customer_recommendation", "imageprocessing",
}
# First path segments served as project Pages sites under
# ranadhir19.github.io/<path>/ (the hub itself is the root).
KNOWN_PAGES_PATHS = {"agentic-systems-lab", "llm-inference-engine", "research"}

VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img",
                 "input", "link", "meta", "param", "source", "track", "wbr"}

FAILURES: list[str] = []


def report(ok: bool, stage: str, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {stage}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAILURES.append(stage)
    return ok


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "a" and "href" in d:
            self.hrefs.append(d["href"])
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "a" and "href" in d:
            self.hrefs.append(d["href"])

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append(f"closing </{tag}> with empty stack")
        elif self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.errors.append(f"unclosed <{self.stack.pop()}> before </{tag}>")
            self.stack.pop()
        else:
            self.errors.append(f"stray closing </{tag}>")


def stage_html_parse(parser: PageParser, html: str) -> bool:
    try:
        parser.feed(html)
        parser.close()
    except Exception as e:  # HTMLParser rarely raises; be explicit anyway
        return report(False, "html-parse", f"parser exception: {e}")
    problems = list(parser.errors)
    if parser.stack:
        problems.append("unclosed elements at EOF: " + ", ".join(parser.stack))
    if problems:
        return report(False, "html-parse", "; ".join(problems[:5]))
    return report(True, "html-parse",
                  f"parsed cleanly; {len(parser.ids)} ids, balanced nesting")


def stage_links(parser: PageParser) -> bool:
    problems = []
    checked = {"anchors": 0, "repos": 0, "pages": 0, "relative": 0, "external": 0}
    for href in parser.hrefs:
        if href.startswith("#"):
            checked["anchors"] += 1
            if href[1:] not in parser.ids:
                problems.append(f"anchor {href} has no matching id")
        elif href.startswith("https://github.com/ranadhir19"):
            rest = href[len("https://github.com/ranadhir19"):].strip("/")
            if rest:
                repo = rest.split("/")[0]
                checked["repos"] += 1
                if repo not in KNOWN_REPOS:
                    problems.append(f"github link names unknown repo: {href}")
        elif href.startswith("https://ranadhir19.github.io"):
            rest = href[len("https://ranadhir19.github.io"):].strip("/")
            checked["pages"] += 1
            if rest and rest.split("/")[0] not in KNOWN_PAGES_PATHS:
                problems.append(f"Pages link maps to no known site: {href}")
        elif href.startswith(("http://", "https://")):
            checked["external"] += 1  # not resolvable offline; counted only
        elif href.startswith("mailto:"):
            continue
        else:
            checked["relative"] += 1
            if not (ROOT / href.split("#")[0]).exists():
                problems.append(f"relative link target missing: {href}")
    if problems:
        return report(False, "links", "; ".join(problems[:5]))
    return report(True, "links",
                  f"{checked['anchors']} anchors, {checked['repos']} repo links, "
                  f"{checked['pages']} Pages links, {checked['relative']} relative, "
                  f"{checked['external']} other external (not fetched, offline)")


def stage_gate_scan() -> bool:
    scanners = sorted(HOME.glob("workspace/github-*-watch/*_scan.py"))
    if not scanners:
        return report(False, "gate-scan", "gate scanner not found under ~/workspace")
    files = sorted(str(p) for p in ROOT.iterdir() if p.is_file())
    try:
        r = subprocess.run([sys.executable, str(scanners[0]), *files],
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return report(False, "gate-scan", "scanner timed out")
    hits = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                hits.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if hits:
        for h in hits[:20]:
            print(f"  candidate: {h.get('file')}:{h.get('line')} "
                  f"[{h.get('pattern')}] {h.get('text', '')[:160]}")
        return report(False, "gate-scan",
                      f"{len(hits)} candidate hit(s) - human judgment required, "
                      "none auto-cleared")
    return report(True, "gate-scan", f"0 candidate hits across {len(files)} files")


def stage_consistency() -> bool:
    readme = ROOT / "README.md"
    index = ROOT / "index.html"
    if not readme.exists():
        return report(False, "consistency", "README.md missing")
    if not index.exists():
        return report(False, "consistency", "index.html missing (README describes it)")
    text = readme.read_text(encoding="utf-8")
    refs: set[str] = set()
    for m in re.finditer(r"\]\(([^)\s]+)\)", text):
        t = m.group(1)
        if not t.startswith(("http://", "https://", "#", "mailto:")):
            refs.add(t)
    for m in re.finditer(r"`([^`\n]+)`", text):
        t = m.group(1).strip()
        if re.search(r"\.(md|py|json|html|yaml|yml|txt|toml|js|css)$", t) \
                and " " not in t and "*" not in t and not t.startswith("/"):
            refs.add(t)
    missing = sorted(r for r in refs if not (ROOT / r).exists())
    if missing:
        return report(False, "consistency",
                      "missing referenced files: " + ", ".join(missing))
    return report(True, "consistency",
                  f"index.html present; all {len(refs)} README-referenced "
                  "local paths exist")


def main() -> int:
    index = ROOT / "index.html"
    if not index.exists():
        report(False, "html-parse", "index.html missing")
        report(False, "links", "index.html missing")
        stage_gate_scan()
        stage_consistency()
    else:
        html = index.read_text(encoding="utf-8")
        parser = PageParser()
        stage_html_parse(parser, html)
        stage_links(parser)
        stage_gate_scan()
        stage_consistency()
    if FAILURES:
        print(f"HARNESS RED: {', '.join(FAILURES)}")
        return 1
    print("HARNESS GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
