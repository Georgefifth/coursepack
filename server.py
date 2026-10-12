"""Loopback-only CoursePack server. No third-party dependencies or remote requests."""
from __future__ import annotations

import argparse
import html
import hashlib
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
from pathlib import Path, PurePosixPath
import posixpath
import secrets
import stat
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).parent
MAX_UPLOAD = 50 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024
SAFE_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.txt', '.csv',
            '.docx', '.pptx', '.xlsx', '.doc', '.ppt', '.xls', '.mp3', '.mp4', '.webm',
            '.ogg', '.wav', '.m4a', '.xml'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif'}
SESSIONS: dict[str, tuple[float, 'Course']] = {}
LOCK = threading.Lock()


class CourseError(ValueError):
    pass


def tag(node):
    return node.tag.rsplit('}', 1)[-1]


def child(node, name):
    return next((x for x in node if tag(x) == name), None)


def text_of(node, name, default=''):
    item = child(node, name)
    return ''.join(item.itertext()).strip() if item is not None else default


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise CourseError('This course XML contains unsupported declarations. Export a standard course package again.')
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise CourseError('The course manifest could not be read. Export the course package again.') from exc


def safe_path(value):
    if not value or '\\' in value or '\x00' in value or value.startswith('/'):
        raise CourseError('This package contains an unsafe file path.')
    parts = value.split('/')
    if '..' in parts or ':' in parts[0]:
        raise CourseError('This package contains an unsafe file path.')
    return posixpath.normpath(value)


def esc(value):
    return html.escape(str(value), quote=True)


