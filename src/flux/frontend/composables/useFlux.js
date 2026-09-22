/**
 * Flux API Composable
 * Wraps all pywebview.api calls with mock fallbacks for browser dev
 */
window.Flux = window.Flux || {};

// pywebview injects its JS bridge from a background thread *after* the page has
// loaded: `window.pywebview` appears first, but `window.pywebview.api` is only
// created once the `pywebviewready` event fires (webview/js/finish.js). Sampling
// the bridge once at mount raced that injection and made the packaged app fall
// back to the browser mocks - e.g. the output-folder picker then used WebView2's
// showDirectoryPicker(), which is blocked on file:// pages ("Can't open this
// folder"). So the bridge must be checked at call time, and readiness awaited.
const hasBridge = () => Boolean(window.pywebview && window.pywebview.api);

// Resolves true as soon as the native bridge is usable, false when running in a
// plain browser (no bridge will ever arrive).
const bridgeReady = new Promise((resolve) => {
  if (hasBridge()) {
    resolve(true);
    return;
  }
  window.addEventListener('pywebviewready', () => resolve(true), { once: true });
  window.setTimeout(() => resolve(hasBridge()), 3000);
});

// Normalizes a directory path that came from the native folder picker or from
// localStorage. pywebview's WinForms backend returns the selection as a tuple,
// and an earlier build stringified it, so a stored value could be tuple repr
// text - "('D:\\Projects',)" with every separator doubled. Such a value is not
// a path: Python rejected it with "The output directory does not exist", so it
// is unwrapped (and the repr escaping undone) on the way in and on read from
// localStorage. Plain paths - including UNC paths, which legitimately start
// with two separators - are returned unchanged.
const normalizeDirPath = (value) => {
  if (typeof value !== 'string') return '';

  let path = value.trim();
  if (!path) return '';

  // Browser-dev placeholders are not real directories.
  if (path.startsWith('[Dev Mode]')) return '';

  const tuple = path.match(/^\((['"])([\s\S]*)\1,?\)$/);
  if (tuple) {
    path = tuple[2].replace(/\\\\/g, '\\').trim();
  }

  return path;
};

window.Flux.useFlux = function() {
  // Reactive flag so the UI can reflect the real mode once the bridge lands.
  const isNative = Vue.ref(hasBridge());
  bridgeReady.then((ready) => {
    if (ready) {
      isNative.value = true;
    }
  });

  // Mock delay helper
  const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  // Mock data for browser dev
  const mockSupportedFormats = {
    input: ['jpg', 'jpeg', 'png', 'webp'],
    output: ['jpg', 'png', 'webp'],
  };

  const mockJobs = new Map();
  let mockJobCounter = 0;

  async function callApi(name, args) {
    if (hasBridge()) {
      // Surface bridge rejections (Python exceptions arrive as Error{name,
      // message, stack}) instead of leaving unhandled promise rejections
      // that silently swallow the real failure.
      const invoke = () => window.pywebview.api[name](...args);
      return bridgeReady.then((ready) => {
        if (!ready) {
          return invoke();
        }
        return invoke().catch((error) => {
          console.error(`pywebview.api.${name} failed:`, error);
          throw error;
        });
      });
    }

    // Browser dev fallback - never reach the native bridge.
    return null;
  }

  async function convert(files, targetFormat, options = {}) {
    if (hasBridge()) {
      // Never ship native File/Blob objects through the bridge: pywebview's
      // serializer keeps only own enumerable properties, so a File arrives
      // in Python as an empty object and every path check fails. The
      // payload must be plain {name, size, type, path} objects only.
      const plainFiles = files.map((f) => ({
        name: f.name,
        size: f.size || 0,
        type: f.type || '',
        path: typeof f.path === 'string' ? f.path : '',
      }));
      return callApi('convert', [plainFiles, targetFormat, options]);
    }

    // Mock implementation
    await delay(100);
    const jobId = `mock-job-${++mockJobCounter}`;
    const totalFiles = files.length;
    let completed = 0;

    mockJobs.set(jobId, {
      status: 'running',
      progress: 0,
      outputPaths: [],
      error: null,
      totalFiles,
      completed,
    });

    // Simulate async conversion
    (async () => {
      for (const file of files) {
        await delay(500 + Math.random() * 1000);
        completed++;
        const progress = Math.round((completed / totalFiles) * 100);
        const job = mockJobs.get(jobId);
        if (job) {
          job.progress = progress;
          job.completed = completed;
          job.outputPaths.push(`/mock/output/${file.name.replace(/\.[^.]+$/, '')}.${targetFormat}`);
          if (completed === totalFiles) {
            job.status = 'complete';
          }
        }
      }
    })();

    return { jobId };
  }

  async function getProgress(jobId) {
    if (hasBridge()) {
      return callApi('getProgress', [jobId]);
    }

    // Mock implementation
    await delay(50);
    const job = mockJobs.get(jobId);
    if (!job) {
      return { code: 'NOT_FOUND', message: 'Job not found' };
    }
    return {
      status: job.status,
      progress: job.progress,
      outputPaths: job.outputPaths,
      error: job.error,
    };
  }

  async function cancel(jobId) {
    if (hasBridge()) {
      return callApi('cancel', [jobId]);
    }

    // Mock implementation
    await delay(50);
    const job = mockJobs.get(jobId);
    if (!job) {
      return { code: 'NOT_FOUND', message: 'Job not found' };
    }
    if (job.status === 'complete') {
      return { code: 'ALREADY_COMPLETE', message: 'Job already complete' };
    }
    job.status = 'cancelled';
    return { cancelled: true };
  }

  async function getSupportedFormats() {
    if (hasBridge()) {
      return callApi('getSupportedFormats', []);
    }

    // Mock implementation
    await delay(50);
    return mockSupportedFormats;
  }

  async function pickFiles(multiple = true) {
    if (hasBridge()) {
      return callApi('pickFiles', [{ multiple }]);
    }

    // Mock implementation - create a file input and simulate selection
    return new Promise((resolve) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.multiple = multiple;
      input.accept = 'image/jpeg,image/png,image/webp';
      input.style.display = 'none';
      input.onchange = (e) => {
        const files = Array.from(e.target.files);
        document.body.removeChild(input);
        if (files.length === 0) {
          resolve({ code: 'CANCELLED', message: 'File selection cancelled' });
        } else {
          resolve({ paths: files });
        }
      };
      document.body.appendChild(input);
      input.click();
    });
  }

  async function pickOutputDir() {
    if (hasBridge()) {
      const result = await callApi('pickOutputDir', []);
      if (result && result.path) {
        // The native picker is the one place a real directory path enters the
        // app state, so it is normalized here rather than trusted verbatim.
        const path = normalizeDirPath(result.path);
        if (!path) {
          return { code: 'CANCELLED', message: 'Folder selection cancelled' };
        }
        return { path };
      }
      return result;
    }

    // Mock implementation - try the File System Access API, which only exists in
    // http(s) dev. On a file:// page (the packaged app) WebView2 blocks it with
    // "Can't open this folder", so it must never be attempted there.
    if (/^https?:$/.test(location.protocol) && 'showDirectoryPicker' in window) {
      try {
        const handle = await window.showDirectoryPicker();
        return { path: handle.name };
      } catch (e) {
        // User cancelled or API not available
        return { code: 'CANCELLED', message: 'Folder selection cancelled' };
      }
    }

    // Fallback for non-secure contexts - return a clear dev-only path
    await delay(100);
    return { path: '[Dev Mode] Select output folder in native app' };
  }

  async function openOutputDir(path) {
    if (hasBridge()) {
      return callApi('openOutputDir', [{ path }]);
    }
    // Mock implementation
    await delay(50);
    if (path && path.startsWith('[Dev Mode]')) {
      console.log('Dev mode: Cannot open output directory in browser');
      return { code: 'DEV_MODE', message: 'Open output folder only works in native app' };
    }
    console.log('Mock: Opening output directory:', path);
    return { opened: true };
  }

  // Listen for dropped-file paths pushed from Python (flux-dropped-paths
  // CustomEvents; see FluxAPI.attach_drop_listener). The subscription lives
  // for the page lifetime - drops are a repeating user action, so there is
  // nothing to unsubscribe from. `handler` receives the delivered file list
  // ([{name, path, size}, ...]) or an empty array.
  function onDroppedPaths(handler) {
    window.addEventListener('flux-dropped-paths', (e) => {
      handler(e.detail && Array.isArray(e.detail.files) ? e.detail.files : []);
    });
  }

  async function getFilePreview(path) {
    if (hasBridge()) {
      return callApi('getFilePreview', [{ path }]);
    }
    // Mock implementation - can't read local files in browser
    await delay(50);
    return { code: 'DEV_MODE', message: 'Preview only works in native app' };
  }

  return {
    convert,
    getProgress,
    cancel,
    getSupportedFormats,
    pickFiles,
    pickOutputDir,
    openOutputDir,
    onDroppedPaths,
    getFilePreview,
    isNative,
    normalizeDirPath,
  };
};