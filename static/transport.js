'use strict';
window.CourseTransport = (() => {
  const browserMode = document.documentElement.dataset.engine === 'browser';
  let worker, sequence = 0;
  const pending = new Map();
  const urls = new Set();
  let previousPreviewURLs = [];
  function revokePrevious() { previousPreviewURLs.forEach(url => { URL.revokeObjectURL(url); urls.delete(url); }); previousPreviewURLs = []; }
  function makeURL(blob) { const url = URL.createObjectURL(blob); urls.add(url); return url; }
  function start() {
    if (worker) return;
    worker = new Worker(new URL('worker.mjs', document.baseURI), { type: 'module' });
    worker.onmessage = ({ data }) => {
      if (data.stage) { document.getElementById('engineStatus').textContent = data.stage; return; }
      const request = pending.get(data.id); if (!request) return;
      pending.delete(data.id);
      document.getElementById('engineStatus').textContent = '在此浏览器处理 · 文件不上传';
      if (data.error) { if (data.detail) console.error(data.detail); request.reject(new Error(data.error)); } else request.resolve(data);
    };
    worker.onerror = () => {
      for (const request of pending.values()) request.reject(new Error('处理环境加载失败，请检查网络后重试。'));
      pending.clear(); worker.terminate(); worker = null;
    };
  }
  async function request(path, body, raw = false) {
    if (!browserMode) {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': raw ? 'application/zip' : 'application/json' }, body: raw ? body : JSON.stringify(body || {}) });
      if (!response.ok) { let error = {}; try { error = await response.json(); } catch (_) {} throw new Error(error.error || '处理未完成，请重试。'); }
      return response;
    }
    start(); const id = ++sequence;
    const bytes = raw ? await body.arrayBuffer() : undefined;
    const result = await new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); worker.postMessage({ id, operation: path, payload: raw ? {} : body, bytes }, bytes ? [bytes] : []); });
    if (path === '/api/export') return { blob: async () => new Blob([result.bytes], { type: 'application/zip' }) };
    if (result.assets) {
      let html = result.data.html.replace("img-src 'self'", "img-src 'self' blob:").replaceAll('href="body.html#', 'href="#');
      const nextURLs = [];
      for (const asset of result.assets) {
        const extension = asset.path.split('.').pop().toLowerCase();
        const type = ({ png:'image/png', jpg:'image/jpeg', jpeg:'image/jpeg', gif:'image/gif', webp:'image/webp', avif:'image/avif', pdf:'application/pdf', txt:'text/plain', csv:'text/csv', xml:'application/xml' })[extension] || 'application/octet-stream';
        const url = makeURL(new Blob([asset.bytes], { type })); nextURLs.push(url);
        const encoded = asset.path.split('/').map(p => encodeURIComponent(p).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase())).join('/');
        html = html.replaceAll('assets/' + encoded, url);
      }
      // Old assets must remain live until the replacement iframe has loaded.
      previousPreviewURLs.push(...(window.CourseTransport.previewAssets || []));
      window.CourseTransport.previewAssets = nextURLs;
      result.data.html = html;
      result.data.url = 'about:blank';
    }
    return { json: async () => result.data };
  }
  function clear() { if (worker) worker.terminate(); worker = null; for (const request of pending.values()) request.reject(new Error('课程已清除。')); pending.clear(); urls.forEach(URL.revokeObjectURL); urls.clear(); previousPreviewURLs = []; }
  return { request, browserMode, clear, revokePrevious };
})();