class Course:
    def __init__(self, data: bytes):
        if len(data) > MAX_UPLOAD:
            raise CourseError('This file exceeds 50 MB. Export a smaller course package.')
        self.files = {}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = z.infolist()
                if len(infos) > 3000 or sum(i.file_size for i in infos) > MAX_TOTAL:
                    raise CourseError('The expanded package exceeds the limit. Export the course in smaller parts.')
                for i in infos:
                    name = safe_path(i.filename)
                    if i.is_dir():
                        continue
                    if name in self.files:
                        raise CourseError('This package has duplicate file paths. Export it again.')
                    if i.file_size > MAX_FILE or i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16):
                        raise CourseError('This package contains oversized files, encrypted entries, or symbolic links.')
                    self.files[name] = z.read(i)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise CourseError('Could not read this archive. Choose a Canvas .imscc or .zip course export.') from exc
        manifests = [p for p in self.files if PurePosixPath(p).name == 'imsmanifest.xml']
        if len(manifests) != 1:
            raise CourseError('No unique course manifest was found. Use Canvas Settings > Export Course Content with the Course export type. Offline HTML packages are not supported.')
        self.manifest_path = manifests[0]
        self.base = posixpath.dirname(self.manifest_path)
        manifest = xml(self.files[self.manifest_path])
        self.title = next((''.join(x.itertext()).strip() for x in manifest.iter()
                           if tag(x) == 'title' and ''.join(x.itertext()).strip()), 'Untitled course')
        self.items = {}
        self.groups = []
        resources = {}
        for r in manifest.iter():
            if tag(r) != 'resource':
                continue
            hrefs = [x.get('href', '') for x in r if tag(x) == 'file']
            resources[r.get('identifier', '')] = {
                'href': r.get('href') or (hrefs[0] if hrefs else ''),
                'type': r.get('type', ''), 'files': hrefs,
            }

        referenced = set()

        def add(title, ref='', href='', kind='', indent=0):
            if ref:
                referenced.add(ref)
            rid = 'i' + str(len(self.items) + 1)
            r = resources.get(ref, {})
            href = href or r.get('href', '')
            path = self.resolve(href, self.manifest_path) if href else None
            self.items[rid] = {'id': rid, 'title': title or 'Untitled material', 'path': path,
                               'href': href, 'type': kind or r.get('type', ''),
                               'indent': indent, 'files': r.get('files', [])}
            return rid

        def flatten(node, out, depth=0):
            for n in node:
                if tag(n) != 'item':
                    continue
                title = text_of(n, 'title', 'Untitled material')
                ref = n.get('identifierref', '')
                if ref:
                    out.append(add(title, ref, indent=depth))
                else:
                    out.append(add(title, kind='heading', indent=depth))
                flatten(n, out, depth + 1)

        orgs = next((n for n in manifest.iter() if tag(n) == 'organizations'), None)
        org = child(orgs, 'organization') if orgs is not None else None
        if org is not None:
            roots = [n for n in org if tag(n) == 'item']
            # Common Cartridge uses a single root folder holding the actual modules.
            if len(roots) == 1 and not roots[0].get('identifierref'):
                nested = [n for n in roots[0] if tag(n) == 'item']
                is_wrapper = text_of(roots[0], 'title') in {self.title, '课程', 'Course'} or any(
                    not n.get('identifierref') and any(tag(x) == 'item' for x in n) for n in nested)
                if nested and is_wrapper:
                    roots = nested
            loose = []
            for n in roots:
                if not n.get('identifierref') and any(tag(x) == 'item' for x in n):
                    ids = []
                    flatten(n, ids)
                    self.groups.append({'id': 'g' + str(len(self.groups) + 1),
                                        'title': text_of(n, 'title', 'Course module'), 'items': ids})
                else:
                    loose.append(add(text_of(n, 'title', 'Course materials'), n.get('identifierref', ''),
                                     kind='' if n.get('identifierref') else 'heading'))
            if loose:
                self.groups.append({'id': 'g' + str(len(self.groups) + 1), 'title': 'Course materials', 'items': loose})

        meta_path = posixpath.join(self.base, 'course_settings/module_meta.xml')
        if meta_path in self.files:
            meta = xml(self.files[meta_path])
            modules = []
            old_items = self.items
            self.items = {}
            old_referenced = referenced.copy()
            referenced.clear()
            for m in meta.iter():
                if tag(m) != 'module':
                    continue
                ids = []
                container = child(m, 'items')
                if container is not None:
                    for item in container:
                        ref = text_of(item, 'identifierref') or item.get('identifierref', '')
                        href = text_of(item, 'url')
                        kind = text_of(item, 'content_type')
                        ids.append(add(text_of(item, 'title', 'Course materials'), ref, href, kind))
                modules.append({'id': 'g' + str(len(modules) + 1),
                                'title': text_of(m, 'title', 'Course module'), 'items': ids})
            if modules:
                self.groups = modules
            else:
                self.items = old_items
                referenced.update(old_referenced)

        # Modules are an arrangement, not a complete inventory of course resources.
        loose = [add(PurePosixPath(r["href"]).stem, ref)
                 for ref, r in resources.items()
                 if ref not in referenced and r["href"] and "associatedcontent" not in r["type"].lower()]
        if loose:
            self.groups.append({"id": "g" + str(len(self.groups) + 1),
                                "title": "Materials outside modules", "items": loose})

        if not self.items:
            ids = [add(PurePosixPath(r['href']).stem, ref) for ref, r in resources.items() if r['href']]
            self.groups = [{'id': 'g1', 'title': 'Course materials', 'items': ids}]
        if len(self.items) > 1000:
            raise CourseError('This package exceeds 1,000 material entries. Export it in smaller parts.')
        if not self.items:
            raise CourseError('No materials were found. Check that you selected course content when exporting.')
        digest = hashlib.sha256()
        for name, content in sorted(self.files.items()):
            digest.update(name.encode('utf-8') + b'\0' + hashlib.sha256(content).digest())
        self.fingerprint = digest.hexdigest()
        self.views = {}

    def resolve(self, href, origin):
        if not href:
            return None
        href = href.replace('$IMS-CC-FILEBASE$', self.base or '.')
        href = href.replace('%24IMS-CC-FILEBASE%24', self.base or '.')
        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            return None
        path = parts.path
        candidates = [posixpath.normpath(posixpath.join(posixpath.dirname(origin), path)),
                      posixpath.normpath(posixpath.join(self.base, path)), path.lstrip('/')]
        if '$IMS' not in href:
            candidates += [unquote(p) for p in candidates]
        for name in candidates:
            if name in self.files:
                return name
        return None

    def snapshot(self, payload):
        title = str(payload.get('title', self.title)).strip()[:200] or self.title
        raw_groups = payload.get('groups', self.groups)
        if not isinstance(raw_groups, list) or len(raw_groups) > 1000:
            raise CourseError('The delivery outline is invalid. Arrange the course again.')
        seen = set()
        groups = []
        for g in raw_groups:
            if not isinstance(g, dict) or not isinstance(g.get('items'), list):
                raise CourseError('The delivery outline is invalid.')
            ids = []
            for iid in g['items']:
                if not isinstance(iid, str) or iid not in self.items or iid in seen:
                    raise CourseError('The delivery outline contains unknown or duplicate materials.')
                seen.add(iid)
                ids.append(iid)
            if ids:
                groups.append({'title': str(g.get('title', 'Course module'))[:200], 'items': ids})
        return title, groups

    def render(self, payload, token='', exporting=False):
        title, groups = self.snapshot(payload)
        notices = []
        used = set()
        included = {iid for g in groups for iid in g['items']}
        sections = []
        inventory = []

        def notice(iid, kind, message):
            entry = {'item': iid, 'title': self.items[iid]['title'], 'kind': kind, 'message': message}
            if entry not in notices:
                notices.append(entry)

        def asset(path):
            suffix = PurePosixPath(path).suffix.lower()
            if suffix not in SAFE_EXT:
                return None
            used.add(path)
            return 'assets/' + quote(path, safe='/') if exporting else '/api/file/' + token + '?path=' + quote(path, safe='')

        def link(href, origin, iid, image=False):
            if href.startswith('#'):
                return '#' + iid + '-src-' + unquote(href[1:]) if not image else None
            if href.startswith('data:'):
                notice(iid, 'unsupported', 'Embedded data was not preserved. Provide a separate file.')
                return None
            parts = urlsplit(href)
            if parts.scheme.lower() in {'http', 'https'} or parts.netloc:
                notice(iid, 'external', 'Internet access is still required: ' + href[:250])
                return None if image else href
            if parts.scheme:
                notice(iid, 'unsupported', 'An unsupported link was removed.')
                return None
            found = self.resolve(href, origin)
            if found:
                matches = [k for k, v in self.items.items() if v['path'] == found and k in included]
                if matches and PurePosixPath(found).suffix.lower() in {'.html', '.htm'} and not image:
                    target = matches[0] + ('-src-' + unquote(parts.fragment) if parts.fragment else '')
                    return ('body.html' if exporting else '') + '#' + target
                if image and PurePosixPath(found).suffix.lower() not in IMAGE_EXT:
                    notice(iid, 'unsupported', 'Image format not preserved: ' + href[:180])
                    return None
                url = asset(found)
                if url:
                    return url
                notice(iid, 'unsupported', 'This link points to an excluded page or unsupported file: ' + href[:180])
            else:
                notice(iid, 'missing', 'Referenced file not found in this package: ' + href[:180])
            return None

        for g in groups:
            body = ['<section class="module"><h2>' + esc(g['title']) + '</h2>']
            for iid in g['items']:
                item = self.items[iid]
                path = item['path']
                suffix = PurePosixPath(path or '').suffix.lower()
                content = ''
                status = 'included'
                kind = item['type'].lower()
                if kind.replace(' ', '') in {'heading', 'contextmodulesubheader', 'subheader'}:
                    content = '<p class="source">Course section heading</p>'
                elif not path:
                    href = item['href']
                    if href.startswith(('https://', 'http://')):
                        notice(iid, 'external', 'This material still requires internet access: ' + href[:250])
                        content = '<p class="callout">Online material</p><p><a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + esc(href) + '</a></p>'
                        status = 'external'
                    else:
                        notice(iid, 'missing', 'This export does not contain the file for this item. Check the original course and save it separately.')
                        content = '<p class="callout">Material file not found. Only the outline entry is preserved.</p>'
                        status = 'missing'
                elif suffix in {'.html', '.htm'}:
                    parser = CleanHTML(lambda href, image=False: link(href, path, iid, image),
                                       lambda message: notice(iid, 'unsupported', message), iid + '-src-')
                    parser.feed(self.files[path].decode('utf-8-sig', errors='replace'))
                    content = parser.result()
                elif suffix in {'.txt', '.csv'}:
                    content = '<pre>' + esc(self.files[path].decode('utf-8-sig', errors='replace')) + '</pre>'
                    url = asset(path)
                    content += '<p class="attachment"><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">Download original file</a></p>'
                elif suffix == '.xml' and any(x in kind for x in ('weblink', 'imswl', 'basiclti', 'external')):
                    try:
                        doc = xml(self.files[path])
                    except CourseError:
                        doc = ET.Element('unreadable')
                    href = next((n.get('href') or (n.text or '').strip() for n in doc.iter()
                                 if tag(n) in {'url', 'launch_url'}), '')
                    if href.startswith(('https://', 'http://')):
                        notice(iid, 'external', 'This material requires an external service: ' + href[:250])
                        content = '<p class="callout">External service material</p><p><a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + esc(href) + '</a></p>'
                    else:
                        notice(iid, 'unsupported', 'The external tool description could not be read. Its original XML is preserved as an attachment.')
                        content = '<p class="attachment"><a href="' + esc(asset(path)) + '" target="_blank" rel="noopener noreferrer">Download original description</a></p>'
                    status = 'external'
                elif suffix in SAFE_EXT:
                    url = asset(path)
                    content = '<div class="attachment"><strong>' + esc(PurePosixPath(path).name) + '</strong><p>The original file is delivered separately, not merged into the printable body.</p><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">Open / download attachment</a></div>'
                    status = 'attachment'
                    if suffix == '.xml':
                        notice(iid, 'unsupported', 'Quiz or structured material is preserved as an original XML attachment. Its interactive content is not reconstructed.')
                else:
                    notice(iid, 'unsupported', 'Unsupported file type: ' + (suffix or 'no extension'))
                    content = '<p class="callout">This material could not be included. Save it separately.</p>'
                    status = 'unsupported'
                body.append('<article id="' + iid + '"><h3>' + esc(item['title']) + '</h3>' + content + '</article>')
                inventory.append({'id': iid, 'title': item['title'], 'module': g['title'],
                                  'source': path or item['href'], 'status': status})
            body.append('</section>')
            sections.append(''.join(body))
        summary = '<p class="scope">This archive includes ' + str(len(included)) + ' items; ' + str(len(self.items) - len(included)) + ' original items were not selected. Attachments are separate; online content still needs internet access. This report checks only the imported package.</p>'
        toc = '<nav class="contents"><h2>Delivery outline</h2>' + ''.join('<h3>' + esc(g['title']) + '</h3><ol>' + ''.join('<li><a href="#' + iid + '">' + esc(self.items[iid]['title']) + '</a></li>' for iid in g['items']) + '</ol>' for g in groups) + '</nav>'
        warnings = ''
        if notices:
            warnings = '<section class="review"><h2>Review before delivery</h2><ul>' + ''.join('<li><strong>' + esc(n['title']) + '</strong>：' + esc(n['message']) + '</li>' for n in notices) + '</ul></section>'
        empty = '<p class="empty">No materials selected. Choose the content to deliver in the outline.</p>' if not included else ''
        output = document(title, '<header class="cover"><p>Course archive</p><h1>' + esc(title) + '</h1>' + summary + '</header>' + toc + warnings + empty + ''.join(sections))
        if len(output.encode('utf-8')) > 10 * 1024 * 1024:
            raise CourseError('The selected body exceeds 10 MB. Include fewer pages or text materials.')
        return {'html': output, 'notices': notices, 'inventory': inventory, 'used': used,
                'count': len(included), 'excluded': len(self.items) - len(included)}

    def public(self, token):
        return {'token': token, 'fingerprint': self.fingerprint, 'title': self.title, 'groups': self.groups,
                'items': [{'id': i['id'], 'title': i['title'], 'type': self.kind(i),
                           'source': i['path'] or i['href']} for i in self.items.values()]}

    @staticmethod
    def kind(item):
        suffix = PurePosixPath(item['path'] or '').suffix.lower()
        if item['type'].lower().replace(' ', '') in {'heading', 'contextmodulesubheader', 'subheader'}:
            return 'Section'
        if suffix in {'.html', '.htm'}:
            return 'Page'
        if suffix == '.pdf':
            return 'PDF attachment'
        if any(x in item['type'].lower() for x in ('weblink', 'imswl', 'external', 'basiclti')):
            return 'Online material'
        return 'Attachment' if item['path'] else 'Needs review'

    def export(self, payload):
        rendered = self.render(payload, exporting=True)
        if not rendered['count']:
            raise CourseError('Select at least one item before exporting.')
        out = io.BytesIO()
        title, groups = self.snapshot(payload)
        index = '<h1>' + esc(title) + '</h1><p>Your course archive is ready. <a href="body.html">Read the complete body</a>. For a PDF, use the browser print command on the body page.</p>'
        for g in groups:
            index += '<h2>' + esc(g['title']) + '</h2><ul>' + ''.join('<li><a href="body.html#' + iid + '">' + esc(self.items[iid]['title']) + '</a></li>' for iid in g['items']) + '</ul>'
        index += '<p>Attachments retain their original formats; use the links in the body. External content is not downloaded automatically.</p>'
        report = {'title': title, 'included': rendered['inventory'], 'excluded_count': rendered['excluded'],
                  'notices': rendered['notices'], 'attachments': sorted(rendered['used']),
                  'scope': 'Checks the imported package only; does not establish source-course completeness or accreditation compliance.'}
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('index.html', document(title, index))
            z.writestr('body.html', rendered['html'])
            z.writestr('inventory.json', json.dumps(report, ensure_ascii=False, indent=2))
            for path in sorted(rendered['used']):
                z.writestr('assets/' + path, self.files[path])
        return out.getvalue()


