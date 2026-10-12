import { loadPyodide } from './runtime/pyodide.mjs';
let runtime;
let initialization;
async function initialize() {
  if (!initialization) initialization = (async () => {
    self.postMessage({ stage: 'Loading processing tools (about 13 MB). Course files are not uploaded…' });
    runtime = await loadPyodide({ indexURL: new URL('./runtime/', import.meta.url).href });
    const response = await fetch(new URL('./engine.py', import.meta.url));
    if (!response.ok) throw new Error('The processing engine could not be downloaded. Check your connection and try again.');
    runtime.FS.writeFile('/home/pyodide/engine.py', await response.text());
    await runtime.runPythonAsync(`
import engine, json, secrets
from js import input_bytes, input_payload
browser_course = None
browser_token = None

def browser_call(operation):
    global browser_course, browser_token
    payload = json.loads(str(input_payload))
    if operation in ('/api/demo', '/api/import'):
        data = engine.demo_bytes() if operation == '/api/demo' else bytes(input_bytes.to_py())
        next_course = engine.Course(data)
        browser_course = next_course
        browser_token = secrets.token_hex(12)
        return json.dumps(next_course.public(browser_token), ensure_ascii=False)
    if operation == '/api/reset':
        if payload.get('token') == browser_token:
            browser_course = None
            browser_token = None
        return '{}'
    if browser_course is None or payload.get('token') != browser_token:
        raise engine.CourseError('The course was cleared. Import it again.')
    if operation == '/api/render':
        result = browser_course.render(payload, exporting=True)
        assets = [(path, browser_course.files[path]) for path in sorted(result.pop('used'))]
        return (json.dumps(result, ensure_ascii=False), assets)
    if operation == '/api/export':
        return browser_course.export(payload)
    raise engine.CourseError('Unknown operation.')
`);
  })().catch(error => { initialization = null; throw error; });
  await initialization;
}
// Serialize mutations and rendering so responses always belong to their request.
let queue = Promise.resolve();
self.onmessage = event => {
  const { id, operation, payload, bytes } = event.data;
  queue = queue.then(async () => {
    try {
      // Declare bridge inputs before the first Python import from js.
      self.input_bytes = new Uint8Array(bytes || 0);
      self.input_payload = JSON.stringify(payload || {});
      await initialize();
      runtime.globals.set('input_bytes', self.input_bytes);
      runtime.globals.set('input_payload', self.input_payload);
      runtime.globals.set('operation', operation);
      const result = runtime.runPython('browser_call(operation)');
      if (operation === '/api/export') {
        const data = result.toJs(); result.destroy();
        const copy = new Uint8Array(data).slice();
        self.postMessage({ id, bytes: copy.buffer }, [copy.buffer]);
      } else if (operation === '/api/render') {
        const parts = result.toJs(); result.destroy();
        const data = JSON.parse(parts[0]);
        const assets = Array.from(parts[1], ([path, value]) => ({ path, bytes: new Uint8Array(value).slice().buffer }));
        self.postMessage({ id, data, assets }, assets.map(a => a.bytes));
      } else self.postMessage({ id, data: JSON.parse(result) });
    } catch (error) {
      const text = String(error.message || error);
      const known = text.match(/CourseError: ([^\n]+)/);
      self.postMessage({ id, error: known ? known[1] : 'Browser processing failed. Try again, or download the source and use the local version.', detail: known ? undefined : text.slice(-800) });
    } finally { self.input_bytes = null; self.input_payload = null; if (runtime) { runtime.globals.set('input_bytes', null); runtime.globals.set('input_payload', null); } }
  });
};
