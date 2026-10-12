# MVP verification — 2026-10-12

## Completed
- 16 standard-library unittest cases passed, including the local HTTP import/render/export/reset workflow and preserved source fragment links.
- Namespace-qualified manifest and Canvas module metadata ordering checked with authored fixtures.
- Selection, reordering, renamed delivery headings, original attachment bytes and encoded filenames checked in exported ZIPs.
- Missing references, external dependencies, media/formula limitations and excluded pages checked.
- Script/event-handler removal, unsafe archive paths, unsafe XML, cross-origin requests and unknown assets checked.
- Actual app opened in the Codex browser. Demo imported through the production importer.
- Browser UI: selected 5 of 6 items; moved a module; changed archive title; observed updated preview and issue count; used a warning to navigate to the affected material.
- Desktop 1280×900 layout and the default narrow browser layout inspected. Temporary viewport override restored.
- Actual browser download succeeded through the ordinary attachment URL. The downloaded ZIP was copied to `validation/CoursePack-demo.zip` and checked: six entries, two declared issues, navigable HTML, original CSV attachment and no imported scripts.
- Print/PDF action opened a separate full-body document. No physical printing or PDF file saving was performed in automated verification.
- User-facing app tab retained. `preview.jpg` records the desktop workbench.

## Limitations
No real teacher export was supplied. Real Canvas versions, large courses, complex equations, embedded tools and institution-specific workflows still need user testing. PDF output uses browser printing and keeps original binary attachments separate. CoursePack does not prove original course completeness or accreditation compliance.

## Reproduce
Run `python3 -m unittest discover -s tests -v`, then `python3 server.py`. Open http://127.0.0.1:8765 and try the synthetic demo.


## Improvement pass — 2026-10-12

- 20 unittest cases now pass, including P0 inventory retention, Canvas subheader handling, malformed external description isolation, stable content fingerprints, and native transport-script delivery.
- All three JavaScript files pass `node --check`.
- The static build verifies six runtime files by pinned size and SHA-256; total 13,550,119 bytes before HTTP compression. The browser downloads five required runtime files; `pyodide.js` is bundled but the module entry uses `pyodide.mjs`.
- Actual static localhost UI imported the synthetic `.imscc` through the file chooser and Pyodide worker. No backend was running on that origin; the HTTP server only served files.
- Search “访谈” produced two matches without changing six selected entries. Clear all → select matching selected exactly two. Direct module rename and reorder appeared in the body. Refresh + demo reimport (same content, different ZIP timestamps) restored two selections, renamed module and order.
- A lost inline edit during asynchronous notice updates was reproduced, then fixed by saving input before preview redraw; subsequent rename/reorder and refresh recovery succeeded.
- Browser render request/worker round trip measured 9.7 ms for the six-item synthetic course (one local observation). A local reimport including runtime initialization measured 3,383.2 ms; a subsequent reload/reimport 3,905.2 ms. These are not cold public-network measurements or instructor task times.
- Worker export completed and produced a Blob save link for the selected/reordered course. The Codex browser download event and `downloadMedia` both timed out for Blob URLs; **static ZIP file saving has not yet been verified on disk**. Native HTTP attachment download was verified in the initial pass. No PDF file was actually saved.

### Reproducible operation differences

| Task | Before | After | Evidence strength |
|---|---|---|---|
| Rename module | Open prompt → enter title → confirm (3 semantic actions) | Enter title in visible field → Enter/blur (2 semantic actions) | Source comparison and actual UI/body verification; no human timing study |
| Recover demonstrated draft after refresh | Reimport, uncheck 4 items, rename, move module again | Reimport same content; selections/name/order restored | Actual static browser scenario; one synthetic course |
| Download unchanged arrangement | Render preview again before download | Reuse matching preview, then package; no preview request | Source cache guard; actual generated ZIP link, disk saving unconfirmed |
| Module metadata covers only two of three resources | Third resource absent | Third resource in separate group | Regression fixture; not a real school export |

The baseline CPython CPU medians (20 tiny-fixture runs) were import 0.701 ms, render 0.281 ms, export 0.778 ms. They exclude UI/network/runtime startup and cannot establish that browser mode is faster. No competitor latency benchmark, real instructor task time, task success rate, large-file benchmark, mobile memory benchmark, or real-institution format coverage was measured. Those claims remain unvalidated.

## Public deployment verification

- Created the isolated `Georgefifth/coursepack` repository after checking that the existing inherited remote belonged to an unrelated project and that this repository name was unused. Reviewed staged files for credential/contact/home-path patterns; no matches. Build caches, imported fixtures and validation downloads are ignored. Published materials and screenshots are synthetic.
- GitHub Actions acceptance tests, runtime-integrity build, and Pages deployment succeeded. First attempt failed because Pages had not yet been enabled; after enabling Pages, the rerun succeeded.
- Opened https://georgefifth.github.io/coursepack/ in the actual browser. Public `app.js`, `transport.js`, `worker.mjs`, and `engine.py` returned HTTP 200 and byte hashes matched reviewed source.
- Public synthetic demo import measured 5,575.2 ms on first use of that site, including environment initialization and generation request. First preview worker/transport round trip measured 17.0 ms; a changed five-item arrangement measured 50.3 ms. Single observations, not averages or guaranteed response times; iframe paint and human task time are not included in the render figure.
- Search then uncheck a filtered module removed only the matching material (six → five), preserving the nonmatching material. Module rename/reorder appeared in body. Worker ZIP generation exposed a save link; changing the arrangement immediately hid that old link.
- Public reload + same-content demo reimport restored five selections, custom archive/module names and module order. Clear + reimport restored the default six selections and source names; deleted draft did not return.
- Narrow layout tested at requested 390×844 viewport (actual content width 375 px after scrollbar); document content width also 375 px, with no horizontal overflow. Viewport override reset afterward.
- Before/after reader-anchor positions when removing an earlier page were 19.775 and 19.863 px (0.088 px difference), on one synthetic document. This checks position preservation, not overall usability.
- Final regression also protects external/attachment links from replacing the reader: they open separately with `noopener noreferrer`; internal material links keep in-document navigation. Total automated acceptance tests: **21**.
- Browser Blob file saving remains unconfirmed: save/download automation timed out. PDF file saving remains unperformed. Neither is reported as an end-to-end file-save success. Real instructor success rates remain unmeasured.
