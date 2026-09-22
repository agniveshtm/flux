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
  DropZone: window.Flux.DropZone,
  FileList: window.Flux.FileList,
  FileRow: window.Flux.FileRow,
  FormatSelect: window.Flux.FormatSelect,
  ProgressBar: window.Flux.ProgressBar,
  ThemeToggle: window.Flux.ThemeToggle,
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
    const { convert, getProgress, getSupportedFormats, pickFiles, pickOutputDir, isNative } = window.Flux.useFlux();

    const files = ref([]);
    const supportedFormats = ref({});
    const outputDir = ref('');
    const isDragOver = ref(false);
    const isConverting = ref(false);
    const activeJobs = ref(new Map());
    const progressTimers = ref(new Map());

    // Load supported formats on mount
    onMounted(async () => {
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

      // Load saved output directory
      const savedDir = localStorage.getItem('flux-output-dir');
      if (savedDir) outputDir.value = savedDir;
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
            file,
            name: file.name,
            size: file.size,
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
      files.value.splice(index, 1);
    }

    function updateFormat(index, format) {
      if (files.value[index]) {
        files.value[index].targetFormat = format;
      }
    }

    async function handleConvertAll() {
      if (files.value.length === 0 || isConverting.value) return;
      if (!outputDir.value) {
        const result = await pickOutputDir();
        if (result.path) {
          outputDir.value = result.path;
          localStorage.setItem('flux-output-dir', result.path);
        } else {
          return;
        }
      }

      const pendingFiles = files.value.filter(f => f.status !== 'done');
      if (pendingFiles.length === 0) return;

      isConverting.value = true;

      try {
        const fileObjects = pendingFiles.map(f => f.file);
        const targetFormat = pendingFiles[0].targetFormat;
        const result = await convert(fileObjects, targetFormat, { outputDir: outputDir.value });
        
        if (result.jobId) {
          startProgressPolling(result.jobId, pendingFiles.map(f => f.id));
        }
      } catch (e) {
        console.error('Conversion failed:', e);
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
      if (result.paths) {
        // In native, we get paths; in mock, we get File objects
        if (isNative) {
          // For native, we'd need to read files - for now just add mock files
          result.paths.forEach(path => {
            const name = path.split(/[/\\]/).pop();
            addFiles([{
              name,
              size: 0,
              type: `image/${name.split('.').pop()}`,
            }]);
          });
        } else {
          addFiles(result.paths);
        }
      }
    }

    async function handlePickOutputDir() {
      const result = await pickOutputDir();
      if (result.path) {
        outputDir.value = result.path;
        localStorage.setItem('flux-output-dir', result.path);
      }
    }

    async function handleOpenOutputDir() {
      if (isNative && outputDir.value) {
        // Native would open folder via API
        console.log('Open output dir:', outputDir.value);
      }
    }

    function handleClearCompleted() {
      files.value = files.value.filter(f => f.status !== 'done');
    }

    function handleDropZoneClick() {
      handlePickFiles();
    }

    function handleDrop(files) {
      addFiles(files);
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
      addFiles,
      removeFile,
      updateFormat,
      handleConvertAll,
      handlePickFiles,
      handlePickOutputDir,
      handleOpenOutputDir,
      handleClearCompleted,
      handleDropZoneClick,
      handleDrop,
      handleDragOver,
      handleDragLeave,
    };
  },
  template: `
    <div class="flex flex-col h-screen bg-bg text-fg">
      <AppHeader
        :theme="theme"
        @toggle-theme="toggleTheme"
        @open-settings="handlePickOutputDir"
      />
      <main class="flex-1 flex flex-col overflow-hidden p-4 gap-4 min-h-0">
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
          @remove="removeFile"
          @format-change="updateFormat"
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