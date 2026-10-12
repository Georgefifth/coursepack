# Independent Firefox acceptance plan

Primary target: deployed GitHub Pages. Secondary: native localhost and static candidate.
Browser: Playwright 1.62.1, actual headless Firefox 153.0. Synthetic authored fixtures only.

Each automated case opens the actual site, performs user actions, asserts business results, records console/page/network errors, and saves screenshots for failures. Important ZIPs are saved to disk, CRC checked, inspected for selection/order and original attachments, then extracted and opened in Firefox. Element existence alone is not acceptance.

The scenarios in `firefox.cjs` cover English first use/help; real demo and file import; images and fragments; portable archive reading; selection/filtering/batch selection/no results; archive/module naming; item/module movement and dragging; collapse; refresh/home/back/reimport/draft clearing; empty selection; wrong extension, oversized, corrupt, HTML-only, empty and unsafe packages with recovery; changed-package draft isolation; keyboard focus/selection/tabs; viewport anchoring; print document opening; and 1280×900, 768×1024, 390×844 and 320×740 workflows. PDF saving through the native Firefox print dialog is separately Blocked in headless automation.

Acceptance includes successful action, expected output, feedback, no unexpected errors, and the ability to continue. Expected HTTP 400 responses are permitted only for intentionally invalid native imports, whose UI recovery is asserted. Fault injection must be explicit and must not substitute for successful operations.

Run:

```sh
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 qa/make_fixtures.py
npm ci
npx playwright install firefox
# Linux hosts may need: npx playwright install-deps firefox
node qa/firefox.cjs https://georgefifth.github.io/coursepack/ public
node qa/firefox.cjs http://127.0.0.1:8765/ native
```

Raw results, screenshots, downloads and extracted archives go to ignored `qa-output/`. Keep failed rounds; do not delete tests, weaken assertions or replace a failing feature with a DOM shortcut. Visual review requires opening the actual screenshots; viewport geometry checks are supplementary. These are scripted acceptance observations, not real-user satisfaction data.

Loading-state tests delay one genuine engine/import response by a bounded 1.5 seconds, then continue it unchanged. They do not fabricate successful imports. Navigation uses DOM-ready waiting plus the same final business assertions; every scenario has a 120-second ceiling.
