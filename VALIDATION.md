# Validation

This repo carries a uniform, offline test harness in `validate.py`
(repo root). It is the deploy gate: do not push this repo unless the
harness is green in its current state.

```bash
python3 validate.py        # exit 0 and final line "HARNESS GREEN" required
```

## Stages

1. **html-parse** — `index.html` parses with Python's `html.parser`
   without errors and its element nesting is balanced (void elements
   excepted).
2. **links** — every internal anchor (`#...`) has a matching `id`;
   every `github.com/ranadhir19/<repo>` link names a repository that
   exists on the account; every `ranadhir19.github.io/<path>` link
   maps to a known Pages path of an existing repo. The check is
   offline: nothing is fetched. The known-repository and known-Pages
   lists are recorded in `validate.py` (`KNOWN_REPOS`,
   `KNOWN_PAGES_PATHS`) and must be updated there when the account's
   repositories change. Non-GitHub external links (e.g. LinkedIn) are
   counted but not resolved.
3. **gate-scan** — the standing employer-reference gate. Every file in
   the repo is passed to the gate scanner in
   `~/workspace/github-*-watch/`. Any candidate hit fails the stage and
   is printed for human judgment; the harness never auto-clears a hit.
4. **consistency** — the page `README.md` describes (`index.html`) is
   present, and any local files the README names (relative markdown
   links, backticked paths) exist. The current README names no local
   files, so this stage chiefly guards `index.html`'s presence. This
   repo-specific stage also runs **deployment-config validation**:
   the tree is walked (skipping `.git`) for `render.yaml`/`render.yml`,
   `vercel.json`, `Procfile`, `Dockerfile*`, `docker-compose*.yml`/
   `.yaml`, `netlify.toml`, `fly.toml`, and
   `.github/workflows/*.yml`/`*.yaml`. Each file found is parsed and
   validated (for example, a Render service must have a name and a
   valid type, a bare `type: static` is invalid — a static site is
   `type: web` with `env: static` — a docker runtime's
   `dockerfilePath` must exist, and a workflow must have `on` and
   `jobs`); any violation fails this stage. YAML is parsed with
   PyYAML when importable, otherwise a structural check only is
   reported. **No deployment configs are present as of this run** —
   this repo deploys via GitHub Pages — so the step prints
   `[PASS] deployment-config: none present — nothing to validate`.

## Last recorded run (2026-10-20)

```
[PASS] html-parse - parsed cleanly; 3 ids, balanced nesting
[PASS] links - 4 anchors, 6 repo links, 3 Pages links, 0 relative, 3 other external (not fetched, offline)
[PASS] gate-scan - 0 candidate hits across 4 files
[PASS] deployment-config: none present — nothing to validate
[PASS] consistency - index.html present; all 0 README-referenced local paths exist
HARNESS GREEN
```
