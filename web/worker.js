// Runs orchestra_review (the same Python package as the CLI) in Pyodide, off the page's main thread.
// Files arrive one at a time and are deleted from the in-memory file system once read, so memory stays flat
// even for hundreds of megabytes of logs. Nothing in here makes a network request except loading itself.

let web;
const WORK = '/tmp/orchestra-review-work';

const ready = (async () => {
  importScripts('pyodide/pyodide.js');
  const pyodide = await loadPyodide({ indexURL: new URL('pyodide/', self.location).href });
  const archive = await (await fetch('orchestra_review.zip')).arrayBuffer();
  pyodide.unpackArchive(archive, 'zip', { extractDir: '/lib/orchestra' });
  pyodide.runPython("import sys; sys.path.insert(0, '/lib/orchestra')");
  web = pyodide.pyimport('orchestra_review.web');
  self.FS = pyodide.FS;
})();

const extension = (name) => (name.match(/\.[a-z]+$/i) || [''])[0].toLowerCase();

self.onmessage = async ({ data }) => {
  try {
    await ready;
    if (data.type === 'boot') {
      self.postMessage({ type: 'ready' });
    } else if (data.type === 'start') {
      web.start();
      self.postMessage({ type: 'started' });
    } else if (data.type === 'file') {
      const path = `${WORK}/upload-${data.n}${extension(data.relative)}`;
      self.FS.writeFile(path, new Uint8Array(data.buffer));
      const kind = extension(data.relative) === '.zip' ? (web.add_zip(path), 'zip') : web.add_file(path, data.relative);
      self.postMessage({ type: 'added', n: data.n, kind });
    } else if (data.type === 'finish') {
      self.postMessage({ type: 'report', json: web.finish(Boolean(data.public)) });
    }
  } catch (error) {
    self.postMessage({ type: 'error', message: String((error && error.message) || error) });
  }
};
