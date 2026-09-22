/**
 * Flux API Composable
 * Wraps all pywebview.api calls with mock fallbacks for browser dev
 */
window.Flux = window.Flux || {};
window.Flux.useFlux = function() {
  const isNative = typeof window !== 'undefined' && window.pywebview && window.pywebview.api;

  // Mock delay helper
  const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  // Mock data for browser dev
  const mockSupportedFormats = {
    input: ['jpg', 'jpeg', 'png', 'webp'],
    output: ['jpg', 'png', 'webp'],
  };

  const mockJobs = new Map();
  let mockJobCounter = 0;

  async function convert(files, targetFormat, options = {}) {
    if (isNative) {
      return window.pywebview.api.convert(files, targetFormat, options);
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
    if (isNative) {
      return window.pywebview.api.getProgress(jobId);
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
    if (isNative) {
      return window.pywebview.api.cancel(jobId);
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
    if (isNative) {
      return window.pywebview.api.getSupportedFormats();
    }

    // Mock implementation
    await delay(50);
    return mockSupportedFormats;
  }

  async function pickFiles(multiple = true) {
    if (isNative) {
      return window.pywebview.api.pickFiles({ multiple });
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
          resolve({ paths: files.map(f => f.path || f.name) });
        }
      };
      document.body.appendChild(input);
      input.click();
    });
  }

  async function pickOutputDir() {
    if (isNative) {
      return window.pywebview.api.pickOutputDir();
    }

    // Mock implementation
    await delay(100);
    return { path: '/mock/output/directory' };
  }

  return {
    convert,
    getProgress,
    cancel,
    getSupportedFormats,
    pickFiles,
    pickOutputDir,
    isNative,
  };
};