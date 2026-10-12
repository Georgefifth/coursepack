# Browser runtime notices

The GitHub Pages build redistributes unmodified Pyodide 314.0.7 runtime files, pinned by size and SHA-256 in `runtime-lock.json`. It loads no additional Python packages.

- Pyodide source and runtime: https://github.com/pyodide/pyodide/tree/314.0.7 — Mozilla Public License 2.0; full text: `licenses/PYODIDE-LICENSE.txt` (served as `runtime/PYODIDE-LICENSE.txt`). The unmodified upstream source is available at that version link.
- CPython and standard-library notices: https://github.com/python/cpython/tree/v3.14.0 — Python Software Foundation License and included component notices: `licenses/PYTHON-LICENSE.txt`.
- Emscripten runtime tooling: https://github.com/emscripten-core/emscripten — MIT / University of Illinois-NCSA notices: `licenses/EMSCRIPTEN-LICENSE.txt`.

Downloads originate from the official CDN named in Pyodide's quickstart: https://cdn.jsdelivr.net/pyodide/v314.0.7/full/. Production serves the verified runtime from its own GitHub Pages origin. None of these libraries receive course files. Source materials imported by users remain subject to their owners' rights; the site does not publish or upload those materials.
