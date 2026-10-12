import io
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def package(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


def fixture(page=None, meta=None):
    manifest = '''<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"><metadata><title>Methods</title></metadata><organizations><organization identifier="org"><item identifier="week"><title>Week one</title><item identifier="a" identifierref="r1"><title>Welcome</title></item><item identifier="b" identifierref="r2"><title>Exercise</title></item><item identifier="c" identifierref="r3"><title>Handout</title></item></item></organization></organizations><resources><resource identifier="r1" type="webcontent" href="wiki_content/start.html"><file href="wiki_content/start.html"/></resource><resource identifier="r2" type="webcontent" href="wiki_content/exercise.html"/><resource identifier="r3" type="webcontent" href="web_resources/手册 (1).pdf"/></resources></manifest>'''
    data = {'imsmanifest.xml': manifest,
            'wiki_content/start.html': page or '<p>Start here</p><img src="../web_resources/photo.png" alt="diagram"><a href="exercise.html">Exercise</a><a href="../web_resources/手册%20%281%29.pdf">Handout</a>',
            'wiki_content/exercise.html': '<p>Observe one real task.</p>',
            'web_resources/手册 (1).pdf': b'%PDF-1.4\nfixture-original',
            'web_resources/photo.png': b'\x89PNG\r\n\x1a\nfixture',
            'web_resources/not-selected.txt': b'Unreferenced private material'}
    if meta is not None:
        data['course_settings/module_meta.xml'] = meta
    return package(data)


class CourseAcceptanceTests(unittest.TestCase):
    def test_manifest_preserves_single_module_and_order(self):
        course = server.Course(fixture())
        self.assertEqual(course.title, 'Methods')
        self.assertEqual(course.groups[0]['title'], 'Week one')
        self.assertEqual([i['title'] for i in course.items.values()], ['Welcome', 'Exercise', 'Handout'])

    def test_canvas_module_metadata_controls_order(self):
        meta = '<modules><module identifier="m"><title>Studio</title><items><item><title>Do this first</title><content_type>WikiPage</content_type><identifierref>r2</identifierref></item><item><title>Then read</title><identifierref>r1</identifierref></item></items></module></modules>'
        course = server.Course(fixture(meta=meta))
        self.assertEqual(course.groups[0]['title'], 'Studio')
        self.assertEqual([i['path'] for i in course.items.values()], ['wiki_content/exercise.html', 'wiki_content/start.html', 'web_resources/手册 (1).pdf'])
        self.assertEqual(course.groups[-1]['title'], '未编入模块的材料')

    def test_module_heading_is_not_a_missing_file(self):
        meta = '<modules><module><title>Week</title><items><item><title>Discussion</title><content_type>ContextModuleSubHeader</content_type></item></items></module></modules>'
        course = server.Course(fixture(meta=meta))
        result = course.render({})
        self.assertEqual(course.kind(course.items['i1']), '分节')
        self.assertFalse(any(n['item'] == 'i1' for n in result['notices']))
        self.assertEqual(len(course.items), 4)

    def test_fingerprint_matches_contents_not_zip_metadata(self):
        first = server.Course(fixture())
        self.assertEqual(first.fingerprint, server.Course(fixture()).fingerprint)
        self.assertNotEqual(first.fingerprint, server.Course(fixture('<p>Changed</p>')).fingerprint)

    def test_corrupt_external_description_does_not_block_other_material(self):
        with zipfile.ZipFile(io.BytesIO(fixture())) as z:
            files = {n: z.read(n) for n in z.namelist()}
        files['imsmanifest.xml'] = files['imsmanifest.xml'].decode().replace('</resources>', '<resource identifier="link" type="imswl" href="broken.xml"/></resources>')
        files['broken.xml'] = '<broken'
        course = server.Course(package(files))
        result = course.render({})
        self.assertIn('Start here', result['html'])
        self.assertTrue(any('未能解析' in n['message'] for n in result['notices']))
        with zipfile.ZipFile(io.BytesIO(course.export({}))) as z:
            self.assertIn('assets/broken.xml', z.namelist())

    def test_selection_reorder_and_rename_reach_export(self):
        course = server.Course(fixture())
        data = course.export({'title': 'My delivery', 'groups': [{'title': 'Chosen order', 'items': ['i2', 'i1']}]})
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            report = json.loads(z.read('inventory.json'))
            self.assertEqual([i['title'] for i in report['included']], ['Exercise', 'Welcome'])
            self.assertEqual(report['excluded_count'], 1)
            self.assertEqual(report['title'], 'My delivery')
            body = z.read('body.html').decode()
            self.assertLess(body.index('article id="i2"'), body.index('article id="i1"'))
            self.assertIn('Chosen order', body)
            self.assertNotIn('not-selected.txt', '\n'.join(z.namelist()))
            self.assertEqual(z.read('assets/web_resources/手册 (1).pdf'), b'%PDF-1.4\nfixture-original')

    def test_export_links_and_images_resolve_with_encoded_names(self):
        course = server.Course(fixture())
        with zipfile.ZipFile(io.BytesIO(course.export({}))) as z:
            body = z.read('body.html').decode()
            self.assertIn('src="assets/web_resources/photo.png"', body)
            self.assertIn('href="body.html#i2"', body)
            self.assertIn('assets/web_resources/%E6%89%8B%E5%86%8C%20%281%29.pdf', body)
            self.assertIn('assets/web_resources/photo.png', z.namelist())

    def test_excluded_page_not_copied_through_crosslink(self):
        course = server.Course(fixture())
        payload = {'groups': [{'title': 'Selected', 'items': ['i1']}]}
        rendered = course.render(payload, exporting=True)
        self.assertTrue(any(n['kind'] == 'unsupported' and 'exercise.html' in n['message'] for n in rendered['notices']))
        with zipfile.ZipFile(io.BytesIO(course.export(payload))) as z:
            self.assertFalse(any('exercise.html' in p for p in z.namelist()))

    def test_source_fragments_are_unique_and_preserved(self):
        page = '<h2 id="details">Details</h2><a href="#details">Jump</a><a href="exercise.html#details">Next details</a>'
        with zipfile.ZipFile(io.BytesIO(fixture(page))) as z:
            files = {name: z.read(name) for name in z.namelist()}
        files['wiki_content/exercise.html'] = '<h2 id="details">Other details</h2>'
        result = server.Course(package(files)).render({}, exporting=True)['html']
        self.assertIn('id="i1-src-details"', result)
        self.assertIn('id="i2-src-details"', result)
        self.assertIn('href="#i1-src-details"', result)
        self.assertIn('href="body.html#i2-src-details"', result)

    def test_missing_external_and_unsupported_are_distinct(self):
        course = server.Course(fixture('<img src="missing.jpg" alt="missing"><img src="https://example.com/image.png"><a href="https://example.com">Reading</a><iframe src="https://example.com/embed"></iframe>'))
        result = course.render({})
        self.assertTrue(any(n['kind'] == 'missing' for n in result['notices']))
        self.assertTrue(any(n['kind'] == 'external' for n in result['notices']))
        self.assertNotIn('src="https://', result['html'])
        self.assertIn('图片未包含', result['html'])
        self.assertIn('href="https://example.com"', result['html'])

    def test_external_and_attachment_links_preserve_reader(self):
        page = '<a href="https://example.com">Online</a><a href="../web_resources/手册%20%281%29.pdf">PDF</a><a href="exercise.html">Next</a>'
        result = server.Course(fixture(page)).render({}, exporting=True)['html']
        self.assertIn('href="https://example.com" rel="noopener noreferrer" target="_blank"', result)
        self.assertIn('href="body.html#i2" rel="noopener noreferrer">Next', result)
        self.assertIn('target="_blank" rel="noopener noreferrer">打开 / 下载附件', result)
        # Generated XML weblinks must follow the same policy as imported HTML links.
        demo = server.Course(server.demo_bytes()).render({})['html']
        self.assertIn('href="https://www.imsglobal.org/" target="_blank" rel="noopener noreferrer"', demo)

    def test_active_html_and_event_handlers_removed(self):
        page = '<script>window.hacked=1</script><style>body{display:none}</style><base href="https://evil.test"><p onclick="alert(1)">Keep this</p><a href="javascript:alert(1)">Bad</a><img src="../web_resources/photo.png" onerror="alert(1)"><form action="https://evil.test"><input name="secret"></form><svg onload="alert(1)"><script>alert(1)</script></svg>'
        output = server.Course(fixture(page)).render({})['html']
        for danger in ['<script', 'window.hacked', 'onclick=', 'onerror=', '<base', '<form', '<svg', 'javascript:']:
            self.assertNotIn(danger, output)
        self.assertIn('Keep this', output)

    def test_media_and_formula_omissions_are_visible(self):
        page = '<video><source src="../web_resources/clip.mp4"></video><math><mi>x</mi><mo>+</mo><mn>1</mn></math><svg><path/></svg>'
        with zipfile.ZipFile(io.BytesIO(fixture())) as z:
            files = {name: z.read(name) for name in z.namelist()}
        files['wiki_content/start.html'] = page
        files['web_resources/clip.mp4'] = b'original-media'
        course = server.Course(package(files))
        result = course.render({}, exporting=True)
        self.assertIn('打开媒体原文件', result['html'])
        self.assertIn('web_resources/clip.mp4', result['used'])
        self.assertTrue(any('数学' in n['message'] for n in result['notices']))
        self.assertTrue(any('图形' in n['message'] for n in result['notices']))

    def test_unsafe_archives_rejected(self):
        for path in ['../outside.txt', '/absolute.txt', 'folder\\file.txt']:
            with self.subTest(path=path), self.assertRaises(server.CourseError):
                server.Course(package({path: 'unsafe'}))

    def test_unsafe_xml_rejected(self):
        with self.assertRaises(server.CourseError):
            server.Course(package({'imsmanifest.xml': '<!DOCTYPE x [<!ENTITY a "x">]><manifest/>'}))

    def test_wrong_export_type_has_actionable_error(self):
        with self.assertRaisesRegex(server.CourseError, '离线 HTML'):
            server.Course(package({'index.html': '<h1>Offline course</h1>'}))

    def test_empty_export_and_duplicate_selection_rejected(self):
        course = server.Course(fixture())
        with self.assertRaises(server.CourseError):
            course.export({'groups': []})
        with self.assertRaises(server.CourseError):
            course.export({'groups': [{'title': 'a', 'items': ['i1', 'i1']}]})

    def test_demo_uses_real_parser_and_reports_issues(self):
        course = server.Course(server.demo_bytes())
        self.assertEqual(len(course.groups), 3)
        self.assertEqual(len(course.items), 6)
        result = course.render({})
        self.assertTrue(any(n['kind'] == 'missing' for n in result['notices']))
        self.assertTrue(any(n['kind'] == 'external' for n in result['notices']))


class HTTPWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def post(self, path, data, mime='application/json', origin=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        headers = {'Content-Type': mime}
        if origin:
            headers['Origin'] = origin
        return urlopen(Request(self.base + path, data=body, headers=headers), timeout=5)

    def test_native_page_transport_script_is_served(self):
        with urlopen(self.base + '/') as response:
            self.assertIn(b'src="transport.js"', response.read())
        with urlopen(self.base + '/transport.js') as response:
            self.assertIn(b'CourseTransport', response.read())
            self.assertIn('javascript', response.headers['Content-Type'])

    def test_import_preview_export_and_reset(self):
        course = json.load(self.post('/api/import', fixture(), 'application/zip'))
        token = course['token']
        payload = {'token': token, 'title': 'Teacher archive', 'groups': [{'title': 'First', 'items': ['i2']}]}
        render = json.load(self.post('/api/render', payload))
        self.assertEqual(render['count'], 1)
        self.assertEqual(render['excluded'], 2)
        with urlopen(self.base + render['url']) as response:
            self.assertIn(b'Observe one real task.', response.read())
            self.assertIn("default-src 'none'", response.headers['Content-Security-Policy'])
        with self.post('/api/export', payload) as response:
            self.assertEqual(response.headers['Content-Type'], 'application/zip')
            with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                self.assertEqual(json.loads(z.read('inventory.json'))['title'], 'Teacher archive')
        with urlopen(self.base + render['archiveUrl']) as response:
            self.assertIn('attachment;', response.headers['Content-Disposition'])
            with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                self.assertEqual([i['id'] for i in json.loads(z.read('inventory.json'))['included']], ['i2'])
        self.post('/api/reset', {'token': token}).close()
        with self.assertRaises(HTTPError):
            self.post('/api/render', payload)

    def test_cross_origin_and_unknown_assets_blocked(self):
        with self.assertRaises(HTTPError) as result:
            self.post('/api/demo', {}, origin='https://example.com')
        self.assertEqual(result.exception.code, 403)
        course = json.load(self.post('/api/demo', {}))
        with self.assertRaises(HTTPError) as result:
            urlopen(self.base + '/api/file/' + course['token'] + '?path=/etc/passwd')
        self.assertEqual(result.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
