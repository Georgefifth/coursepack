'use strict';
const $ = (id) => document.getElementById(id);
let course = null;
let groups = [];
let selected = new Set();
let originalGroups = [];
let notices = [];
let activeItem = null;
let currentPreview = null;
let renderTimer = null;
let renderRevision = 0;
let drag = null;
let importBusy = false;
let messageTimer;
let previewKey = '';
let archiveURL = null;
let previewHTML = '';
let lastDownloadURL = null;
let exportBusy = false;
let scrollAnchor = null;
let collapsed = new Set();
let draftWarning = false;
const DRAFT_KEY = 'coursepack-arrangement-v1';
if (CourseTransport.browserMode) {
  $('privacyNote').textContent = '支持带课程清单的 Canvas .imscc / .zip，最大 50 MB。文件在浏览器内处理，不上传，不连接学校账号。';
  $('engineStatus').textContent = '首次使用需下载约 13 MB 处理环境；之后由浏览器缓存。';
  $('sessionNote').textContent = '文件留在本标签页处理内存；清除课程或关闭标签页后释放。网站没有账户、云端数据库或学校连接。';
}
function saveDraft() {
  if (!course) return;
  try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ fingerprint: course.fingerprint, title: $('courseTitle').value, groups, selected: [...selected], collapsed: [...collapsed] })); }
  catch (_) { $('draftStatus').textContent = '浏览器未允许暂存进度；关闭或刷新前请下载档案。'; if (!draftWarning) { message('整理仍可继续，但此浏览器未允许暂存进度。'); draftWarning = true; } }
}
function restoreDraft() {
  try {
    const draft = JSON.parse(sessionStorage.getItem(DRAFT_KEY));
    if (!draft || draft.fingerprint !== course.fingerprint || typeof draft.title !== 'string' || !Array.isArray(draft.groups) || !Array.isArray(draft.selected)) return false;
    const known = new Set(course.items.map(i => i.id));
    const ids = draft.groups.flatMap(g => Array.isArray(g.items) ? g.items : []);
    if (ids.length !== known.size || new Set(ids).size !== known.size || ids.some(id => !known.has(id)) || draft.selected.some(id => !known.has(id))) return false;
    if (draft.groups.length !== originalGroups.length || draft.groups.some(g => typeof g.title !== 'string' || !originalGroups.some(o => o.id === g.id)) || new Set(draft.groups.map(g => g.id)).size !== originalGroups.length) return false;
    groups = draft.groups; selected = new Set(draft.selected); collapsed = new Set(draft.collapsed || []); $('courseTitle').value = draft.title.slice(0, 200); return true;
  } catch (_) { return false; }
}
function matches(id) {
  const item = course.byId[id];
  const query = $('materialSearch').value.trim().toLocaleLowerCase();
  return (!query || (item.title + ' ' + item.source).toLocaleLowerCase().includes(query)) && (!$('issuesOnly').checked || notices.some(n => n.item === id));
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function message(text, error = false) {
  clearTimeout(messageTimer);
  $('message').textContent = text;
  $('message').className = 'message' + (error ? ' error' : '');
  $('message').setAttribute('role', error ? 'alert' : 'status');
  $('message').hidden = false;
  messageTimer = setTimeout(() => { $('message').hidden = true; }, error ? 14000 : 6000);
}
const request = (...args) => CourseTransport.request(...args);
function snapshot() {
  return { token: course.token, title: $('courseTitle').value, groups: groups.map(g => ({ title: g.title, items: g.items.filter(id => selected.has(id)) })) };
}
function setImportBusy(value) {
  importBusy = value;
  ['importButton', 'demoButton', 'replaceButton', 'fileInput'].forEach(id => { $(id).disabled = value; });
  $('importButton').textContent = value ? '正在读取…' : '导入课程包';
}
async function importCourse(file) {
  if (importBusy) return;
  if (file && file.size > 50 * 1024 * 1024) return message('文件超过 50 MB。请导出更小的课程包。', true);
  if (file && !/\.(imscc|zip)$/i.test(file.name)) return message('请选择 Canvas 导出的 .imscc 或 .zip 文件。', true);
  setImportBusy(true);
  const importStarted = performance.now();
  try {
    const response = await request(file ? '/api/import' : '/api/demo', file || {}, !!file);
    const next = await response.json();
    if (course) request('/api/reset', { token: course.token }).catch(() => {});
    clearTimeout(renderTimer);
    renderRevision++;
    if (lastDownloadURL) URL.revokeObjectURL(lastDownloadURL); lastDownloadURL = null; $('saveArchiveLink').hidden = true;
    course = next;
    course.byId = Object.fromEntries(next.items.map(item => [item.id, item]));
    originalGroups = structuredClone(next.groups);
    groups = structuredClone(next.groups);
    selected = new Set(next.items.map(item => item.id));
    activeItem = null;
    notices = [];
    currentPreview = null; previewKey = ''; archiveURL = null; collapsed.clear();
    $('materialSearch').value = ''; $('issuesOnly').checked = false;
    $('courseTitle').value = next.title;
    const restored = restoreDraft();
    $('sourceLabel').textContent = file ? file.name : '示例课程 · 合成材料，含故意设置的缺项';
    $('welcome').hidden = true;
    $('workbench').hidden = false;
    showTab('preview');
    drawOutline();
    await refreshPreview();
    $('sourceLabel').dataset.importMs = (performance.now() - importStarted).toFixed(1);
    saveDraft();
    message(restored ? '已恢复本标签页的名称、顺序和材料选择。' : file ? '课程已导入。选择内容后，预览和导出会使用同一份目录。' : '示例已导入。可试试取消材料、调整顺序和查看待确认事项。');
  } catch (error) { message(error.message, true); }
  finally { setImportBusy(false); $('fileInput').value = ''; }
}
function moveButton(label, direction, onClick, disabled) {
  const button = el('button', '', direction < 0 ? '↑' : '↓');
  button.setAttribute('aria-label', label);
  button.title = label;
  button.disabled = disabled;
  button.addEventListener('click', onClick);
  return button;
}
function moveModule(index, direction) {
  const target = index + direction;
  if (target < 0 || target >= groups.length) return;
  [groups[index], groups[target]] = [groups[target], groups[index]];
  changed();
}
function moveItem(group, index, direction) {
  const target = index + direction;
  if (target < 0 || target >= group.items.length) return;
  [group.items[index], group.items[target]] = [group.items[target], group.items[index]];
  changed();
}
function changed() { saveDraft(); drawOutline(); schedulePreview(); }
function drawOutline() {
  const focus = document.activeElement && document.activeElement.dataset.focus;
  const root = $('moduleList');
  const scroll = root.parentElement.scrollTop;
  root.replaceChildren();
  const problems = new Set(notices.map(n => n.item));
  const filtering = !!$('materialSearch').value.trim() || $('issuesOnly').checked;
  let visible = 0;
  groups.forEach((g, gi) => {
    const matching = g.items.filter(matches);
    visible += matching.length;
    if (filtering && !matching.length) return;
    const block = el('section', 'module-block');
    block.dataset.module = g.id;
    const heading = el('div', 'module-heading');
    heading.draggable = true;
    heading.dataset.drag = 'module';
    heading.dataset.id = g.id;
    const check = el('input'); check.type = 'checkbox';
    check.setAttribute('aria-label', '选择模块：' + g.title);
    check.dataset.focus = 'module-' + g.id;
    check.checked = matching.length > 0 && matching.every(id => selected.has(id));
    check.indeterminate = !check.checked && matching.some(id => selected.has(id));
    check.addEventListener('change', () => { matching.forEach(id => check.checked ? selected.add(id) : selected.delete(id)); changed(); });
    const collapse = el('button', 'collapse-button', collapsed.has(g.id) && !filtering ? '›' : '⌄');
    collapse.setAttribute('aria-label', '展开或收起模块：' + g.title);
    collapse.setAttribute('aria-expanded', !collapsed.has(g.id) || filtering);
    collapse.dataset.focus = 'collapse-' + g.id;
    collapse.addEventListener('click', () => { collapsed.has(g.id) ? collapsed.delete(g.id) : collapsed.add(g.id); saveDraft(); drawOutline(); });
    const title = el('input', 'module-title'); title.value = g.title; title.maxLength = 200;
    title.setAttribute('aria-label', '模块名称：' + g.title); title.dataset.focus = 'title-' + g.id;
    title.title = '直接修改交付模块名称，回车保存';
    title.addEventListener('input', () => { g.title = title.value.slice(0, 200); saveDraft(); schedulePreview(); });
    title.addEventListener('change', () => { g.title = title.value.trim().slice(0, 200) || '课程模块'; title.value = g.title; saveDraft(); schedulePreview(); });
    title.addEventListener('keydown', event => { if (event.key === 'Enter') title.blur(); });
    title.draggable = false;
    const actions = el('div', 'move-actions');
    const up = moveButton('上移模块：' + g.title, -1, () => moveModule(gi, -1), gi === 0); up.dataset.focus = 'mg-up-' + g.id;
    const down = moveButton('下移模块：' + g.title, 1, () => moveModule(gi, 1), gi === groups.length - 1); down.dataset.focus = 'mg-down-' + g.id;
    actions.append(up, down); heading.append(collapse, check, title, actions); block.append(heading);
    g.items.forEach((id, ii) => {
      if (!matches(id) || (collapsed.has(g.id) && !filtering)) return;
      const item = course.byId[id];
      const row = el('div', 'item-row' + (!selected.has(id) ? ' is-excluded' : '') + (activeItem === id ? ' selected-preview' : ''));
      row.draggable = true; row.dataset.drag = 'item'; row.dataset.id = id; row.dataset.group = g.id;
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(id);
      checkbox.setAttribute('aria-label', '选入交付：' + item.title); checkbox.dataset.focus = 'item-' + id;
      checkbox.addEventListener('change', () => { checkbox.checked ? selected.add(id) : selected.delete(id); changed(); });
      const open = el('button', 'item-open'); open.setAttribute('aria-label', '预览：' + item.title); open.dataset.focus = 'open-' + id;
      open.append(el('strong', '', item.title));
      const meta = el('span', 'item-meta', item.type);
      if (problems.has(id)) { meta.append(el('i', 'item-issue')); meta.append(document.createTextNode('需确认')); }
      open.append(meta); open.addEventListener('click', () => focusItem(id));
      const moves = el('div', 'move-actions');
      const itemUp = moveButton('上移材料：' + item.title, -1, () => moveItem(g, ii, -1), ii === 0); itemUp.dataset.focus = 'up-' + id;
      const itemDown = moveButton('下移材料：' + item.title, 1, () => moveItem(g, ii, 1), ii === g.items.length - 1); itemDown.dataset.focus = 'down-' + id;
      moves.append(itemUp, itemDown); row.append(checkbox, open, moves); block.append(row);
    });
    root.append(block);
  });
  if (!visible) root.append(el('p', 'no-matches', '没有匹配的材料。可修改关键词或取消筛选。'));
  $('filterCount').textContent = filtering ? visible + ' 项匹配（不改变交付选择）' : '';
  $('selectVisibleButton').hidden = !filtering || !visible;
  $('selectionCount').textContent = '已选 ' + selected.size + ' / ' + course.items.length + ' 项材料';
  $('selectAllButton').textContent = selected.size === course.items.length ? '全不选' : '全选';
  $('exportButton').disabled = selected.size === 0 || exportBusy;
  $('printButton').disabled = selected.size === 0;
  root.parentElement.scrollTop = scroll;
  if (focus) { const target = Array.from(root.querySelectorAll('[data-focus]')).find(n => n.dataset.focus === focus); if (target) target.focus({ preventScroll: true }); }
}
function schedulePreview() {
  saveDraft();
  renderRevision++;
  $('previewStatus').textContent = '正在更新…';
  clearTimeout(renderTimer);
  renderTimer = setTimeout(refreshPreview, 250);
}
async function refreshPreview() {
  if (!course) return null;
  clearTimeout(renderTimer);
  const payload = snapshot();
  const key = JSON.stringify(payload);
  if (key === previewKey && currentPreview) { $('previewStatus').textContent = '与交付目录同步'; return currentPreview; }
  const revision = ++renderRevision;
  const token = course.token;
  $('previewStatus').textContent = '正在生成预览…';
  try {
    const started = performance.now();
    const response = await request('/api/render', payload);
    const result = await response.json();
    if (revision !== renderRevision || !course || course.token !== token) return null;
    const doc = $('previewFrame').contentDocument;
    const view = $('previewFrame').contentWindow;
    const first = doc && [...doc.querySelectorAll('article')].find(n => n.getBoundingClientRect().bottom > 0);
    scrollAnchor = first ? { id: first.id, offset: first.getBoundingClientRect().top } : { y: view ? view.scrollY : 0 };
    currentPreview = result.url; previewKey = key; archiveURL = result.archiveUrl;
    const issuesChanged = JSON.stringify(notices) !== JSON.stringify(result.notices);
    notices = result.notices;
    $('issueCount').textContent = notices.length;
    if (CourseTransport.browserMode) { previewHTML = result.html; $('previewFrame').srcdoc = result.html; }
    else $('previewFrame').src = result.url;
    $('previewStatus').textContent = '与交付目录同步';
    $('previewStatus').dataset.renderMs = (performance.now() - started).toFixed(1);
    if (issuesChanged) drawOutline();
    drawIssues();
    return result.url;
  } catch (error) { if (revision === renderRevision) { $('previewStatus').textContent = '预览未更新'; message(error.message, true); } return null; }
}
function drawIssues() {
  const area = $('issuesArea'); area.replaceChildren();
  area.append(el('h2', '', '交付前需确认'));
  area.append(el('p', 'issues-intro', '这里只检查选入材料在导出包中的引用。外部资源、缺失文件和不支持的内容需要你确认；文件存在并不代表原课程完整。'));
  if (!notices.length) area.append(el('p', 'no-issues', '当前选入的材料没有发现引用问题。交付前仍请检查内容是否符合你的要求。'));
  notices.forEach(n => {
    const row = el('div', 'issue-row');
    row.append(el('span', 'issue-tag', ({ missing: '文件缺失', external: '需要联网', unsupported: '未转换' })[n.kind] || '需确认'));
    const detail = el('div'); detail.append(el('h3', '', n.title), el('p', '', n.message));
    const button = el('button', 'text-button', '查看对应材料'); button.addEventListener('click', () => focusItem(n.item));
    detail.append(button); row.append(detail); area.append(row);
  });
}
function showTab(name) {
  const preview = name === 'preview';
  $('previewTab').setAttribute('aria-selected', preview);
  $('issuesTab').setAttribute('aria-selected', !preview);
  $('previewArea').hidden = !preview; $('issuesArea').hidden = preview;
}
function focusItem(id) {
  if (!selected.has(id)) return message('这项材料未选入交付。勾选后即可在预览中查看。');
  activeItem = id; showTab('preview'); drawOutline();
  const target = $('previewFrame').contentDocument && $('previewFrame').contentDocument.getElementById(id);
  if (target) target.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
}
$('previewFrame').addEventListener('load', () => {
  if (scrollAnchor) {
    const view = $('previewFrame').contentWindow;
    const target = scrollAnchor.id && $('previewFrame').contentDocument.getElementById(scrollAnchor.id);
    view.scrollTo(0, target ? view.scrollY + target.getBoundingClientRect().top - scrollAnchor.offset : scrollAnchor.y || 0);
    scrollAnchor = null;
  }
  CourseTransport.revokePrevious();
});
$('materialSearch').addEventListener('input', drawOutline);
$('issuesOnly').addEventListener('change', drawOutline);
$('selectVisibleButton').addEventListener('click', () => { course.items.filter(i => matches(i.id)).forEach(i => selected.add(i.id)); changed(); });
$('importButton').addEventListener('click', () => $('fileInput').click());
$('replaceButton').addEventListener('click', () => $('fileInput').click());
$('demoButton').addEventListener('click', () => importCourse(null));
$('fileInput').addEventListener('change', () => { if ($('fileInput').files[0]) importCourse($('fileInput').files[0]); });
$('courseTitle').addEventListener('input', schedulePreview);
$('selectAllButton').addEventListener('click', () => { selected = selected.size === course.items.length ? new Set() : new Set(course.items.map(i => i.id)); changed(); });
$('resetOrderButton').addEventListener('click', () => { groups = structuredClone(originalGroups); changed(); message('已恢复原始目录和模块名称，保留当前材料选择。'); });
$('clearButton').addEventListener('click', async () => {
  const old = course;
  clearTimeout(renderTimer); renderRevision++; course = null;
  $('previewFrame').removeAttribute('src'); $('previewFrame').removeAttribute('srcdoc'); previewHTML = ''; currentPreview = null; previewKey = ''; archiveURL = null; scrollAnchor = null;
  if (lastDownloadURL) URL.revokeObjectURL(lastDownloadURL); lastDownloadURL = null; $('saveArchiveLink').hidden = true;
  try { sessionStorage.removeItem(DRAFT_KEY); } catch (_) {} $('welcome').hidden = false; $('workbench').hidden = true;
  groups = []; selected.clear(); notices = []; activeItem = null;
  if (old) { try { await request('/api/reset', { token: old.token }); if (CourseTransport.browserMode) CourseTransport.clear(); message('课程和本标签页的整理进度已清除。'); } catch (error) { message(error.message, true); } }
});
$('previewTab').addEventListener('click', () => showTab('preview'));
$('issuesTab').addEventListener('click', () => showTab('issues'));
['previewTab', 'issuesTab'].forEach(id => $(id).addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); const next = id === 'previewTab' ? 'issuesTab' : 'previewTab'; showTab(next === 'previewTab' ? 'preview' : 'issues'); $(next).focus(); }
}));
$('helpButton').addEventListener('click', () => $('helpDialog').showModal());
$('closeHelp').addEventListener('click', () => $('helpDialog').close());
$('exportButton').addEventListener('click', async () => {
  if (exportBusy) return;
  exportBusy = true;
  const button = $('exportButton'); button.disabled = true; button.textContent = '正在打包…';
  try {
    if (!await refreshPreview()) throw new Error('请先等待预览更新成功再导出。');
    const anchor = el('a');
    let downloadURL;
    if (CourseTransport.browserMode) { const response = await request('/api/export', snapshot()); downloadURL = URL.createObjectURL(await response.blob()); anchor.href = downloadURL; }
    else anchor.href = archiveURL;
    anchor.download = 'CoursePack-archive.zip';
    document.body.append(anchor); anchor.click(); anchor.remove();
    if (downloadURL) { if (lastDownloadURL) URL.revokeObjectURL(lastDownloadURL); lastDownloadURL = downloadURL; $('saveArchiveLink').href = downloadURL; $('saveArchiveLink').hidden = false; }
    message('已发起档案下载。解压后打开 index.html；原附件保留在 assets 文件夹。');
  } catch (error) { message(error.message, true); }
  finally { exportBusy = false; button.disabled = !course || selected.size === 0; button.textContent = '下载档案'; }
});
$('printButton').addEventListener('click', async () => {
  const popup = window.open('', '_blank');
  if (!popup) return message('浏览器拦截了打印窗口。请允许此页面打开弹窗后重试。', true);
  const button = $('printButton'); button.disabled = true;
  clearTimeout(renderTimer);
  const url = await refreshPreview();
  if (url) {
    popup.onload = () => { popup.focus(); popup.print(); };
    if (CourseTransport.browserMode) { popup.document.open(); popup.document.write(previewHTML); popup.document.close(); }
    else popup.location.href = url;
    message('在打印窗口选择「另存为 PDF」。正文包含附件索引，原附件请使用「下载档案」保存。');
  } else popup.close();
  button.disabled = selected.size === 0;
});
const list = $('moduleList');
list.addEventListener('dragstart', event => {
  const row = event.target.closest('[data-drag]');
  if (!row) return;
  drag = { kind: row.dataset.drag, id: row.dataset.id, group: row.dataset.group };
  event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', drag.id); row.classList.add('dragging');
});
list.addEventListener('dragover', event => {
  const row = event.target.closest('[data-drag]');
  if (!drag || !row || row.dataset.drag !== drag.kind || (drag.kind === 'item' && row.dataset.group !== drag.group)) return;
  event.preventDefault(); event.dataTransfer.dropEffect = 'move';
  list.querySelectorAll('.drop-target').forEach(n => n.classList.remove('drop-target')); row.classList.add('drop-target');
});
list.addEventListener('drop', event => {
  const row = event.target.closest('[data-drag]');
  if (!drag || !row || row.dataset.drag !== drag.kind || (drag.kind === 'item' && row.dataset.group !== drag.group)) return;
  event.preventDefault();
  const array = drag.kind === 'module' ? groups : groups.find(g => g.id === drag.group).items;
  const from = drag.kind === 'module' ? array.findIndex(g => g.id === drag.id) : array.indexOf(drag.id);
  const to = drag.kind === 'module' ? array.findIndex(g => g.id === row.dataset.id) : array.indexOf(row.dataset.id);
  if (from >= 0 && to >= 0) { const value = array.splice(from, 1)[0]; array.splice(to, 0, value); changed(); }
  drag = null;
});
list.addEventListener('dragend', () => { drag = null; list.querySelectorAll('.dragging,.drop-target').forEach(n => n.classList.remove('dragging', 'drop-target')); });
document.addEventListener('dragover', event => { if (!drag && Array.from(event.dataTransfer.types).includes('Files')) event.preventDefault(); });
document.addEventListener('drop', event => { if (!drag && event.dataTransfer.files.length) { event.preventDefault(); importCourse(event.dataTransfer.files[0]); } });
