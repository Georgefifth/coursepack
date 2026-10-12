# CoursePack MVP

## User and job
A teacher already has a Canvas export and needs an ordered, readable delivery for archive, handover or review. The app reduces the work after downloading: selection, ordering, preview and packaging.

## Core workflow
1. Import a Canvas Common Cartridge `.imscc` / `.zip` containing `imsmanifest.xml`, or try the clearly labelled synthetic demo.
2. Search titles/file names, filter selected-material issues, select material, directly rename delivery headings and reorder modules/items.
3. Inspect the full delivery preview and actionable missing/external/unsupported notices.
4. Download a portable ZIP (index, readable body, original safe attachments and JSON inventory), or open the same body in the browser print dialog and save as PDF.

## Scope
- Manifest title and organization tree; Canvas `course_settings/module_meta.xml` controls arrangement when present, while other declared material resources remain visible in a separate group.
- HTML pages, HTML assignment descriptions, plain text, ordinary file attachments, Common Cartridge web links and LTI descriptions.
- Unsupported quiz XML remains an explicitly labelled attachment; no reconstructed quizzes or answer keys.
- File-local images and links are rewritten. Missing references and external dependencies are listed with their originating item.
- Imported scripts, forms, frames, event handlers and source styles are removed. External content is never fetched automatically.
- Local processing through a loopback server or browser Web Worker; imported file content remains in memory. This tab saves arrangement metadata only, with disclosure and explicit clear.

## Acceptance criteria
- Demo and a synthetic namespace-qualified cartridge import through the same code path.
- Original order is preserved; selection and reordering change preview and export together.
- Renamed headings appear consistently in preview, print document and inventory.
- Excluded entries do not appear in index/body/inventory; unreferenced source files are not dumped into the delivery.
- A missing image produces a visible placeholder and a source-specific notice.
- External links remain visible but are explicitly identified as online dependencies.
- Exported local images/files resolve after extraction; original safe binary attachment bytes are unchanged.
- Imported active HTML cannot execute in preview or exported documents.
- PDF button invokes browser printing of the full arranged document and states that original attachments are delivered separately.
- Unsafe/unsupported import fails with an actionable error and keeps the previous course usable.

## Architecture and tradeoffs
The shared standard-library Python engine builds preview and archive from one delivery model. Native mode requires only Python. GitHub Pages runs that engine in a pinned Pyodide module worker, adding about 13 MB of initial runtime download to remove the installation prerequisite. Vanilla JavaScript handles interaction. ZIP limits and an in-memory session cap bound resource usage. Browser printing provides searchable body text, page breaks and an attachment index, but does not merge PDF/Office attachments into that body.

## Design plan
Palette: paper #ffffff, workspace #edf2f7, ink #172b45, binding blue #315cba, divider #d4deea, issue amber #82520c. System sans-serif for controls and locally available serif for course text. Left-aligned controls and a document canvas rather than a marketing landing page. One characteristic visual: the course resembles a bound teaching dossier, with its structure visible beside the delivery.

Review: avoid dashboard cards and decorative statistics. Counts describe included material and actionable issues. The preview occupies most of the screen. Selection and reorder controls have useful text labels, including keyboard alternatives to dragging.

## Validation and limits
Automated fixture-based acceptance/security tests and browser workflow checks. No real institution export or teacher usability study has been supplied. Success with real users should be measured against their current method using time, manual repair and omitted material, not visual preference alone.
