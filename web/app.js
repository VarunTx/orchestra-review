// Page logic: collect the dropped files, stream them to the worker, render the report.
// The page never sends log content anywhere. The only request it makes beyond loading itself is
// POST /ping?e=report once a report finishes, which carries no data and lets the server count reports.

const WANTED = /(\.jsonl|\.json|\.zip|(^|\/)CLAUDE\.md|(^|\/)AGENTS\.md)$/i;
const $ = (id) => document.getElementById(id);
let worker = null;
let lastReport = null;
let running = false;

// ---------- collecting files ----------

function readEntries(reader) {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

async function walk(entry, out) {
  if (entry.isFile) {
    const relative = entry.fullPath.replace(/^\//, '');
    if (WANTED.test(relative)) out.push({ relative, file: await new Promise((res, rej) => entry.file(res, rej)) });
    return;
  }
  const reader = entry.createReader();
  for (let batch = await readEntries(reader); batch.length; batch = await readEntries(reader)) {
    for (const child of batch) await walk(child, out);
  }
}

async function fromDrop(dataTransfer) {
  const out = [];
  const entries = [...dataTransfer.items].map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
  if (entries.length) for (const entry of entries) await walk(entry, out);
  else for (const file of dataTransfer.files) if (WANTED.test(file.name)) out.push({ relative: file.name, file });
  return out;
}

function fromInput(input) {
  return [...input.files]
    .map((file) => ({ relative: file.webkitRelativePath || file.name, file }))
    .filter((item) => WANTED.test(item.relative));
}

// ---------- talking to the worker ----------

function getWorker() {
  if (!worker) worker = new Worker('worker.js');
  return worker;
}

function ask(message, transfer = []) {
  const w = getWorker();
  return new Promise((resolve, reject) => {
    const listener = ({ data }) => {
      if (data.type === 'error') { w.removeEventListener('message', listener); reject(new Error(data.message)); return; }
      w.removeEventListener('message', listener);
      resolve(data);
    };
    w.addEventListener('message', listener);
    w.postMessage(message, transfer);
  });
}

async function analyze(items) {
  if (running) return;
  if (!items.length) {
    showStatus('No agent logs found there. Pick the .claude or .codex folder, or the zip made by the command below.', 'error');
    return;
  }
  running = true;
  setBusy(true);
  try {
    showStatus('Loading the analysis engine. The first visit downloads about 6 MB; later visits use the cached copy.');
    await ask({ type: 'boot' });
    await ask({ type: 'start' });
    let n = 0;
    for (const item of items) {
      n += 1;
      showStatus(`Reading ${n.toLocaleString()} of ${items.length.toLocaleString()} files…`, 'busy', n / items.length);
      const buffer = await item.file.arrayBuffer();
      await ask({ type: 'file', n, relative: item.relative, buffer }, [buffer]);
    }
    showStatus('Building the report…', 'busy', 1);
    const { json } = await ask({ type: 'finish', public: $('public').checked });
    lastReport = JSON.parse(json);
    render(lastReport, false);
    showStatus('');
    fetch('ping?e=report', { method: 'POST', keepalive: true }).catch(() => {});
  } catch (error) {
    showStatus(`Something went wrong while reading the logs: ${error.message}. Nothing was uploaded. Try the zip command below, or open an issue on GitHub.`, 'error');
  } finally {
    running = false;
    setBusy(false);
  }
}

async function refreshPublic() {
  if (!lastReport || running) return;
  const { json } = await ask({ type: 'finish', public: $('public').checked });
  lastReport = JSON.parse(json);
  render(lastReport, false);
}

// ---------- status ----------

function showStatus(text, kind = 'busy', fraction = null) {
  const box = $('status');
  box.hidden = !text;
  box.dataset.kind = kind;
  $('status-text').textContent = text;
  const bar = $('status-bar');
  bar.hidden = fraction === null;
  if (fraction !== null) bar.value = fraction;
}

function setBusy(busy) {
  for (const id of ['pick-folder', 'pick-zip']) $(id).disabled = busy;
  $('drop').classList.toggle('is-busy', busy);
}

// ---------- rendering ----------

const AGENT = { 'claude-code': 'Claude Code', codex: 'Codex', opencode: 'OpenCode' };
const VERDICT = {
  stopped: ['good', 'Stopped'],
  'still happening': ['bad', 'Still happening'],
  'too early': ['wait', 'Too early to tell'],
  'not seen before or after': ['wait', 'Not seen'],
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child != null) node.append(child.nodeType ? child : document.createTextNode(String(child)));
  return node;
}

function copyButton(text, label = 'Copy') {
  const button = el('button', { class: 'copy', type: 'button', text: label });
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = 'Copied';
    } catch {
      const range = document.createRange();
      range.selectNodeContents(button.previousElementSibling || button);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      button.textContent = 'Selected';
    }
    setTimeout(() => (button.textContent = label), 1600);
  });
  return button;
}

function instructionFile(path) {
  if (path.includes('/codex/')) return '~/.codex/AGENTS.md';
  if (path.includes('/claude/')) return '~/.claude/CLAUDE.md';
  return path.split('/').pop();
}

function pct(part, whole) {
  return whole ? `${Math.round((part / whole) * 100)}%` : '—';
}

