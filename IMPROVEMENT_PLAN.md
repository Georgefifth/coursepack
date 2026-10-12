# Implementation decisions and acceptance criteria

Priority considers task failure first, then operation cost; ratings are qualitative, not invented weighted scores.

| Priority / change | User value and impact | Cost / risk | Acceptance |
|---|---|---|---|
| P0: retain manifest resources outside Canvas modules | Prevent silently incomplete delivery inventory | Small; associated-content bundles must not become duplicate materials | Partial module metadata fixture retains the remaining PDF in a separate group; only manifest resources, not every ZIP entry, are added |
| P0: heading and broken external XML handling | Prevent false missing-file reports and whole-preview failures | Small; unknown content must remain visibly unconverted | Canvas subheader yields no missing notice; malformed external description has notice and original XML attachment; other pages still render |
| P1: search, visible-item selection, collapsible modules | Reduce scrolling and repeated selection | Small; filters must never silently exclude delivery content | Search matches titles and source paths; filtered module checkbox affects only matches; clearing filter preserves selection; issue filter reflects selected-material notices |
| P1: direct module rename and session draft | Remove blocking prompt and repeated work after refresh | Medium; race conditions and metadata privacy | Enter/blur commits rename into preview/export; refresh + same-content reimport restores arrangement; changed-content package does not restore; clear removes draft and file data |
| P1: preview cache and viewport anchoring | Avoid redundant rendering and unexpected jumps | Medium; stale output and retained blob memory | Unchanged download/print reuses matching preview; changed snapshot invalidates cache; old asset URLs released after replacement document load |
| P1: true GitHub Pages execution | Remove Python installation prerequisite for trial | Medium/high: ~13 MB runtime, WebAssembly memory, browser compatibility | Deployed site imports, previews, searches, exports in worker without `/api/` server requests; ZIP outputs remain valid; import failures stay actionable |
| Deferred: HTML-only package conversion, full PDF/Office merge, live collection, cloud sync | Could expand useful workflows, but increases complexity and overlap | High; format fidelity, permissions and backend persistence | Needs real export corpus and task evidence before implementation |

The browser deployment shares the tested Python engine instead of replacing its importer/exporter. Native loopback mode remains available. GitHub Pages cannot run Python HTTP services, databases, school-account secrets or synchronization jobs. It serves our self-contained worker/runtime; course processing is entirely in the browser. A future multi-user/cloud product needs a separate backend and a new privacy design.

No AI feature, redundant dashboard, or complex animation was added. Direct edits and recovery are the material UX changes; tests must catch lost edits and accidental inclusion before claiming improvement.
