/**
 * Flux Main Entry Point
 * Initializes Vue app with all components and composables
 */
const { createApp, ref, computed, watch, onMounted, onUnmounted } = Vue;

// Initialize global namespace
window.Flux = window.Flux || {};

// Register all components
const components = {
  AppHeader: window.Flux.AppHeader,
  Branding: window.Flux.Branding,
  DropZone: window.Flux.DropZone,
  FileList: window.Flux.FileList,
  FileRow: window.Flux.FileRow,
  FormatSelect: window.Flux.FormatSelect,
  ProgressBar: window.Flux.ProgressBar,
  ThemeToggle: window.Flux.ThemeToggle,
  UpdateBell: window.Flux.UpdateBell,
  AppFooter: window.Flux.AppFooter,
};

Object.entries(components).forEach(([name, component]) => {
  if (component) {
    window.Flux[name] = component;
  }
});

// Main App Component
const App = {
  name: 'FluxApp',
  components,
  setup() {
    const { theme, toggleTheme, cleanup: cleanupTheme } = window.Flux.useTheme();
    const { convert, getProgress, getSupportedFormats, pickFiles, pickOutputDir, openOutputDir, onDroppedPaths, getFilePreview, isNative, normalizeDirPath, checkForUpdate, downloadUpdate, installUpdate, onUpdateProgress } = window.Flux.useFlux();

    const files = ref([]);
    const supportedFormats = ref({});
    const outputDir = ref('');
    const isDragOver = ref(false);
    const isConverting = ref(false);
    const activeJobs = ref(new Map());
    const progressTimers = ref(new Map());

    // --- In-app update state -----------------------------------------------
    // updateState: checking | idle | downloading | downloaded | installing | error
    const updateInfo = ref(null);
    const updateState = ref('checking');
    const updateProgress = ref(0);
    const updateReceived = ref(0);
    const updateTotal = ref(0);
    const updateError = ref('');
    const updateCheckError = ref('');
    const updateDismissed = ref(false); // session-only "Dismiss"
    const seenRelease = ref(localStorage.getItem('flux-seen-release') || '');

    // Badge rule: only a newer, not-yet-acknowledged, not-yet-acted-on
    // release gets the yellow exclamation. Downloading/dismissing/marking it
    // read all clear it - the bell itself stays clickable either way.
    const showUpdateBadge = computed(() => {
      const info = updateInfo.value;
      if (!info || !info.available) return false;
      if (updateDismissed.value) return false;
      if (seenRelease.value && seenRelease.value === info.latestVersion) return false;
      return updateState.value === 'idle' || updateState.value === 'checking';
    });

    function handleUpdateProgress(detail) {
      if (detail.phase === 'downloading') {
        updateState.value = 'downloading';
        updateProgress.value = detail.progress || 0;
        updateReceived.value = detail.received || 0;
        updateTotal.value = detail.total || 0;
      } else if (detail.phase === 'downloaded') {
        updateState.value = 'downloaded';
        updateProgress.value = 100;
      } else if (detail.phase === 'error') {
        updateState.value = 'error';
        updateError.value = detail.message || 'The update download failed.';
      }
    }

    async function handleUpdateCheck() {
      updateState.value = 'checking';
      updateCheckError.value = '';
      try {
        const info = await checkForUpdate();
        if (info && !info.code) {
          updateInfo.value = info;
        } else {
          // A failed check is not worth disturbing anyone: the menu shows a
          // quiet "could not check" with a retry, and no badge ever appears.
          updateCheckError.value = (info && info.message) || 'Could not check for updates.';
        }
      } catch (e) {
        console.warn('Update check failed:', e);
        updateCheckError.value = 'Could not check for updates.';
      }
      updateState.value = 'idle';
    }

    async function handleUpdateDownload() {
      if (updateState.value === 'downloading') return;
      updateError.value = '';
      updateProgress.value = 0;
      updateReceived.value = 0;
      updateTotal.value = 0;
      // Optimistic: Python confirms with flux-update-progress events, or an
      // immediate error object (NO_UPDATE) if the state is stale.
      updateState.value = 'downloading';
      try {
        const result = await downloadUpdate();
        if (!result || result.code) {
          updateState.value = 'error';
          updateError.value = (result && result.message) || 'Could not start the download.';
        }
      } catch (e) {
        console.warn('Update download failed to start:', e);
        updateState.value = 'error';
        updateError.value = 'Could not start the download.';
      }
    }

    async function handleUpdateInstall() {
      if (updateState.value === 'installing') return;
      updateError.value = '';
      updateState.value = 'installing';
      try {
        const result = await installUpdate();
        if (!result || result.code) {
          // Nothing has started yet, so fall back to the ready state and
          // let the user retry instead of stranding them on "Restarting...".
          updateState.value = 'downloaded';
          updateError.value = (result && result.message) || 'Could not start the installer.';
        }
        // Success: Python runs the setup and closes this window.
      } catch (e) {
        console.warn('Update install failed to start:', e);
        updateState.value = 'downloaded';
        updateError.value = 'Could not start the installer.';
      }
    }

    function handleUpdateDismiss() {
      // Session only - the badge returns on the next launch unless the user
      // marks the release read or actually updates.
      updateDismissed.value = true;
    }

    function handleUpdateMarkRead() {
      if (updateInfo.value) {
        seenRelease.value = updateInfo.value.latestVersion;
        localStorage.setItem('flux-seen-release', seenRelease.value);
      }
      updateDismissed.value = true;
    }

    // Load supported formats on mount
    onMounted(async () => {
      // Subscribe before any await: an early drop would otherwise fire
      // flux-dropped-paths with no listener and permanently lose its paths.
      // Dropped-file paths are pushed from Python after each drop
      // (flux-dropped-paths; see FluxAPI.attach_drop_listener). Enrich any
      // rows still missing a path.
      onDroppedPaths((delivered) => {
        if (!Array.isArray(delivered) || delivered.length === 0) return;
        delivered.forEach(delivery => {
          if (!delivery || !delivery.path) return;
          const row = files.value.find(
            f => !f.path && f.status === 'ready' && f.name === delivery.name
          );
          if (row) {
            row.path = delivery.path;
            if (!row.size && delivery.size) row.size = delivery.size;
          }
        });
      });

      // Update check runs once per start; progress is subscribed first so a
      // fast download cannot outrun its listener. Deliberately not awaited:
      // it waits on the native bridge and must not delay format loading.
      onUpdateProgress(handleUpdateProgress);
      handleUpdateCheck();

      try {
        const formats = await getSupportedFormats();
        supportedFormats.value = formats.output || {};
        // Build input->output mapping
        const mapping = {};
        (formats.input || []).forEach(input => {
          mapping[input] = (formats.output || []).filter(out => 
            (input === 'jpg' || input === 'jpeg') && ['png', 'webp'].includes(out) ||
            input === 'png' && ['jpg', 'webp'].includes(out) ||
            input === 'webp' && ['jpg', 'png'].includes(out)
          );
        });
        supportedFormats.value = mapping;
      } catch (e) {
        console.error('Failed to load supported formats:', e);
      }

      // Load saved output directory, unless it is a browser-dev placeholder:
      // the mock picker stored "[Dev Mode] ..." strings which the native app
      // then reused, so every conversion failed validation with "The output
      // directory does not exist". Native flow re-prompts instead.
      // Load the saved output directory. The value is normalized rather than
      // trusted: an earlier build stored the native picker's tuple repr
      // ("('D:\\Projects',)") and the browser-dev placeholder ("[Dev Mode] ..."),
      // neither of which is a directory - that is what made conversions fail
      // with "The output directory does not exist". Unusable values are dropped
      // so the picker is invoked again instead.
      const rawSavedDir = localStorage.getItem('flux-output-dir');
      const savedDir = normalizeDirPath(rawSavedDir);
      if (savedDir) {
        outputDir.value = savedDir;
        // Persist the normalization so a value stored in an unusable shape by
        // an earlier build cannot resurface on the next launch.
        if (rawSavedDir !== savedDir) {
          localStorage.setItem('flux-output-dir', savedDir);
        }
      } else {
        localStorage.removeItem('flux-output-dir');
      }
    });

    onUnmounted(() => {
      cleanupTheme();
      progressTimers.value.forEach(timer => clearInterval(timer));
    });

    function addFiles(newFiles) {
      const validTypes = ['image/jpeg', 'image/png', 'image/webp'];
      const validExtensions = ['jpg', 'jpeg', 'png', 'webp'];

      newFiles.forEach(file => {
        const ext = file.name.split('.').pop()?.toLowerCase() || '';
        const isValid = validTypes.includes(file.type) || validExtensions.includes(ext);

        if (isValid && !files.value.some(f => f.name === file.name && f.size === file.size)) {
          files.value.push({
            id: `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            // Rows are plain data: name/size/type plus a path that the
            // native picker fills immediately and a drop fills once Python
            // pushes the dropped-file paths back into the page. A native
            // File object is never kept on the row (it cannot cross the
            // bridge); browser dev keeps an object URL for previews only.
            name: file.name,
            size: file.size || 0,
            type: file.type || '',
            path: typeof file.path === 'string' ? file.path : '',
            objectUrl: typeof File !== 'undefined' && file instanceof File
              ? URL.createObjectURL(file)
              : null,
            targetFormat: getDefaultTargetFormat(ext),
            status: 'ready',
            progress: 0,
          });
        }
      });
    }

    function getDefaultTargetFormat(inputExt) {
      const map = {
        jpg: 'png',
        jpeg: 'png',
        png: 'jpg',
        webp: 'jpg',
      };
      return map[inputExt.toLowerCase()] || 'png';
    }

    function removeFile(index) {
      const [removed] = files.value.splice(index, 1);
      if (removed && removed.objectUrl) {
        URL.revokeObjectURL(removed.objectUrl);
      }
    }

    function updateFormat(index, format) {
      if (files.value[index]) {
        files.value[index].targetFormat = format;
      }
    }

    function forgetOutputDir() {
      outputDir.value = '';
      localStorage.removeItem('flux-output-dir');
    }

    // Shared by both places a directory can be chosen (the footer button and
    // the automatic prompt on Convert) so the value is stored in one shape.
    function rememberOutputDir(path) {
      const dir = normalizeDirPath(path);
      if (!dir) return false;
      outputDir.value = dir;
      localStorage.setItem('flux-output-dir', dir);
      return true;
    }

    async function handleConvertAll() {
      if (files.value.length === 0 || isConverting.value) return;
      if (!outputDir.value) {
        const result = await pickOutputDir();
        if (!rememberOutputDir(result && result.path)) {
          return;
        }
      }

      const pendingFiles = files.value.filter(f => f.status !== 'done');
      if (pendingFiles.length === 0) return;

      // Every row must carry a real filesystem path before conversion: the
      // backend resolves input files exclusively through the "path" key.
      const unresolved = pendingFiles.filter(f => !f.path || typeof f.path !== 'string' || !f.path.trim());
      if (unresolved.length > 0) {
        const message = 'File location not available. Please drop the file again or pick it with "Select files".';
        unresolved.forEach(f => { f.status = 'error'; f.error = message; });
        console.error('Conversion blocked:', message);
        return;
      }

      isConverting.value = true;

      // The API converts a batch to a single target format, so rows with
      // different per-row selections are split into one job per format
      // instead of every file inheriting the first row's choice.
      const groups = new Map();
      pendingFiles.forEach(f => {
        const fmt = f.targetFormat || pendingFiles[0].targetFormat;
        if (!groups.has(fmt)) groups.set(fmt, []);
        groups.get(fmt).push(f);
      });

      let startedAnyJob = false;
      for (const [targetFormat, rows] of groups) {
        try {
          // Plain {name, size, type, path} objects only - a native File object
          // serializes through pywebview's bridge as an empty object and every
          // path check in Python fails.
          const fileObjects = rows.map(f => ({
            name: f.name,
            size: f.size || 0,
            type: f.type || '',
            path: f.path,
          }));
          const result = await convert(fileObjects, targetFormat, { outputDir: outputDir.value });

          if (result && result.jobId) {
            startProgressPolling(result.jobId, rows.map(f => f.id));
            startedAnyJob = true;
          } else if (result && result.details && result.details.outputDir) {
            // The remembered output folder is gone (deleted/renamed, or an
            // unusable value an earlier build stored): forget it so the next
            // Convert asks for a real one, instead of failing every time.
            forgetOutputDir();
            const message = 'The output folder is no longer available. Choose a folder to continue.';
            pendingFiles.forEach(f => {
              f.status = 'error';
              f.error = message;
            });
            console.error('Conversion failed:', message, result.details.outputDir);
            isConverting.value = false;
            return;
          } else {
            // The API rejected the request without throwing (e.g. a validation
            // error object) - surface it and unblock the UI.
            const message = (result && (result.message || result.error)) || 'Conversion failed';
            rows.forEach(f => {
              f.status = 'error';
              f.error = message;
            });
            console.error('Conversion failed:', message);
          }
        } catch (e) {
          console.error('Conversion failed:', e);
          rows.forEach(f => {
            f.status = 'error';
            f.error = String(e);
          });
        }
      }

      if (!startedAnyJob) {
        isConverting.value = false;
      }
    }

    function startProgressPolling(jobId, fileIds) {
      const timer = setInterval(async () => {
        try {
          const progress = await getProgress(jobId);
          
          if (progress.status === 'running' || progress.status === 'pending') {
            const pct = progress.progress || 0;
            fileIds.forEach((fid, idx) => {
              const file = files.value.find(f => f.id === fid);
              if (file) {
                file.status = 'converting';
                file.progress = pct;
              }
            });
          } else if (progress.status === 'complete') {
            fileIds.forEach((fid, idx) => {
              const file = files.value.find(f => f.id === fid);
              if (file) {
                file.status = 'done';
                file.progress = 100;
                file.outputPath = progress.outputPaths?.[idx];
              }
            });
            clearInterval(timer);
            progressTimers.value.delete(jobId);
            checkAllComplete();
          } else if (progress.status === 'error') {
            fileIds.forEach(fid => {
              const file = files.value.find(f => f.id === fid);
              if (file) {
                file.status = 'error';
                file.error = progress.error;
              }
            });
            clearInterval(timer);
            progressTimers.value.delete(jobId);
            checkAllComplete();
          }
        } catch (e) {
          console.error('Progress polling error:', e);
        }
      }, 200);

      progressTimers.value.set(jobId, timer);
    }

    function checkAllComplete() {
      const allDone = files.value.every(f => f.status === 'done' || f.status === 'error');
      if (allDone) {
        isConverting.value = false;
      }
    }

    async function handlePickFiles() {
      const result = await pickFiles(true);
      if (result.paths && result.paths.length > 0) {
        // Native dialog returns real path strings; the browser mock returns
        // File objects. Decide by shape - `isNative` may still be settling.
        if (typeof result.paths[0] === 'string') {
          // window.py's pickFiles reports name/size alongside the paths so rows
          // can show real sizes (a File object can't be passed to Python).
          const details = result.files || [];
          result.paths.forEach((path, index) => {
            const info = details[index] || {};
            const name = info.name || path.split(/[/\\]/).pop();
            addFiles([{
              name,
              size: info.size || 0,
              type: `image/${name.split('.').pop().toLowerCase()}`,
              // Keep the real path on the row: handleConvertAll passes these
              // objects to Python, which resolves the file via `path`.
              path,
            }]);
          });
        } else {
          // Browser dev mock: native File objects, which cannot be passed to
          // Python. addFiles stores plain {name, size, type} rows; preview
          // and conversion via Python are unavailable without a bridge.
          addFiles(result.paths);
        }
      }
    }

    async function handlePickOutputDir() {
      const result = await pickOutputDir();
      if (!rememberOutputDir(result && result.path)) {
        console.warn('Output folder selection returned no usable directory.');
      }
    }

    async function handleOpenOutputDir() {
      if (outputDir.value) {
        await openOutputDir(outputDir.value);
      }
    }

    function handleClearCompleted() {
      const removed = files.value.filter(f => f.status === 'done');
      removed.forEach(f => {
        if (f.objectUrl) URL.revokeObjectURL(f.objectUrl);
      });
      files.value = files.value.filter(f => f.status !== 'done');
    }

    // Bulk counterpart to removeFile (the per-row "x"): the same per-row
    // cleanup in one pass, so no blob URL is leaked when the whole list is
    // dropped at once. Blocked while a conversion is in flight, matching the
    // per-row button being disabled on a converting row.
    function handleClearAll() {
      if (isConverting.value) return;
      files.value.forEach(f => {
        if (f.objectUrl) URL.revokeObjectURL(f.objectUrl);
      });
      files.value = [];
    }

    function handleDropZoneClick() {
      handlePickFiles();
    }

    function handleDrop(event, incoming) {
      // Rows are created without a path first. The real filesystem paths
      // arrive when Python's document-level drop listener (registered at
      // startup by FluxAPI.attach_drop_listener) receives this same drop
      // event through pywebview's DOM-event channel and pushes a
      // flux-dropped-paths event back into the page; the subscription in
      // onMounted resolves these rows. Note: no JS bridge call can trigger
      // pywebview's FilesDropped delivery - only that Python-side listener
      // can (webview/js/api.js posts AdditionalObjects exclusively from its
      // own pywebviewEventHandler payload).
      addFiles(incoming);
    }

    function handleDragOver() {
      isDragOver.value = true;
    }

    function handleDragLeave() {
      isDragOver.value = false;
    }

    const hasCompleted = computed(() => files.value.some(f => f.status === 'done'));

    return {
      theme,
      toggleTheme,
      files,
      supportedFormats,
      outputDir,
      isDragOver,
      isConverting,
      hasCompleted,
      isNative,
      // Must be returned from setup(): the template hands it to FileList and
      // FileList to FileRow, whose preview loader calls it. Omitting it fails
      // silently - the production Vue build resolves it to undefined and the
      // prop simply never arrives, so no row ever asked Python for a preview.
      getFilePreview,
      addFiles,
      removeFile,
      updateFormat,
      handleConvertAll,
      handlePickFiles,
      handlePickOutputDir,
      handleOpenOutputDir,
      handleClearCompleted,
      handleClearAll,
      handleDropZoneClick,
      handleDrop,
      handleDragOver,
      handleDragLeave,
      updateInfo,
      updateState,
      updateProgress,
      updateReceived,
      updateTotal,
      updateError,
      updateCheckError,
      showUpdateBadge,
      handleUpdateCheck,
      handleUpdateDownload,
      handleUpdateInstall,
      handleUpdateDismiss,
      handleUpdateMarkRead,
    };
  },
  template: `
    <div class="flex flex-col h-screen bg-bg text-fg">
      <AppHeader
        :theme="theme"
        :update="updateInfo"
        :update-badge="showUpdateBadge"
        :update-state="updateState"
        :update-progress="updateProgress"
        :update-received="updateReceived"
        :update-total="updateTotal"
        :update-error="updateError"
        :update-check-error="updateCheckError"
        :is-native="isNative"
        @toggle-theme="toggleTheme"
        @update-check="handleUpdateCheck"
        @update-download="handleUpdateDownload"
        @update-install="handleUpdateInstall"
        @update-dismiss="handleUpdateDismiss"
        @update-mark-read="handleUpdateMarkRead"
      />
      <main class="flex-1 flex flex-col overflow-hidden px-4 py-4 gap-4 min-h-0 w-full">
        <Branding :theme="theme" />
        <DropZone
          :is-drag-over="isDragOver"
          :is-disabled="isConverting"
          @drop="handleDrop"
          @click="handleDropZoneClick"
          @dragover="handleDragOver"
          @dragleave="handleDragLeave"
        />
        <FileList
          :files="files"
          :supported-formats="supportedFormats"
          :is-converting="isConverting"
          :get-file-preview="getFilePreview"
          @remove="removeFile"
          @format-change="updateFormat"
          @clear-all="handleClearAll"
        />
      </main>
      <AppFooter
        :files="files"
        :is-converting="isConverting"
        :output-dir="outputDir"
        :has-completed="hasCompleted"
        @convert-all="handleConvertAll"
        @pick-output-dir="handlePickOutputDir"
        @open-output-dir="handleOpenOutputDir"
        @clear-completed="handleClearCompleted"
      />
    </div>
  `,
};

// Create and mount app
const app = createApp(App);
app.mount('#app');