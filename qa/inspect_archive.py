"""Inspect actual browser downloads and safely extract them for Firefox reading tests."""
import json
from pathlib import Path
import sys
import zipfile

archive = Path(sys.argv[1])
target = archive.with_suffix('')
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None, 'ZIP CRC check failed'
    for name in z.namelist():
        resolved = (target / name).resolve()
        assert resolved.is_relative_to(target.resolve()), 'Unsafe output path'
    if len(sys.argv) > 2:
        with zipfile.ZipFile(sys.argv[2]) as source:
            for name in z.namelist():
                if name.startswith('assets/'):
                    assert z.read(name) == source.read(name[len('assets/'):]), 'Original attachment bytes changed: ' + name
    report = json.loads(z.read('inventory.json'))
    body = z.read('body.html').decode()
    index = z.read('index.html').decode()
    z.extractall(target)
    print(json.dumps({'report': report, 'body': body, 'index': index, 'files': z.namelist(), 'extracted': str(target.resolve())}))
