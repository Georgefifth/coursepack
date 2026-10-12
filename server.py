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
        raise CourseError('课程 XML 含有不支持的声明。请重新导出标准课程包。')
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise CourseError('课程清单无法读取。请重新导出课程包。') from exc


def safe_path(value):
    if not value or '\\' in value or '\x00' in value or value.startswith('/'):
        raise CourseError('课程包含有不安全的文件路径。')
    parts = value.split('/')
    if '..' in parts or ':' in parts[0]:
        raise CourseError('课程包含有不安全的文件路径。')
    return posixpath.normpath(value)


def esc(value):
    return html.escape(str(value), quote=True)


class Course:
    def __init__(self, data: bytes):
        if len(data) > MAX_UPLOAD:
            raise CourseError('文件超过 50 MB。请导出更小的课程包。')
        self.files = {}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = z.infolist()
                if len(infos) > 3000 or sum(i.file_size for i in infos) > MAX_TOTAL:
                    raise CourseError('课程包解压后过大。请分批导出课程内容。')
                for i in infos:
                    name = safe_path(i.filename)
                    if i.is_dir():
                        continue
                    if name in self.files:
                        raise CourseError('课程包中有重复文件路径。请重新导出。')
                    if i.file_size > MAX_FILE or i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16):
                        raise CourseError('课程包含有过大的文件、加密文件或符号链接。')
                    self.files[name] = z.read(i)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise CourseError('无法读取压缩包。请选择 Canvas 导出的 .imscc 或 .zip 文件。') from exc
        manifests = [p for p in self.files if PurePosixPath(p).name == 'imsmanifest.xml']
        if len(manifests) != 1:
            raise CourseError('没有找到唯一的课程清单。首版支持 Canvas「设置 → 导出课程内容」生成的课程包；离线 HTML 包暂不支持。')
        self.manifest_path = manifests[0]
        self.base = posixpath.dirname(self.manifest_path)
        manifest = xml(self.files[self.manifest_path])
        self.title = next((''.join(x.itertext()).strip() for x in manifest.iter()
                           if tag(x) == 'title' and ''.join(x.itertext()).strip()), '未命名课程')
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
            self.items[rid] = {'id': rid, 'title': title or '未命名材料', 'path': path,
                               'href': href, 'type': kind or r.get('type', ''),
                               'indent': indent, 'files': r.get('files', [])}
            return rid

        def flatten(node, out, depth=0):
            for n in node:
                if tag(n) != 'item':
                    continue
                title = text_of(n, 'title', '未命名材料')
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
                                        'title': text_of(n, 'title', '课程模块'), 'items': ids})
                else:
                    loose.append(add(text_of(n, 'title', '课程材料'), n.get('identifierref', ''),
                                     kind='' if n.get('identifierref') else 'heading'))
            if loose:
                self.groups.append({'id': 'g' + str(len(self.groups) + 1), 'title': '课程材料', 'items': loose})

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
                        ids.append(add(text_of(item, 'title', '课程材料'), ref, href, kind))
                modules.append({'id': 'g' + str(len(modules) + 1),
                                'title': text_of(m, 'title', '课程模块'), 'items': ids})
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
                                "title": "未编入模块的材料", "items": loose})

        if not self.items:
            ids = [add(PurePosixPath(r['href']).stem, ref) for ref, r in resources.items() if r['href']]
            self.groups = [{'id': 'g1', 'title': '课程材料', 'items': ids}]
        if len(self.items) > 1000:
            raise CourseError('课程条目超过首版支持的 1000 项，请分批导出。')
        if not self.items:
            raise CourseError('课程包没有可整理的材料。请确认导出时选择了课程内容。')
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
            raise CourseError('交付目录格式有误，请重新整理。')
        seen = set()
        groups = []
        for g in raw_groups:
            if not isinstance(g, dict) or not isinstance(g.get('items'), list):
                raise CourseError('交付目录格式有误。')
            ids = []
            for iid in g['items']:
                if not isinstance(iid, str) or iid not in self.items or iid in seen:
                    raise CourseError('交付目录含有未知或重复的材料。')
                seen.add(iid)
                ids.append(iid)
            if ids:
                groups.append({'title': str(g.get('title', '课程模块'))[:200], 'items': ids})
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
                notice(iid, 'unsupported', '嵌入数据未保留，请补充独立文件。')
                return None
            parts = urlsplit(href)
            if parts.scheme.lower() in {'http', 'https'} or parts.netloc:
                notice(iid, 'external', '仍需联网访问：' + href[:250])
                return None if image else href
            if parts.scheme:
                notice(iid, 'unsupported', '不支持的链接已移除。')
                return None
            found = self.resolve(href, origin)
            if found:
                matches = [k for k, v in self.items.items() if v['path'] == found and k in included]
                if matches and PurePosixPath(found).suffix.lower() in {'.html', '.htm'} and not image:
                    target = matches[0] + ('-src-' + unquote(parts.fragment) if parts.fragment else '')
                    return ('body.html' if exporting else '') + '#' + target
                if image and PurePosixPath(found).suffix.lower() not in IMAGE_EXT:
                    notice(iid, 'unsupported', '图片格式未保留：' + href[:180])
                    return None
                url = asset(found)
                if url:
                    return url
                notice(iid, 'unsupported', '此链接指向未包含的网页或不支持的文件：' + href[:180])
            else:
                notice(iid, 'missing', '包内未找到引用文件：' + href[:180])
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
                    content = '<p class="source">课程分节标题</p>'
                elif not path:
                    href = item['href']
                    if href.startswith(('https://', 'http://')):
                        notice(iid, 'external', '此材料仍需联网访问：' + href[:250])
                        content = '<p class="callout">在线材料</p><p><a href="' + esc(href) + '">' + esc(href) + '</a></p>'
                        status = 'external'
                    else:
                        notice(iid, 'missing', '导出包没有包含此条目的文件。请回到原课程检查并补存。')
                        content = '<p class="callout">没有找到材料文件。此条目仅保留目录信息。</p>'
                        status = 'missing'
                elif suffix in {'.html', '.htm'}:
                    parser = CleanHTML(lambda href, image=False: link(href, path, iid, image),
                                       lambda message: notice(iid, 'unsupported', message), iid + '-src-')
                    parser.feed(self.files[path].decode('utf-8-sig', errors='replace'))
                    content = parser.result()
                elif suffix in {'.txt', '.csv'}:
                    content = '<pre>' + esc(self.files[path].decode('utf-8-sig', errors='replace')) + '</pre>'
                    url = asset(path)
                    content += '<p class="attachment"><a href="' + esc(url) + '">下载原文件</a></p>'
                elif suffix == '.xml' and any(x in kind for x in ('weblink', 'imswl', 'basiclti', 'external')):
                    try:
                        doc = xml(self.files[path])
                    except CourseError:
                        doc = ET.Element('unreadable')
                    href = next((n.get('href') or (n.text or '').strip() for n in doc.iter()
                                 if tag(n) in {'url', 'launch_url'}), '')
                    if href.startswith(('https://', 'http://')):
                        notice(iid, 'external', '此材料需要外部服务：' + href[:250])
                        content = '<p class="callout">外部服务材料</p><p><a href="' + esc(href) + '">' + esc(href) + '</a></p>'
                    else:
                        notice(iid, 'unsupported', '外部工具描述未能解析。原 XML 作为附件保留。')
                        content = '<p class="attachment"><a href="' + esc(asset(path)) + '">下载原描述文件</a></p>'
                    status = 'external'
                elif suffix in SAFE_EXT:
                    url = asset(path)
                    content = '<div class="attachment"><strong>' + esc(PurePosixPath(path).name) + '</strong><p>原文件单独交付，未并入可打印正文。</p><a href="' + esc(url) + '">打开 / 下载附件</a></div>'
                    status = 'attachment'
                    if suffix == '.xml':
                        notice(iid, 'unsupported', '测验或结构化材料作为原 XML 附件保留，首版不重建其内容。')
                else:
                    notice(iid, 'unsupported', '暂不支持此文件类型：' + (suffix or '无扩展名'))
                    content = '<p class="callout">此材料未能进入交付包，请另行保存。</p>'
                    status = 'unsupported'
                body.append('<article id="' + iid + '"><h3>' + esc(item['title']) + '</h3>' + content + '</article>')
                inventory.append({'id': iid, 'title': item['title'], 'module': g['title'],
                                  'source': path or item['href'], 'status': status})
            body.append('</section>')
            sections.append(''.join(body))
        summary = '<p class="scope">本档案包含 ' + str(len(included)) + ' 项材料；原目录中 ' + str(len(self.items) - len(included)) + ' 项未选入。附件单独保存；在线内容仍需联网。此报告仅检查已导入的课程包。</p>'
        toc = '<nav class="contents"><h2>交付目录</h2>' + ''.join('<h3>' + esc(g['title']) + '</h3><ol>' + ''.join('<li><a href="#' + iid + '">' + esc(self.items[iid]['title']) + '</a></li>' for iid in g['items']) + '</ol>' for g in groups) + '</nav>'
        warnings = ''
        if notices:
            warnings = '<section class="review"><h2>交付前需确认</h2><ul>' + ''.join('<li><strong>' + esc(n['title']) + '</strong>：' + esc(n['message']) + '</li>' for n in notices) + '</ul></section>'
        empty = '<p class="empty">尚未选入材料。请在左侧选择要交付的内容。</p>' if not included else ''
        output = document(title, '<header class="cover"><p>课程档案</p><h1>' + esc(title) + '</h1>' + summary + '</header>' + toc + warnings + empty + ''.join(sections))
        if len(output.encode('utf-8')) > 10 * 1024 * 1024:
            raise CourseError('选入的正文超过 10 MB。请减少本次交付的页面或文本材料。')
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
            return '分节'
        if suffix in {'.html', '.htm'}:
            return '页面'
        if suffix == '.pdf':
            return 'PDF 附件'
        if any(x in item['type'].lower() for x in ('weblink', 'imswl', 'external', 'basiclti')):
            return '在线材料'
        return '附件' if item['path'] else '待检查'

    def export(self, payload):
        rendered = self.render(payload, exporting=True)
        if not rendered['count']:
            raise CourseError('请至少选择一项材料再导出。')
        out = io.BytesIO()
        title, groups = self.snapshot(payload)
        index = '<h1>' + esc(title) + '</h1><p>课程档案已整理。<a href="body.html">阅读全部正文</a>；需要 PDF 时，在正文页面使用浏览器的打印功能。</p>'
        for g in groups:
            index += '<h2>' + esc(g['title']) + '</h2><ul>' + ''.join('<li><a href="body.html#' + iid + '">' + esc(self.items[iid]['title']) + '</a></li>' for iid in g['items']) + '</ul>'
        index += '<p>附件保持原格式，见正文中的附件链接。外部内容不会被自动下载。</p>'
        report = {'title': title, 'included': rendered['inventory'], 'excluded_count': rendered['excluded'],
                  'notices': rendered['notices'], 'attachments': sorted(rendered['used']),
                  'scope': '仅检查导入包；不能证明原课程完整或认证合格。'}
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
            self.on_unsupported('视频或音频未并入可打印正文；可用的原文件作为附件保留。')
            if url:
                self.out.append('<p class="attachment"><a href="' + esc(url) + '">打开媒体原文件</a>（未并入可打印正文）</p>')
            return
        if name == 'math':
            self.on_unsupported('数学标记已简化为文本，请核对公式或补充 PDF 附件。')
        if name in self.blocked:
            if name in {'svg', 'form', 'object', 'embed'}:
                self.on_unsupported('交互内容或嵌入图形未转换，请补充独立文件。')
                self.out.append('<p class="callout">此处的交互内容或图形未转换，请补充独立文件。</p>')
            if name == 'iframe':
                attrs = dict(attrs)
                url = self.resolver(attrs['src']) if attrs.get('src') else None
                self.out.append('<p class="callout">嵌入内容未纳入正文。' +
                                ('<a href="' + esc(url) + '" rel="noopener noreferrer">打开对应资源</a>' if url else '请检查外部资源。') + '</p>')
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
            elif name == 'img':
                self.out.append('<span class="callout">[图片未包含：' + esc(attrs.get('alt', '请补存')) + ']</span>')
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
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:#172b45;font:16px/1.75 Georgia,'Noto Serif CJK SC','Songti SC',serif}main{max-width:850px;margin:auto;padding:54px 56px}h1{font-size:34px;line-height:1.35;overflow-wrap:anywhere}h2{font-size:24px;line-height:1.4}h3{font-size:20px;line-height:1.5}a{color:#315cba;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border:1px solid #cbd6e3;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f4f8;padding:18px;font:13px/1.6 monospace}p{overflow-wrap:anywhere}.cover{border-bottom:3px solid #315cba;padding-bottom:24px}.cover>p:first-child{font:14px system-ui;color:#315cba}.scope,.source{font:13px/1.7 system-ui;color:#53657b}.contents{padding:24px 0;border-bottom:1px solid #d4deea}.contents ol{padding-left:24px}.module{margin:40px 0}.module>h2{border-bottom:1px solid #d4deea;padding-bottom:14px}article{margin:28px 0;scroll-margin-top:20px}.attachment{border-left:3px solid #315cba;padding:12px 20px;background:#f3f6fb;font:14px/1.7 system-ui}.attachment p{margin:4px 0}.callout{background:#fff5e4;color:#82520c;padding:6px 10px;font:13px/1.6 system-ui}.review{font:13px/1.7 system-ui;background:#fff8ec;padding:18px 22px;margin:24px 0}.review h2{font:600 17px system-ui}.review li{margin:8px 0;overflow-wrap:anywhere}.empty{text-align:center;padding:60px 0;color:#53657b}@media(max-width:600px){main{padding:28px 22px}h1{font-size:27px}}@page{size:A4;margin:18mm}@media print{main{max-width:none;padding:0}body{font-size:11pt}h1{font-size:25pt}h2{font-size:18pt}h3{font-size:14pt}h1,h2,h3{break-after:avoid}img,table,.attachment{break-inside:avoid}.cover{break-after:page}.module{break-before:page}.contents a{text-decoration:none;color:inherit}.review{background:none;border:1px solid #d4deea}a{color:inherit}.scope{font-size:9pt}}
"""


def document(title, content):
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>' + esc(title) + '</title><style>' + DOC_STYLE + '</style></head><body><main>' + content + '</main></body></html>'


def demo_bytes():
    manifest = '''<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" identifier="demo"><metadata><title>设计研究方法 · 秋季课程</title></metadata><organizations><organization identifier="o"><item identifier="root"><title>课程</title><item identifier="m1"><title>开始之前</title><item identifier="a" identifierref="r1"><title>课程说明与学习目标</title></item><item identifier="b" identifierref="r2"><title>研究伦理与访谈准备</title></item></item><item identifier="m2"><title>第一周：观察真实任务</title><item identifier="c" identifierref="r3"><title>观察记录练习</title></item><item identifier="d" identifierref="r4"><title>访谈记录表</title></item><item identifier="e" identifierref="r5"><title>延伸阅读</title></item></item><item identifier="m3"><title>第二周：整理证据</title><item identifier="f" identifierref="r6"><title>从记录到发现</title></item></item></item></organization></organizations><resources><resource identifier="r1" type="webcontent" href="wiki_content/intro.html"/><resource identifier="r2" type="webcontent" href="wiki_content/ethics.html"/><resource identifier="r3" type="webcontent" href="wiki_content/exercise.html"/><resource identifier="r4" type="webcontent" href="web_resources/interview.csv"/><resource identifier="r5" type="imswl_xmlv1p1" href="links/reading.xml"/><resource identifier="r6" type="webcontent" href="wiki_content/evidence.html"/></resources></manifest>'''
    files = {
        'imsmanifest.xml': manifest,
        'wiki_content/intro.html': '<h2>把问题放回真实的工作中</h2><p>这是一门围绕观察、访谈与证据整理的实践课程。你将跟随一位参与者，记录他们完成任务的过程。</p><h3>完成课程后，你能够</h3><ul><li>描述具体用户、场景和任务。</li><li>区分观察事实与个人解释。</li><li>用证据选择下一步，而不是凭直觉增加功能。</li></ul><table><tr><th>考核</th><th>比例</th></tr><tr><td>观察记录</td><td>40%</td></tr><tr><td>研究报告</td><td>60%</td></tr></table>',
        'wiki_content/ethics.html': '<p>访谈前说明目的，并获得参与者同意。对外分享记录时移除姓名、联系方式和不必要的身份信息。</p><blockquote>记录参与者做了什么，再讨论为什么。</blockquote><p>使用<a href="../web_resources/interview.csv">访谈记录表</a>整理事实。</p>',
        'wiki_content/exercise.html': '<h3>课堂练习：一次真实交付</h3><p>观察参与者整理一份要交给别人的材料。记录他们查找、排序、检查和修改的动作。</p><ol><li>确定材料接收者。</li><li>记录每次手工调整。</li><li>让参与者解释交付前最后一次检查。</li></ol><p>以下图片故意未包含，用于演示缺项提示：</p><img src="../web_resources/missing-photo.png" alt="观察流程示意图">',
        'web_resources/interview.csv': '时间,观察到的动作,原话,待确认的问题\n09:10,整理附件,我不知道哪个是最终版,版本来源\n',
        'links/reading.xml': '<webLink xmlns="http://www.imsglobal.org/xsd/imswl_v1p1"><title>延伸阅读</title><url href="https://www.imsglobal.org/"/></webLink>',
        'wiki_content/evidence.html': '<p>把观察整理为一条可检查的陈述：</p><pre>参与者 → 任务 → 阻碍 → 当前办法 → 证据</pre><h3>提交前检查</h3><ul><li>每项发现都能追溯到记录。</li><li>明确标记推测。</li><li>写出可能推翻结论的证据。</li></ul>',
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
            raise CourseError('课程会话已结束。请重新导入课程包。')
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
            return self.send({'error': '只允许本机访问。'}, status=403)
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        try:
            if parts.path in {'/', '/app.js', '/transport.js', '/style.css'}:
                name = 'index.html' if parts.path == '/' else parts.path[1:]
                return self.send((ROOT / 'static' / name).read_bytes(), mimetypes.guess_type(name)[0] or 'text/plain')
            if parts.path in {'/api/document', '/api/archive'}:
                course = get_session(query.get('token', [''])[0])
                view = query.get('view', [''])[0]
                if view not in course.views:
                    raise CourseError('预览已过期，请重新生成。')
                if parts.path == '/api/archive':
                    return self.send(course.export(course.views[view]['payload']), 'application/zip', filename='CoursePack-archive.zip')
                return self.send(course.views[view]['html'], 'text/html; charset=utf-8', document_page=True)
            if parts.path.startswith('/api/file/'):
                course = get_session(parts.path.split('/')[-1])
                path = query.get('path', [''])[0]
                if path not in course.files or PurePosixPath(path).suffix.lower() not in SAFE_EXT:
                    return self.send({'error': '附件不可用。'}, status=404)
                suffix = PurePosixPath(path).suffix.lower()
                inline = suffix in IMAGE_EXT or suffix == '.pdf'
                return self.send(course.files[path], mimetypes.guess_type(path)[0] or 'application/octet-stream',
                                 filename=None if inline else PurePosixPath(path).name, document_page=True)
            return self.send({'error': '页面不存在。'}, status=404)
        except CourseError as exc:
            self.send({'error': str(exc)}, status=400)

    def do_POST(self):
        if not self.allowed_request():
            return self.send({'error': '只允许本机访问。'}, status=403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > MAX_UPLOAD:
                raise CourseError('文件超过 50 MB，请导出更小的课程包。')
            data = self.rfile.read(length)
            path = urlsplit(self.path).path
            if path in {'/api/import', '/api/demo'}:
                course = Course(demo_bytes() if path == '/api/demo' else data)
                token = add_session(course)
                return self.send(course.public(token))
            payload = json.loads(data or b'{}')
            if not isinstance(payload, dict):
                raise CourseError('请求格式有误。')
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
            self.send({'error': '请求不存在。'}, status=404)
        except (CourseError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self.send({'error': str(exc) if isinstance(exc, CourseError) else '请求格式有误，请重试。'}, status=400)
        except Exception:
            self.send({'error': '处理未完成。请确认课程包格式，或尝试更小的导出包。'}, status=500)


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