class CleanHTML(HTMLParser):
    allowed = {'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em',
               'b', 'i', 'u', 's', 'br', 'hr', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
               'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'sub', 'sup',
               'a', 'img', 'dl', 'dt', 'dd'}
    blocked = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'form', 'template', 'head'}
    void = {'br', 'hr', 'img'}

    def __init__(self, resolver, on_unsupported=None, id_prefix='src-'):
        super().__init__(convert_charrefs=True)
        self.resolver = resolver
        self.on_unsupported = on_unsupported or (lambda _: None)
        self.id_prefix = id_prefix
        self.out = []
        self.skipping = []
        self.stack = []

    def handle_starttag(self, name, attrs):
        if self.skipping:
            if name in self.blocked:
                self.skipping.append(name)
            return
        if name in {'video', 'audio', 'source'}:
            attrs = dict(attrs)
            url = self.resolver(attrs['src']) if attrs.get('src') else None
            self.on_unsupported('Video or audio is not merged into the printable body; available originals are preserved as attachments.')
            if url:
                self.out.append('<p class="attachment"><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">Open original media file</a> (not merged into the printable body)</p>')
            return
        if name == 'math':
            self.on_unsupported('Math markup was simplified to text. Check formulas or provide a PDF attachment.')
        if name in self.blocked:
            if name in {'svg', 'form', 'object', 'embed'}:
                self.on_unsupported('Interactive content or embedded graphics were not converted. Provide a separate file.')
                self.out.append('<p class="callout">Interactive content or graphics here were not converted. Provide a separate file.</p>')
            if name == 'iframe':
                attrs = dict(attrs)
                url = self.resolver(attrs['src']) if attrs.get('src') else None
                self.out.append('<p class="callout">Embedded content was not included in the body. ' +
                                ('<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">Open linked resource</a>' if url else 'Check the external resource.') + '</p>')
            if name not in {'embed'}:
                self.skipping.append(name)
            return
        if name not in self.allowed:
            return
        attrs = dict(attrs)
        extra = ''
        if name in {'a', 'img'}:
            original = attrs.get('href' if name == 'a' else 'src', '')
            url = self.resolver(original, name == 'img') if original else None
            if url:
                extra += ' ' + ('href' if name == 'a' else 'src') + '="' + esc(url) + '"'
                if name == 'a':
                    extra += ' rel="noopener noreferrer"'
                    if not url.startswith(('#', 'body.html#')):
                        extra += ' target="_blank"'
            elif name == 'img':
                self.out.append('<span class="callout">[Image not included：' + esc(attrs.get('alt', 'save separately')) + ']</span>')
                return
            if name == 'img':
                extra += ' alt="' + esc(attrs.get('alt', '')) + '"'
        for key in ('colspan', 'rowspan'):
            if name in {'td', 'th'} and attrs.get(key, '').isdigit():
                extra += ' ' + key + '="' + str(min(int(attrs[key]), 100)) + '"'
        if attrs.get('id'):
            extra += ' id="' + self.id_prefix + esc(attrs['id']) + '"'
        self.out.append('<' + name + extra + '>')
        if name not in self.void:
            self.stack.append(name)

    def handle_startendtag(self, name, attrs):
        self.handle_starttag(name, attrs)
        if name not in self.void:
            self.handle_endtag(name)

    def handle_endtag(self, name):
        if self.skipping:
            if name == self.skipping[-1]:
                self.skipping.pop()
            return
        if name in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.out.append('</' + current + '>')
                if current == name:
                    break

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(esc(data))

    def result(self):
        return ''.join(self.out) + ''.join('</' + x + '>' for x in reversed(self.stack))