function render(data, example) {
  const root = $('report');
  root.replaceChildren();
  $('report-label').textContent = example ? 'Example report' : 'Your report';
  $('example-note').hidden = !example;
  $('public-row').hidden = example;

  if (!data.sessions) {
    root.append(el('p', { class: 'empty', text: 'No agent sessions with tool calls were found in those files.' }));
    return;
  }

  const agents = Object.entries(data.by_source).map(([k, v]) => `${v} ${AGENT[k] || k}`).join(' · ');
  const period = data.period ? `${data.period[0].slice(0, 10)} → ${data.period[1].slice(0, 10)}` : '';
  root.append(
    el('div', { class: 'summary' },
      el('div', { class: 'figure lead' },
        el('span', { class: 'value', text: pct(data.recurring_failed_steps, data.failed_steps) }),
        el('span', { class: 'label', text: `of failed tool calls (${data.recurring_failed_steps.toLocaleString()} of ${data.failed_steps.toLocaleString()}) repeated a mistake from another session` })),
      el('div', { class: 'figure' },
        el('span', { class: 'value', text: data.sessions.toLocaleString() }),
        el('span', { class: 'label', text: `sessions: ${agents}` })),
      el('div', { class: 'figure' },
        el('span', { class: 'value', text: data.steps.toLocaleString() }),
        el('span', { class: 'label', text: `tool calls${period ? `, ${period}` : ''}` }))),
  );

  root.append(el('h3', { text: data.recurring.length ? 'Mistakes your agent repeats' : 'No mistake has repeated across sessions yet' }));
  const list = el('ol', { class: 'mistakes' });
  for (const r of data.recurring) {
    const fix = r.fix || {};
    const item = el('li', { class: 'mistake' },
      el('div', { class: 'mistake-head' },
        el('code', { class: 'cause', text: r.cause }),
        el('span', { class: 'count', text: `${r.sessions} sessions · ${r.failed_steps} failures` })),
      r.example ? el('div', { class: 'example', text: `e.g. ${r.example}` }) : null);
    if (fix.line) {
      const line = `- ${fix.line}`;
      item.append(
        el('div', { class: 'fix' },
          el('span', { class: 'fix-label', text: 'Add this line to CLAUDE.md or AGENTS.md' }),
          el('div', { class: 'fix-line' }, el('code', { text: line }), copyButton(line)),
          el('div', { class: 'fix-cli' },
            el('code', { text: `orchestra-review apply ${fix.id} --to ~/.claude/CLAUDE.md` }),
            copyButton(`orchestra-review apply ${fix.id} --to ~/.claude/CLAUDE.md`))));
    } else {
      item.append(el('div', { class: 'nofix', text: fix.note ? `No suggested line: ${fix.note}.` : 'No suggested line.' }));
    }
    list.append(item);
  }
  root.append(list);

  if (data.fixes_in_place && data.fixes_in_place.length) {
    root.append(el('h3', { text: 'Lines already in your instruction files' }));
    root.append(el('p', { class: 'hint', text: 'Sessions that hit the mistake, out of sessions that tried the same action, before and after the line was added.' }));
    const wrap = el('div', { class: 'table-wrap' });
    const table = el('table', {},
      el('thead', {}, el('tr', {}, ...['Line', 'File', 'Added', 'Before', 'After', 'Verdict'].map((h) => el('th', { text: h })))));
    const body = el('tbody');
    for (const f of data.fixes_in_place) {
      const side = (s) => (s.tried == null ? `${s.hit} / ${s.sessions}` : `${s.hit} / ${s.tried}`);
      const [tone, word] = VERDICT[f.verdict] || ['wait', f.verdict];
      body.append(el('tr', {},
        el('td', {}, el('code', { text: f.id })),
        el('td', { text: instructionFile(f.file) }),
        el('td', { text: f.added.slice(0, 10) }),
        el('td', { class: 'num', text: side(f.before) }),
        el('td', { class: 'num', text: side(f.after) }),
        el('td', {}, el('span', { class: `pill ${tone}`, text: word }))));
    }
    table.append(body);
    wrap.append(table);
    root.append(wrap);
  }

  if (!example && data.blocked_steps) {
    root.append(el('p', { class: 'hint', text: `${data.blocked_steps} calls blocked by permissions or by you are not counted as failures.` }));
  }
}

// ---------- wiring ----------

const drop = $('drop');
for (const name of ['dragenter', 'dragover']) drop.addEventListener(name, (e) => { e.preventDefault(); drop.classList.add('is-over'); });
for (const name of ['dragleave', 'drop']) drop.addEventListener(name, () => drop.classList.remove('is-over'));
drop.addEventListener('drop', async (e) => { e.preventDefault(); analyze(await fromDrop(e.dataTransfer)); });
$('pick-folder').addEventListener('click', () => $('folder-input').click());
$('pick-zip').addEventListener('click', () => $('zip-input').click());
$('folder-input').addEventListener('change', (e) => { analyze(fromInput(e.target)); e.target.value = ''; });
$('zip-input').addEventListener('change', (e) => { analyze(fromInput(e.target)); e.target.value = ''; });
$('public').addEventListener('change', refreshPublic);
for (const button of document.querySelectorAll('[data-copy]')) {
  button.replaceWith(copyButton($(button.dataset.copy).textContent));
}

fetch('sample-report.json')
  .then((r) => r.json())
  .then((data) => { if (!lastReport) render(data, true); })
  .catch(() => {});

// For automated tests: analyze files without the picker.
window.orchestraReview = { analyze: (items) => analyze(items) };
