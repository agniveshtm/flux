/**
 * Shared helpers for the Flux UI checks.
 *
 * These scripts drive a real browser against the real frontend and read the
 * rendered geometry back out, because the layout rules the UI has to keep
 * (equal wings, a centred button, a popover that is not clipped by an
 * ancestor's overflow) are invisible to a static check - see
 * scripts/check-frontend.js, which covers the templates and the wiring.
 *
 * No npm dependencies: Node 22+ ships a global WebSocket, and the browser is
 * driven over the DevTools protocol directly.
 */
'use strict';

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const REPO_FRONTEND = path.join(ROOT, 'src', 'flux', 'frontend');
const REPO_ASSETS = path.join(ROOT, 'src', 'flux', 'assets');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// --- Browser discovery -----------------------------------------------------

const BROWSER_CANDIDATES = [
  process.env.FLUX_BROWSER,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/snap/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
];

function browserPath() {
  for (const candidate of BROWSER_CANDIDATES) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  for (const name of ['chrome', 'chromium', 'msedge', 'google-chrome']) {
    const found = which(name);
    if (found) return found;
  }
  throw new Error(
    'No Chrome or Edge found. Set FLUX_BROWSER to the browser executable.'
  );
}

function which(name) {
  const dirs = (process.env.PATH || '').split(path.delimiter);
  const suffixes = process.platform === 'win32' ? ['.exe', '.cmd', ''] : [''];
  for (const dir of dirs) {
    if (!dir) continue;
    for (const suffix of suffixes) {
      const full = path.join(dir, name + suffix);
      if (fs.existsSync(full) && fs.statSync(full).isFile()) return full;
    }
  }
  return null;
}

// --- The instrumented copy of the frontend ---------------------------------

// setup() keeps the app state in closure variables, so a script cannot seed
// a file row from the outside. The copy below is the shipped frontend with
// one line added inside setup() that publishes those variables on
// window.__flux - the repo itself is never modified.
//
// The layout has to be preserved: Branding resolves its logo as
// '../assets/logo-dark.png', so the copy keeps the frontend and the assets
// as siblings under a common parent, exactly as src/flux/ does.
let instrumentedUrl = null;
const instanceId = Date.now() + '-' + process.pid;

function instrumentFrontend() {
  if (instrumentedUrl) return instrumentedUrl;

  // Each Node invocation gets its own temp dir to avoid races when running
  // multiple checks in parallel.
  const tmp = path.join(os.tmpdir(), `flux-ui-check-${instanceId}`);
  const bundle = path.join(tmp, 'flux');
  fs.rmSync(tmp, { recursive: true, force: true });
  fs.mkdirSync(bundle, { recursive: true });
  fs.cpSync(REPO_FRONTEND, path.join(bundle, 'frontend'), { recursive: true });
  fs.cpSync(REPO_ASSETS, path.join(bundle, 'assets'), { recursive: true });

  const mainPath = path.join(bundle, 'frontend', 'main.js');
  const source = fs.readFileSync(mainPath, 'utf8');
  const newline = source.includes('\r\n') ? '\r\n' : '\n';
  // The anchor is the single `return {` of setup(), identified by the
  // first entry of its returned object. If main.js is reshaped and the
  // anchor stops matching exactly once, this throws rather than silently
  // producing a copy with no __flux.
  const anchor = new RegExp(
    `(^|\\r?\\n)([ \\t]*)return \\{(\\r?\\n)([ \\t]*)theme,`
  );
  const matches = source.match(new RegExp(anchor.source, 'g')) || [];
  if (matches.length !== 1) {
    throw new Error(
      `setup() return anchor found ${matches.length} times in main.js - ` +
        'the instrumentation point moved'
    );
  }
  const patched = source.replace(anchor, (all, lead, indent, nl, inner) =>
    `${lead}${indent}window.__flux = { files, bulkTarget, supportedOutputs, ` +
    `handleSelectTarget };${nl}${nl}${indent}return {${nl}${inner}theme,`
  );
  fs.writeFileSync(mainPath, patched);

  instrumentedUrl = pathToUrl(path.join(bundle, 'frontend', 'index.html'));
  return instrumentedUrl;
}

function repoFrontendUrl() {
  return pathToUrl(path.join(REPO_FRONTEND, 'index.html'));
}

function pathToUrl(filePath) {
  const resolved = path.resolve(filePath).replace(/\\/g, '/');
  return `file:///${resolved.startsWith('/') ? resolved.slice(1) : resolved}`;
}

// --- Driving the browser ----------------------------------------------------

/**
 * Launch a headless browser, open `url` in it, and hand back a session.
 *
 * The page is given a moment to settle before the caller starts reading
 * geometry: the frontend mounts asynchronously (it awaits the backend's
 * format list on mount) and measures before that would read an empty app.
 */