DOC_STYLE = """
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:#172b45;font:16px/1.75 Georgia,'Noto Serif CJK SC','Songti SC',serif}main{max-width:850px;margin:auto;padding:54px 56px}h1{font-size:34px;line-height:1.35;overflow-wrap:anywhere}h2{font-size:24px;line-height:1.4}h3{font-size:20px;line-height:1.5}a{color:#315cba;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border:1px solid #cbd6e3;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f4f8;padding:18px;font:13px/1.6 monospace}p{overflow-wrap:anywhere}.cover{border-bottom:3px solid #315cba;padding-bottom:24px}.cover>p:first-child{font:14px system-ui;color:#315cba}.scope,.source{font:13px/1.7 system-ui;color:#53657b}.contents{padding:24px 0;border-bottom:1px solid #d4deea}.contents ol{padding-left:24px}.module{margin:40px 0}.module>h2{border-bottom:1px solid #d4deea;padding-bottom:14px}article{margin:28px 0;scroll-margin-top:20px}.attachment{border-left:3px solid #315cba;padding:12px 20px;background:#f3f6fb;font:14px/1.7 system-ui}.attachment p{margin:4px 0}.callout{background:#fff5e4;color:#82520c;padding:6px 10px;font:13px/1.6 system-ui}.review{font:13px/1.7 system-ui;background:#fff8ec;padding:18px 22px;margin:24px 0}.review h2{font:600 17px system-ui}.review li{margin:8px 0;overflow-wrap:anywhere}.empty{text-align:center;padding:60px 0;color:#53657b}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media(max-width:600px){main{padding:28px 22px}h1{font-size:27px}}@page{size:A4;margin:18mm}@media print{main{max-width:none;padding:0}body{font-size:11pt}h1{font-size:25pt}h2{font-size:18pt}h3{font-size:14pt}h1,h2,h3{break-after:avoid}img,table,.attachment{break-inside:avoid}.cover{break-after:page}.module{break-before:page}.contents a{text-decoration:none;color:inherit}.review{background:none;border:1px solid #d4deea}a{color:inherit}.scope{font-size:9pt}}
"""


