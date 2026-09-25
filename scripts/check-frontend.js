#!/usr/bin/env node
/**
 * Frontend checks for the Flux UI - no npm dependencies.
 *
 *   node scripts/check-frontend.js
 *
 * 1. Syntax-checks every non-vendor .js file under src/flux/frontend with
 *    `node --check`.
 * 2. Compiles every component template with the vendored Vue build (the
 *    same runtime the app ships), so a malformed template fails CI instead
 *    of silently rendering nothing in WebView2.
 * 3. Verifies index.html references every component/composable script and
 *    that every such file on disk is referenced - a component that exists
 *    but is not wired into the page is invisible at runtime.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const FRONTEND = path.join(ROOT, 'src', 'flux', 'frontend');
const VUE_PATH = path.join(FRONTEND, 'vendor', 'vue.global.prod.js');
const INDEX_PATH = path.join(FRONTEND, 'index.html');

let failures = 0;

const rel = (file) => path.relative(ROOT, file).replace(/\\/g, '/');

function ok(label) {
  console.log(`ok    ${label}`);
}

function fail(label, message) {
  failures += 1;
  const body = String(message).trim().replace(/\n/g, '\n      ');
  console.error(`FAIL  ${label}\n      ${body}`);
}

function listJsFiles() {
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'vendor') continue; // vendored Vue, not ours
        walk(full);
      } else if (entry.name.endsWith('.js')) {
        files.push(full);
      }
    }
  };
  walk(FRONTEND);
  return files.sort();
}

function syntaxCheck(file) {
  const result = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
  if (result.status === 0) {
    ok(`${rel(file)} syntax`);
    return true;
  }
  fail(`${rel(file)} syntax`, result.stderr || result.stdout || 'node --check failed');
  return false;
}

// --- Minimal DOM sufficient for Vue's entity decoder ---------------------
// The vendored build decodes entities via a cached div:
//   text: div.innerHTML = raw;           div.textContent
//   attr: div.innerHTML = `<div foo="...">`; div.children[0].getAttribute('foo')
// without a `children[0]` accessor the attribute path throws
// "Cannot read properties of undefined (reading '0')" on any template with
// `&` inside an attribute (e.g. FileList's `v-if="a && b"`).
const NAMED_ENTITIES = { quot: '"', amp: '&', lt: '<', gt: '>', apos: "'", nbsp: ' ' };

function decodeEntities(text) {
  return String(text).replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, body) => {
    if (body[0] === '#') {
      const code = body[1] === 'x' || body[1] === 'X'
        ? parseInt(body.slice(2), 16)
        : parseInt(body.slice(1), 10);
      return Number.isNaN(code) ? match : String.fromCodePoint(code);
    }
    return Object.prototype.hasOwnProperty.call(NAMED_ENTITIES, body)
      ? NAMED_ENTITIES[body]
      : match;
  });
}

function createStubElement() {
  return {
    _html: '',
    textContent: '',
    children: [],
    get innerHTML() {
      return this._html;
    },
    set innerHTML(value) {
      this._html = String(value);
      this.textContent = decodeEntities(this._html);
      this.children = [{
        getAttribute: (name) => {
          const match = this._html.match(new RegExp(`<div ${name}="([\\s\\S]*)">`));
          return match ? decodeEntities(match[1]) : null;
        },
      }];
    },
  };
}

// --- Checks ---------------------------------------------------------------

function loadVue() {
  // The vendored file is a classic browser script with a top-level
  // `var Vue = ...` (no UMD wrapper), so evaluating it in a function scope
  // and returning Vue is how Node can get at it.
  const source = fs.readFileSync(VUE_PATH, 'utf8');
  return new Function(`${source};return Vue;`)();
}

function executeForLoadErrors(file) {
  try {
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(file, 'utf8'))();
    return true;
  } catch (error) {
    fail(rel(file), (error && error.stack) || error);
    return false;
  }
}

function compileTemplates(Vue) {
  const componentsDir = path.join(FRONTEND, 'components');
  for (const name of fs.readdirSync(componentsDir).sort()) {
    if (!name.endsWith('.js')) continue;
    const file = path.join(componentsDir, name);
    if (!executeForLoadErrors(file)) continue;

    const componentName = path.basename(name, '.js');
    const component = window.Flux && window.Flux[componentName];
    if (!component || typeof component.template !== 'string') {
      fail(rel(file), `did not register window.Flux.${componentName} with a template`);
      continue;
    }

    // Vue reports template errors through console.error rather than
    // throwing, so the error stream has to be captured, not just caught.
    const captured = [];
    const originalError = console.error;
    console.error = (...args) => captured.push(args.map(String).join(' '));
    try {
      Vue.compile(component.template);
    } catch (error) {
      captured.push(String((error && error.stack) || error));
    } finally {
      console.error = originalError;
    }

    if (captured.length) fail(`${rel(file)} template`, captured.join('\n'));
    else ok(`${rel(file)} template compiles`);
  }
}

function checkIndexWiring() {
  let localFailures = 0;
  const html = fs.readFileSync(INDEX_PATH, 'utf8');
  const referenced = new Set();
  for (const match of html.matchAll(/<script\s+src="\.\/([^"]+)"/g)) {
    const ref = match[1];
    referenced.add(ref);
    if (!fs.existsSync(path.join(FRONTEND, ref))) {
      localFailures += 1;
      fail(`index.html -> ${ref}`, 'referenced script does not exist');
    }
  }

  for (const dir of ['components', 'composables']) {
    for (const name of fs.readdirSync(path.join(FRONTEND, dir)).sort()) {
      if (!name.endsWith('.js')) continue;
      const ref = `${dir}/${name}`;
      if (!referenced.has(ref)) {
        localFailures += 1;
        fail(ref, 'not referenced by index.html');
      }
    }
  }

  if (localFailures === 0) ok('index.html script tags match files on disk');
}

function main() {
  // Browser-ish globals for executing the frontend scripts in plain Node.
  // useFlux.js registers a pywebviewready listener and arms a 3s readiness
  // timeout at load, so the listener no-ops must exist and timers must be
  // unref'd - otherwise the timeout would either throw (addEventListener is
  // not a Node global) or keep the process alive after the checks finish.
  global.window = global;
  global.addEventListener = () => {};
  global.removeEventListener = () => {};
  const nativeSetTimeout = global.setTimeout;
  global.setTimeout = (callback, delay, ...args) => {
    const timer = nativeSetTimeout(callback, delay, ...args);
    if (timer && typeof timer.unref === 'function') timer.unref();
    return timer;
  };
  global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  global.document = {
    createElement: () => createStubElement(),
    addEventListener: () => {},
    removeEventListener: () => {},
  };

  const files = listJsFiles();
  files.forEach(syntaxCheck);

  const composablesDir = path.join(FRONTEND, 'composables');
  for (const name of fs.readdirSync(composablesDir).sort()) {
    if (!name.endsWith('.js')) continue;
    const file = path.join(composablesDir, name);
    if (executeForLoadErrors(file)) ok(`${rel(file)} loads`);
  }

  let Vue = null;
  try {
    Vue = loadVue();
  } catch (error) {
    fail(rel(VUE_PATH), error);
  }
  if (Vue && typeof Vue.compile === 'function') {
    // Vue's runtime compiler emits `new Function` code that resolves the
    // free variable `Vue` against the global scope (window.Vue in the
    // browser); in plain Node that only works if it is set explicitly.
    global.Vue = Vue;
    compileTemplates(Vue);
  } else if (Vue) {
    fail(rel(VUE_PATH), 'no Vue.compile export');
  }

  checkIndexWiring();

  if (failures > 0) {
    console.error(`\n${failures} frontend check(s) failed`);
    process.exit(1);
  }
  console.log('\nall frontend checks passed');
}

main();
