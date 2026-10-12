"""Build self-contained GitHub Pages files with a verified, pinned Pyodide runtime."""
import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent

def build():
    lock = json.loads((ROOT / 'runtime-lock.json').read_text())
    cache = ROOT / 'runtime_cache'
    cache.mkdir(exist_ok=True)
    target = ROOT / 'site'
    target.mkdir(exist_ok=True)
    for source in (ROOT / 'static').iterdir():
        if source.is_file():
            shutil.copyfile(source, target / source.name)
    runtime = target / 'runtime'
    runtime.mkdir(exist_ok=True)
    for name, pin in lock['files'].items():
        path = cache / name
        if not path.exists():
            with urlopen(lock['base_url'] + name, timeout=90) as response:
                path.write_bytes(response.read())
        data = path.read_bytes()
        if len(data) != pin['size'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
            raise ValueError('Runtime integrity check failed: ' + name)
        shutil.copyfile(path, runtime / name)
    shutil.copyfile(ROOT / 'server.py', target / 'engine.py')
    shutil.copyfile(ROOT / 'THIRD_PARTY.md', target / 'THIRD_PARTY.md')
    for source in (ROOT / 'licenses').iterdir():
        shutil.copyfile(source, runtime / source.name)
    index = target / 'index.html'
    index.write_text(index.read_text().replace('<html lang="en">', '<html lang="en" data-engine="browser">'))
    (target / '.nojekyll').touch()
    print('Built site; pinned runtime bytes:', sum(p['size'] for p in lock['files'].values()))

if __name__ == '__main__':
    build()