def document(title, content):
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>' + esc(title) + '</title><style>' + DOC_STYLE + '</style></head><body><main>' + content + '</main></body></html>'


def demo_bytes():
    manifest = '''<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" identifier="demo"><metadata><title>Design Research Methods · Fall Course</title></metadata><organizations><organization identifier="o"><item identifier="root"><title>Course</title><item identifier="m1"><title>Before you begin</title><item identifier="a" identifierref="r1"><title>Course overview and learning goals</title></item><item identifier="b" identifierref="r2"><title>Research ethics and interview preparation</title></item></item><item identifier="m2"><title>Week 1: Observe real tasks</title><item identifier="c" identifierref="r3"><title>Observation exercise</title></item><item identifier="d" identifierref="r4"><title>Interview worksheet</title></item><item identifier="e" identifierref="r5"><title>Further reading</title></item></item><item identifier="m3"><title>Week 2: Organize evidence</title><item identifier="f" identifierref="r6"><title>From notes to findings</title></item></item></item></organization></organizations><resources><resource identifier="r1" type="webcontent" href="wiki_content/intro.html"/><resource identifier="r2" type="webcontent" href="wiki_content/ethics.html"/><resource identifier="r3" type="webcontent" href="wiki_content/exercise.html"/><resource identifier="r4" type="webcontent" href="web_resources/interview.csv"/><resource identifier="r5" type="imswl_xmlv1p1" href="links/reading.xml"/><resource identifier="r6" type="webcontent" href="wiki_content/evidence.html"/></resources></manifest>'''
    files = {
        'imsmanifest.xml': manifest,
        'wiki_content/intro.html': '<h2>Study a real workflow</h2><p>Practice observation, interviewing, and organizing evidence. Follow a participant and record how they complete a task.</p><h3>Learning goals</h3><ul><li>Describe a specific user, context, and task.</li><li>Distinguish observation from interpretation.</li><li>Choose the next step using evidence.</li></ul><table><tr><th>Assessment</th><th>Weight</th></tr><tr><td>Observation notes</td><td>40%</td></tr><tr><td>Research report</td><td>60%</td></tr></table>',
        'wiki_content/ethics.html': '<p>Explain the purpose of the interview and obtain consent. Remove names, contact details, and unnecessary identifiers before sharing notes.</p><blockquote>Record what the participant did before discussing why.</blockquote><p>Use the <a href="../web_resources/interview.csv">interview worksheet</a> to organize facts.</p>',
        'wiki_content/exercise.html': '<h3>Exercise: A real handover</h3><p>Observe someone preparing materials for another person. Record how they find, order, check, and revise them.</p><ol><li>Identify the recipient.</li><li>Record each manual adjustment.</li><li>Ask the participant to explain their final check.</li></ol><p>This image is intentionally missing to demonstrate issue reporting:</p><img src="../web_resources/missing-photo.png" alt="Observation workflow diagram">',
        'web_resources/interview.csv': 'Time,Observed action,Quote,Question to verify\n09:10,Organizing attachments,I do not know which is the final version,Version source\n',
        'links/reading.xml': '<webLink xmlns="http://www.imsglobal.org/xsd/imswl_v1p1"><title>Further reading</title><url href="https://www.imsglobal.org/"/></webLink>',
        'wiki_content/evidence.html': '<p>Turn observations into a statement that can be checked:</p><pre>Participant → Task → Obstacle → Current workaround → Evidence</pre><h3>Before submission</h3><ul><li>Trace each finding back to a record.</li><li>Label assumptions.</li><li>Describe evidence that could disprove the finding.</li></ul>',
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return out.getvalue()


def add_session(course):
    token = secrets.token_urlsafe(24)
    with LOCK:
        now = time.time()
        for key, (created, _) in list(SESSIONS.items()):
            if now - created > 7200:
                SESSIONS.pop(key, None)
        while len(SESSIONS) >= 3:
            SESSIONS.pop(next(iter(SESSIONS)))
        SESSIONS[token] = (now, course)
    return token


def get_session(token):
    with LOCK:
        entry = SESSIONS.get(token)
        if not entry or time.time() - entry[0] > 7200:
            SESSIONS.pop(token, None)
            raise CourseError('This course session has ended. Reimport the course package.')
        return entry[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log course filenames or contents.

    def allowed_request(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        return host in hosts and (not origin or origin in {'http://' + h for h in hosts})

    def send(self, data, mime='application/json; charset=utf-8', status=200, filename=None, document_page=False):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'" if document_page else "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(filename))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.allowed_request():
            return self.send({'error': 'Only local access is allowed.'}, status=403)
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        try:
            if parts.path in {'/', '/app.js', '/transport.js', '/style.css', '/favicon.svg'}:
                name = 'index.html' if parts.path == '/' else parts.path[1:]
                return self.send((ROOT / 'static' / name).read_bytes(), mimetypes.guess_type(name)[0] or 'text/plain')
            if parts.path in {'/api/document', '/api/archive'}:
                course = get_session(query.get('token', [''])[0])
                view = query.get('view', [''])[0]
                if view not in course.views:
                    raise CourseError('This preview has expired. Generate it again.')
                if parts.path == '/api/archive':
                    return self.send(course.export(course.views[view]['payload']), 'application/zip', filename='CoursePack-archive.zip')
                return self.send(course.views[view]['html'], 'text/html; charset=utf-8', document_page=True)
            if parts.path.startswith('/api/file/'):
                course = get_session(parts.path.split('/')[-1])
                path = query.get('path', [''])[0]
                if path not in course.files or PurePosixPath(path).suffix.lower() not in SAFE_EXT:
                    return self.send({'error': 'This attachment is unavailable.'}, status=404)
                suffix = PurePosixPath(path).suffix.lower()
                inline = suffix in IMAGE_EXT or suffix == '.pdf'
                return self.send(course.files[path], mimetypes.guess_type(path)[0] or 'application/octet-stream',
                                 filename=None if inline else PurePosixPath(path).name, document_page=True)
            return self.send({'error': 'Page not found.'}, status=404)
        except CourseError as exc:
            self.send({'error': str(exc)}, status=400)

    def do_POST(self):
        if not self.allowed_request():
            return self.send({'error': 'Only local access is allowed.'}, status=403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > MAX_UPLOAD:
                raise CourseError('This file exceeds 50 MB. Export a smaller package.')
            data = self.rfile.read(length)
            path = urlsplit(self.path).path
            if path in {'/api/import', '/api/demo'}:
                course = Course(demo_bytes() if path == '/api/demo' else data)
                token = add_session(course)
                return self.send(course.public(token))
            payload = json.loads(data or b'{}')
            if not isinstance(payload, dict):
                raise CourseError('Invalid request format.')
            token = payload.get('token', '')
            course = get_session(token)
            if path == '/api/reset':
                with LOCK:
                    SESSIONS.pop(token, None)
                return self.send({'ok': True})
            if path == '/api/render':
                rendered = course.render(payload, token)
                view = secrets.token_urlsafe(12)
                with LOCK:
                    while len(course.views) >= 6:
                        course.views.pop(next(iter(course.views)))
                    course.views[view] = {'html': rendered['html'], 'payload': payload}
                return self.send({'url': '/api/document?token=' + token + '&view=' + view,
                                  'archiveUrl': '/api/archive?token=' + token + '&view=' + view,
                                  'notices': rendered['notices'], 'count': rendered['count'],
                                  'excluded': rendered['excluded']})
            if path == '/api/export':
                return self.send(course.export(payload), 'application/zip', filename='CoursePack-archive.zip')
            self.send({'error': 'Unknown request.'}, status=404)
        except (CourseError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self.send({'error': str(exc) if isinstance(exc, CourseError) else 'Invalid request format. Try again.'}, status=400)
        except Exception:
            self.send({'error': 'Processing failed. Check the package format or try a smaller export.'}, status=500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'CoursePack: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        SESSIONS.clear()


if __name__ == '__main__':
    main()
