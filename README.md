# CoursePack

A focused workbench for turning an existing Canvas course package into an ordered, readable archive. Select material, rename/reorder modules, inspect omissions, and deliver a navigable ZIP with original attachments. No AI, analytics, Canvas login or course uploads to a remote server.

## Browser version

[Open CoursePack](https://georgefifth.github.io/coursepack/). GitHub Pages serves a pinned Pyodide runtime and the same Python import/export engine in a module Web Worker. First use downloads about 13 MB; processing starts after that environment loads. Course files stay in worker memory. Closing the tab or clearing the course releases them. No server API or database is required.

Arrangement metadata (course/module names, order and selection) is saved in **this tab's sessionStorage**, not course content. Refresh, then reimport the same package to restore it. Clear course removes the draft. Closing a tab usually clears its session; browser session recovery may restore it. Use Clear course for explicit removal.

## Local Python version

Python 3.12+; no packages to install:

```bash
cd coursepack
python3 server.py
```

Open http://127.0.0.1:8765. The server binds to loopback only. Do not expose it through a public proxy. Files remain in RAM until clear, eviction, expiration or shutdown; at most three course sessions, expiring after two hours.

Both modes accept Canvas `.imscc`/`.zip` with a unique `imsmanifest.xml`, maximum 50 MB compressed, 100 MB expanded, 20 MB per file, 3,000 files and 1,000 material entries. Demo content is synthetic and uses the real importer. The archive includes `index.html`, printable `body.html`, `inventory.json` and usable original attachments under `assets/`.

## Scope and limitations

This is an archive arranger, not a full course backup or authoring platform. Canvas offline HTML-only packages are not supported. Quizzes remain original XML attachments; interactive content, embedded graphics and formulas may be simplified or explicitly omitted. Office/PDF/media files are separate attachments and are not merged into a printable PDF. External links are not downloaded or checked online. PDF saving uses the browser print dialog; it is not a server-generated PDF. Imported content is sanitized, but archive completeness cannot be inferred from a package.

Modern browser module workers, WebAssembly, and standard Blob downloads are required. Large packages can use considerably more RAM than their ZIP size; mobile/low-memory behavior and real school exports still require validation. First use requires a network connection. Browser cache is not an offline-install guarantee.

GitHub Pages cannot run the optional Python HTTP server, a database, account-secret processing or background synchronization. Any future cloud collaboration needs a separate backend and privacy design.

## Checks and static build

```bash
python3 -m unittest discover -s tests -v
python3 build_site.py
python3 -m http.server 8766 --bind 127.0.0.1 --directory site
```

`build_site.py` obtains the runtime from the official Pyodide CDN during build only, verifies pinned sizes/SHA-256, and bundles it on the same origin. See [third-party notices](THIRD_PARTY.md). No Python packages are fetched at runtime. The GitHub Actions workflow runs acceptance tests before deploying Pages.

See [competitive review](COMPETITIVE_REVIEW.md), [improvement priorities and acceptance](IMPROVEMENT_PLAN.md), [validation](VALIDATION.md), [product scope](PRODUCT.md) and [architecture constraints](AGENTS.md). Competitive advantages are hypotheses until tested with real instructors.


## Firefox acceptance testing

The interface, generated archive copy, error feedback and authored demo are English. Imported source content keeps its original language.

See `qa/TEST_PLAN.md` for real headless Firefox business scenarios. Install the pinned development-only Playwright dependency with `npm ci`, then `npx playwright install firefox`. Generate the synthetic inputs with `PYTHONPATH=. python3 qa/make_fixtures.py`. Run `npm run qa:public` against the deployed site, or start the native server and run `npm run qa:local`. Downloads, extracted archives, screenshots and JSON results stay under ignored `qa-output/`. These tests save actual ZIPs and read their extracted HTML in Firefox; they do not accept a download link as proof of a completed download.
