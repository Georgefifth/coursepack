# Publication review — 2026-10-12

Scope: this newly created CoursePack project only. No unrelated local project files were inspected or reused. Repository metadata revealed an inherited unrelated remote; it was not used. CoursePack has its own Git root and one origin: https://github.com/Georgefifth/coursepack.git.

The user's current request explicitly authorizes creating a GitHub repository and GitHub Pages deployment. The earlier project's no-publication rule was updated to reflect this authorization; the prohibition on publishing imported course data remains.

Staged files reviewed for common GitHub/OpenAI/AWS credential formats, private-key markers, private email/contact patterns and home-directory paths. No matches. This is a scoped pattern/content review, not a guarantee against all possible secrets. All fixtures, demo text and screenshot content are authored synthetic materials; no real student, teacher or institution data was supplied. `validation/`, `runtime_cache/`, `site/`, `.env*`, and Python bytecode are excluded from Git.

The public site contains application source, pinned unmodified runtime files and license notices. It has no Canvas credentials, analytics, user accounts, backend upload endpoint or database. Normal requests to GitHub Pages download the application/runtime; imported files stay in the browser worker. The local server remains loopback-only and is not exposed by Pages. Imported HTML cannot execute scripts in preview/exports. External resources are not automatically fetched. Clicking an explicit external link opens that destination separately.

Course/module names, order and selection are sessionStorage metadata, disclosed before/within use. They are not raw course files, but can still be sensitive; Clear course removes them. Downloaded archives remain wherever the user saves them. Browser sessions may be restored by the browser, so closing a tab is not advertised as a guaranteed metadata deletion.

Actions build permissions are contents:read, pages:write and id-token:write. No private course files are fed to CI. Runtime build downloads are size/SHA-256 pinned; production does not load a remote CDN. Third-party source and license links are in THIRD_PARTY.md.
