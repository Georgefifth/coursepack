# CoursePack

## Goal
Help teachers turn an existing Canvas course export into an ordered, readable course archive, with visible omissions and usable original attachments.

## Workspace boundary
This is a newly created, isolated project. Do not inspect, import, or reuse any other local project. Public documentation may be used for research. The user authorized publishing this product source and a GitHub Pages site on 2026-10-12. Never publish or send imported course data externally. Do not create a duplicate repository.

## Architecture
One Python standard-library import/export engine, shared by a loopback server and a Pyodide module Web Worker on GitHub Pages, plus plain HTML/CSS/JavaScript. Imported ZIPs remain in memory. Parse Common Cartridge manifests and Canvas module metadata; sanitize imported HTML before displaying or exporting it. No analytics, AI, or account connection. The Pages build bundles a pinned, SHA-256 verified Pyodide runtime on the same origin; no CDN is contacted at runtime. Browser sessions retain file data only in worker memory. sessionStorage retains arrangement metadata only, disclosed in the UI and removed on clear.

## Constraints
- Preserve source data; edits change the delivery arrangement only.
- Clearly distinguish included material, missing references, external dependencies, and unsupported content.
- Never claim that a package proves the source course is complete or accreditation-ready.
- Export a navigable ZIP and a print-ready HTML document; PDF is saved through the browser print dialog.
- Attachments remain separate original files. Do not silently claim they were converted or printed.
- Keyboard-accessible selection/reordering, responsive layout, visible focus and informative errors.
- Reject oversized archives, unsafe paths, encrypted entries, duplicate paths and unsafe XML declarations. Do not extract user ZIPs to disk or fetch their remote URLs.

## Validation
Use standard-library unittest for realistic import/export round trips, resource rewriting, omitted selections, malicious HTML, unsafe archives and HTTP workflows. Inspect the actual app in a browser if browser tooling is available. Public synthetic fixtures are not a substitute for testing real teacher exports; report that limitation.

## Quality bar
The main workflow must work end to end in the deployed static browser version and in the local Python version. Report the browser runtime cold-load cost. Demo content must exercise the real importer. Errors must identify the next useful action. Maintain PRODUCT.md, README.md and tests when behavior changes.