async function openPage(options = {}) {
  const width = options.width || 900;
  const height = options.height || 620;
  const scheme = options.scheme || 'light';
  const port = options.port || 9200 + (process.pid % 400);
  const browser = browserPath();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'flux-cdp-'));

  const args = [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    `--window-size=${width},${height}`,
  ];
  // Headless Edge reports the dark scheme by default and ignores
  // preferredColorScheme=2, so the light scheme has to be asked for
  // explicitly.
  if (scheme !== 'dark') args.push('--blink-settings=preferredColorScheme=1');
  args.push('about:blank');

  const child = spawn(browser, args, { stdio: 'ignore' });

  let targets = null;
  for (let attempt = 0; attempt < 40 && !targets; attempt += 1) {
    await sleep(250);
    try {
      targets = await getJSON(port, '/json/list');
    } catch (error) {
      /* the browser is not listening yet */
    }
  }
  const page = (targets || []).find((target) => target.type === 'page');
  if (!page) {
    killBrowser(child);
    // Profile dir: the browser holds it open briefly after kill, so try with
    // retries then leave it for the OS if still locked.
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    } catch (error) {
      /* the profile may be locked; the OS will reclaim it */
    }
    throw new Error('The browser exposed no page target');
  }

  const socket = new WebSocket(page.webSocketDebuggerUrl);
  let nextId = 0;
  const pending = new Map();
  const problems = [];

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
      return;
    }
    if (message.method === 'Runtime.consoleAPICalled'
        && ['error', 'warning'].includes(message.params.type)) {
      problems.push(
        `${message.params.type}: ` +
        message.params.args.map((arg) => arg.value || arg.description || '').join(' ')
      );
    }
    if (message.method === 'Runtime.exceptionThrown') {
      const details = message.params.exceptionDetails;
      problems.push(
        `exception: ${details.text || ''} ` +
        (details.exception ? details.exception.description : '')
      );
    }
    if (message.method === 'Log.entryAdded'
        && message.params.entry.level === 'error') {
      problems.push(`log: ${message.params.entry.text}`);
    }
  };

  const send = (method, params) => new Promise((resolve) => {
    const id = ++nextId;
    pending.set(id, resolve);
    socket.send(JSON.stringify({ id, method, params: params || {} }));
  });

  await new Promise((resolve) => { socket.onopen = resolve; });
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Page.navigate', { url: options.url });
  await sleep(options.settle || 2500);

  const evaluate = async (expression) => {
    const response = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (response.result && response.result.exceptionDetails) {
      throw new Error(
        'evaluate failed: ' + response.result.exceptionDetails.text
      );
    }
    const value = response.result && response.result.result;
    return value ? value.value : null;
  };

  const screenshot = async (filePath) => {
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    if (!shot.result || !shot.result.data) {
      throw new Error('the browser returned no screenshot');
    }
    fs.writeFileSync(filePath, Buffer.from(shot.result.data, 'base64'));
    return filePath;
  };

  const close = () => {
    try {
      socket.close();
    } catch (error) {
      /* the socket is already gone */
    }
    killBrowser(child);
    // The browser holds its profile directory open for a moment after it is
    // killed, so the removal can fail on Windows. It is a temp directory -
    // leaving it behind is not worth failing the run over.
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    } catch (error) {
      /* the profile is still locked; the OS will reclaim the temp dir */
    }
  };

  return { evaluate, screenshot, problems, close };
}

function getJSON(port, pathname) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port, path: pathname }, (response) => {
      let body = '';
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => {
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    }).on('error', reject);
  });
}

// The browser spawns a process tree, and killing the parent alone leaves
// the children behind on Windows.
function killBrowser(child) {
  if (process.platform === 'win32' && child.pid) {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(child.pid)], {
      stdio: 'ignore',
    });
    return;
  }
  child.kill();
}

// --- Reporting --------------------------------------------------------------

let failures = 0;

function ok(label) {
  console.log(`ok    ${label}`);
}

function fail(label, message) {
  failures += 1;
  const body = String(message).trim().replace(/\n/g, '\n      ');
  console.error(`FAIL  ${label}\n      ${body}`);
}

function check(label, condition, message) {
  if (condition) {
    ok(label);
  } else {
    fail(label, message === undefined ? 'the condition was false' : message);
  }
}

function finish() {
  if (failures > 0) {
    console.error(`\n${failures} UI check(s) failed`);
    process.exit(1);
  }
  console.log('\nall UI checks passed');
}

module.exports = {
  browserPath,
  check,
  fail,
  finish,
  instrumentFrontend,
  ok,
  openPage,
  repoFrontendUrl,
  ROOT,
};
