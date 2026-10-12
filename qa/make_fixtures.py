"""Synthetic browser-QA inputs, never copied from an existing project."""
from pathlib import Path
import io
import struct
import zlib
import zipfile
import server

ROOT = Path(__file__).resolve().parents[1] / 'qa-output' / 'fixtures'
ROOT.mkdir(parents=True, exist_ok=True)

def write_zip(name, files):
    with zipfile.ZipFile(ROOT / name, 'w', zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(path, data)

# A valid, authored PNG makes actual browser image loading testable.
def chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 80, 40, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\0' + bytes([70, 125, 170]) * 80) * 40)) + chunk(b'IEND', b'')
manifest = '''<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"><metadata><title>QA Evidence Course</title></metadata><organizations><organization><item><title>QA Evidence Course</title><item><title>Getting started</title><item identifierref="intro"><title>Introduction</title></item><item identifierref="lesson"><title>Evidence lesson</title></item><item identifierref="worksheet"><title>Worksheet</title></item></item></item></organization></organizations><resources><resource identifier="intro" type="webcontent" href="pages/intro.html"/><resource identifier="lesson" type="webcontent" href="pages/lesson.html"/><resource identifier="worksheet" type="webcontent" href="resources/worksheet.csv"/><resource identifier="quiz" type="imsqti" href="quiz.xml"/></resources></manifest>'''
files = {
    'imsmanifest.xml': manifest,
    'pages/intro.html': '<h2>Welcome to the evidence course</h2><p>Observe, record, and review.</p><img src="../resources/figure%20%E5%9B%BE.png" alt="Evidence figure"><a href="lesson.html#details">Continue to details</a><a href="../resources/worksheet.csv">Get worksheet</a><script>document.body.textContent="COMPROMISED"</script><p onclick="alert(1)">Safe retained text</p>',
    'pages/lesson.html': '<h2 id="details">Details to verify</h2><p>Each finding needs a source.</p><a href="https://example.com/">External reading</a><img src="missing.png" alt="Missing example">',
    'resources/worksheet.csv': 'Task,Evidence\nHandover,Original observation\n',
    'resources/figure 图.png': png,
    'resources/unreferenced.txt': 'This undeclared file must not be exported.',
    'quiz.xml': '<questestinterop><assessment title="Original quiz"/></questestinterop>',
}
write_zip('course.imscc', files)
changed = dict(files, **{'pages/intro.html': '<p>Different course content</p>'})
write_zip('changed.imscc', changed)
write_zip('html-only.zip', {'index.html': '<h1>Offline course</h1>'})
write_zip('empty.zip', {'imsmanifest.xml': '<manifest><metadata><title>Empty</title></metadata></manifest>'})
write_zip('unsafe.zip', {'../outside.txt': 'unsafe'})
(ROOT / 'corrupt.imscc').write_bytes(b'not a zip archive')
(ROOT / 'wrong.txt').write_text('not a course package')
(ROOT / 'demo.imscc').write_bytes(server.demo_bytes())
with (ROOT / 'oversize.imscc').open('wb') as f:
    f.truncate(50 * 1024 * 1024 + 1)
print('Authored QA fixtures:', ROOT)
