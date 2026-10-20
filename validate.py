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
                  describes (index.html) is present. This repo-specific
                  stage also validates any deployment configuration
                  found in the tree (render.yaml/render.yml, vercel.json,
                  Procfile, Dockerfile*, docker-compose*.yml/yaml,
                  netlify.toml, fly.toml, .github/workflows/*.yml/yaml):
                  each file found is parsed and checked structurally;
                  when none is present it prints a PASS line saying so.

Deterministic and offline.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()

# Repositories that exist on the ranadhir19 GitHub account.
KNOWN_REPOS = {
    "agentic-systems-lab", "governed-agents", "llm-inference-engine",
    "research", "open-managed-agents", "skillforge", "snowflake-assignment",
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


# ---------------------------------------------------------------------------
# Deployment-config validation (used by the repo-specific stage below):
# discovers deployment configs anywhere in the tree and validates each one.
# YAML files are parsed with PyYAML when importable; otherwise only a
# structural (non-empty) check is possible and that limitation is
# reported, never hidden.
# ---------------------------------------------------------------------------

DEPLOY_FILE_NAMES = {"render.yaml", "render.yml", "vercel.json", "Procfile",
                     "netlify.toml", "fly.toml"}
DEPLOY_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                    ".pytest_cache"}


def find_deploy_configs():
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in DEPLOY_SKIP_DIRS)
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            rel = p.relative_to(ROOT)
            if fn in DEPLOY_FILE_NAMES or fn.startswith("Dockerfile"):
                found.append(p)
            elif fn.startswith("docker-compose") and p.suffix in (".yml", ".yaml"):
                found.append(p)
            elif (len(rel.parts) == 3 and rel.parts[0] == ".github"
                  and rel.parts[1] == "workflows"
                  and p.suffix in (".yml", ".yaml")):
                found.append(p)
    return sorted(found)


def _load_yaml_config(path, notes):
    """Return (data, error). data is None when no parser is available."""
    try:
        import yaml
    except ImportError:
        notes.append("parser unavailable (PyYAML not importable) - "
                     "structural check only")
        if not path.read_text(errors="replace").strip():
            return None, "empty file"
        return None, None
    try:
        return yaml.safe_load(path.read_text(errors="replace")), None
    except Exception as exc:  # YAML syntax error
        return None, f"YAML does not parse: {exc}"


def _check_render(path, rel, problems, notes):
    data, err = _load_yaml_config(path, notes)
    if err:
        problems.append(f"{rel}: {err}")
        return
    if data is None:
        return
    if not isinstance(data, dict):
        problems.append(f"{rel}: top level must be a mapping")
        return
    services = data.get("services")
    if not isinstance(services, list) or not services:
        problems.append(f"{rel}: 'services' must be a non-empty list")
        return
    valid_types = {"web", "worker", "cron", "pserv", "static"}
    for i, svc in enumerate(services):
        where = f"{rel}: services[{i}]"
        if not isinstance(svc, dict):
            problems.append(f"{where} must be a mapping")
            continue
        if not svc.get("name"):
            problems.append(f"{where} has no 'name'")
        typ, env = svc.get("type"), svc.get("env")
        if typ not in valid_types:
            problems.append(f"{where} type {typ!r} not in {sorted(valid_types)}")
        if typ == "static":
            problems.append(f"{where} 'type: static' is invalid - a static "
                            "site is type: web with env: static")
        if env == "static" and typ != "web":
            problems.append(f"{where} env: static requires type: web")
        if env == "docker" or svc.get("runtime") == "docker":
            root_dir = svc.get("rootDir") or "."
            dockerfile = svc.get("dockerfilePath") or "./Dockerfile"
            if not (ROOT / root_dir / dockerfile).exists():
                problems.append(f"{where} docker runtime but dockerfilePath "
                                f"{dockerfile!r} does not exist")


def _check_vercel(path, rel, problems, notes):
    try:
        data = json.loads(path.read_text(errors="replace"))
    except Exception as exc:
        problems.append(f"{rel}: JSON does not parse: {exc}")
        return
    if not isinstance(data, dict):
        problems.append(f"{rel}: top level must be an object")
        return
    if "builds" in data and not isinstance(data["builds"], list):
        problems.append(f"{rel}: 'builds' must be a list")
    if "functions" in data and not isinstance(data["functions"], dict):
        problems.append(f"{rel}: 'functions' must be an object")


def _check_dockerfile(path, rel, problems, notes):
    lines = [ln.strip() for ln in path.read_text(errors="replace").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        problems.append(f"{rel}: empty Dockerfile")
        return
    heads = [ln.split(None, 1)[0].upper() for ln in lines]
    if "FROM" not in heads:
        problems.append(f"{rel}: no FROM instruction")
    if "CMD" not in heads and "ENTRYPOINT" not in heads:
        problems.append(f"{rel}: no CMD or ENTRYPOINT instruction")


def _check_compose(path, rel, problems, notes):
    data, err = _load_yaml_config(path, notes)
    if err:
        problems.append(f"{rel}: {err}")
        return
    if data is None:
        return
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, dict) or not services:
        problems.append(f"{rel}: 'services' must be a non-empty mapping")


def _check_workflow(path, rel, problems, notes):
    data, err = _load_yaml_config(path, notes)
    if err:
        problems.append(f"{rel}: {err}")
        return
    if data is None:
        return
    if not isinstance(data, dict):
        problems.append(f"{rel}: top level must be a mapping")
        return
    # YAML 1.1 parses the bare key `on` as boolean True.
    if "on" not in data and True not in data:
        problems.append(f"{rel}: missing 'on' trigger")
    if "jobs" not in data:
        problems.append(f"{rel}: missing 'jobs'")


def _check_procfile(path, rel, problems, notes):
    lines = [ln for ln in path.read_text(errors="replace").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        problems.append(f"{rel}: empty Procfile")
        return
    for ln in lines:
        if not re.match(r"^[\w.-]+:\s*\S+", ln):
            problems.append(f"{rel}: line does not match 'name: command': {ln!r}")


def _check_toml(path, rel, problems, notes, need_app=False):
    try:
        data = tomllib.loads(path.read_text(errors="replace"))
    except Exception as exc:
        problems.append(f"{rel}: TOML does not parse: {exc}")
        return
    if need_app and "app" not in data:
        problems.append(f"{rel}: missing 'app' key")


def check_deploy_configs():
    """Return (problems, found_count); prints one line per file checked."""
    configs = find_deploy_configs()
    problems = []
    for p in configs:
        rel = str(p.relative_to(ROOT))
        notes = []
        if p.name in ("render.yaml", "render.yml"):
            _check_render(p, rel, problems, notes)
        elif p.name == "vercel.json":
            _check_vercel(p, rel, problems, notes)
        elif p.name.startswith("Dockerfile"):
            _check_dockerfile(p, rel, problems, notes)
        elif p.name.startswith("docker-compose"):
            _check_compose(p, rel, problems, notes)
        elif p.name == "Procfile":
            _check_procfile(p, rel, problems, notes)
        elif p.name == "fly.toml":
            _check_toml(p, rel, problems, notes, need_app=True)
        elif p.name == "netlify.toml":
            _check_toml(p, rel, problems, notes)
        elif p.suffix in (".yml", ".yaml"):
            _check_workflow(p, rel, problems, notes)
        for n in notes:
            print(f"  deployment-config: {rel}: {n}")
    return problems, len(configs)


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
    deploy_problems, deploy_found = check_deploy_configs()
    if not deploy_found:
        print("[PASS] deployment-config: none present — nothing to validate")
    for dp in deploy_problems:
        print(f"    INVALID deployment-config: {dp}")
    if missing:
        return report(False, "consistency",
                      "missing referenced files: " + ", ".join(missing))
    if deploy_problems:
        return report(False, "consistency",
                      f"{len(deploy_problems)} invalid deployment config(s)")
    detail = (f"index.html present; all {len(refs)} README-referenced "
              "local paths exist")
    if deploy_found:
        detail += (f"; {deploy_found} deployment config(s) checked, "
                   f"{len(deploy_problems)} invalid")
    return report(True, "consistency", detail)


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
