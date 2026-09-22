/**
 * Flux File Row Component
 * Filename, size, target-format dropdown, status, progress bar, remove button
 */
window.Flux = window.Flux || {};
window.Flux.FileRow = {
  name: 'FileRow',
  components: {
    FormatSelect: window.Flux.FormatSelect,
    ProgressBar: window.Flux.ProgressBar,
  },
  props: {
    file: {
      type: Object,
      required: true,
    },
    index: {
      type: Number,
      required: true,
    },
    supportedFormats: {
      type: Object,
      default: () => ({}),
    },
    getFilePreview: {
      type: Function,
      required: false,
    },
  },
  emits: ['remove', 'format-change', 'preview-click'],
  data() {
    return {
      previewUrl: null,
      previewError: null,
      fullscreenLoading: false,
      showFullscreen: false,
    };
  },
  mounted() {
    this.createPreviewUrl();
  },
  watch: {
    // Dropped rows are created before Python pushes their real paths back
    // (flux-dropped-paths), so the preview has to be (re)requested once the
    // path lands - mounted() alone would only ever cover picked files.
    'file.path'(path) {
      if (path) {
        this.createPreviewUrl();
      }
    },
  },
  beforeUnmount() {
    this.cleanupPreview();
  },
  methods: {
    // Previews come from Python as base64 data URLs: the page runs on
    // file:// so a path-based <img src> is blocked, and File objects dropped
    // onto the window are not readable by the backend. Dropped rows preview
    // once their path arrives (see the file.path watcher).
    createPreviewUrl() {
      this.cleanupPreview();
      if (this.file.path && this.getFilePreview) {
        this.fetchPreview(this.file.path);
      } else if (this.file.objectUrl) {
        // Browser dev / dropped rows awaiting flux-dropped-paths: a blob URL
        // keeps the thumbnail warm until the real path lands.
        this.previewUrl = this.file.objectUrl;
      }
    },
    cleanupPreview() {
      this.previewUrl = null;
      this.previewError = null;
    },
    async fetchPreview(path) {
      try {
        const result = await this.getFilePreview(path);
        if (result && result.dataUrl) {
          this.previewUrl = result.dataUrl;
        } else {
          this.useFallbackOrError((result && result.message) || 'Preview not available');
        }
      } catch (e) {
        this.useFallbackOrError((e && e.message) || 'Preview failed');
      }
    },
    // A failed bridge preview should not blank a thumbnail we already have.
    useFallbackOrError(message) {
      if (this.file.objectUrl) {
        this.previewUrl = this.file.objectUrl;
      } else {
        this.previewError = message;
      }
    },
    async onPreviewClick() {
      if (this.previewUrl) {
        // Reuse the loaded thumbnail data URL for the fullscreen view.
        this.showFullscreen = true;
        return;
      }
      if (this.file.path && this.getFilePreview && !this.fullscreenLoading) {
        this.fullscreenLoading = true;
        await this.fetchPreview(this.file.path);
        this.fullscreenLoading = false;
        if (this.previewUrl) {
          this.showFullscreen = true;
        }
      }
    },
    closeFullscreen() {
      this.showFullscreen = false;
    },
  },
  computed: {
    inputFormat() {
      return this.file.name.split('.').pop()?.toLowerCase() || '';
    },
    validTargets() {
      const formats = this.supportedFormats[this.inputFormat] || [];
      return formats;
    },
    statusText() {
      switch (this.file.status) {
        case 'ready':
          return 'Ready';
        case 'converting':
          return 'Converting...';
        case 'done':
          return 'Done';
        case 'error':
          return 'Failed';
        default:
          return 'Ready';
      }
    },
    statusClass() {
      switch (this.file.status) {
        case 'ready':
          return 'badge-ready';
        case 'converting':
          return 'badge-converting';
        case 'done':
          return 'badge-done';
        case 'error':
          return 'badge-error';
        default:
          return 'badge-ready';
      }
    },
    fileSize() {
      const bytes = this.file.size || 0;
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    },
  },
  template: `
    <tr class="border-b border-line hover:bg-surface-2 transition-colors duration-150">
      <td class="px-4 py-4 w-10 text-center">
        <span class="text-sm text-muted">{{ index + 1 }}</span>
      </td>
      <td class="px-4 py-4 min-w-[300px]">
        <div class="flex items-center gap-3 min-w-0">
          <div class="relative w-16 h-16 flex-shrink-0 rounded-lg overflow-hidden bg-surface-2"
               @click="onPreviewClick"
               :title="previewUrl ? 'Click to view fullscreen' : (previewError || 'Preview loading…')"
               role="button"
               tabindex="0"
               :aria-label="previewUrl ? 'View fullscreen preview' : 'Preview unavailable'"
               @keydown.enter="onPreviewClick">
            <img
              v-if="previewUrl"
              :src="previewUrl"
              :alt="file.name"
              class="w-full h-full object-cover"
            />
            <span v-else-if="previewError" class="preview-thumb-fallback" aria-hidden="true">!</span>
            <svg
              v-else
              class="w-8 h-8 text-muted mx-auto my-auto"
              fill="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path d="M21 19V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2zM17 1H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V3a2 2 0 00-2-2H9.5a2 2 0 00-.82.16L5.16 4.84A2 2 0 005 5.5V19a2 2 0 002 2h14a2 2 0 002-2V4.5A2 2 0 0017.5 3H17V1z"/>
            </svg>
          </div>
          <div class="min-w-0">
            <p class="text-sm font-medium text-fg truncate">{{ file.name }}</p>
            <p class="text-xs text-muted mt-1">{{ fileSize }}</p>
            <!-- Conversion failures reach the row as file.error (bridge
                 rejections and per-file errors); without this line the row
                 only showed a "Failed" badge with no reason. -->
            <p v-if="file.error" class="text-xs text-accent mt-1 truncate" :title="file.error">
              {{ file.error }}
            </p>
          </div>
        </div>
      </td>
      <td class="px-4 py-4 w-40">
        <FormatSelect
          :input-format="inputFormat"
          :target-format="file.targetFormat"
          :disabled="file.status === 'converting' || file.status === 'done'"
          @update:targetFormat="val => $emit('format-change', val)"
        />
      </td>
      <td class="px-4 py-4 w-32">
        <span :class="statusClass" :title="file.error || statusText">{{ statusText }}</span>
      </td>
      <td class="px-4 py-4 w-48">
        <ProgressBar
          :progress="file.progress || 0"
          :status="file.status"
        />
      </td>
      <td class="px-4 py-4 w-14 text-right">
        <button
          type="button"
          class="btn-danger p-1.5 rounded-lg"
          @click="$emit('remove')"
          :disabled="file.status === 'converting'"
          aria-label="Remove file"
          title="Remove file"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </td>
    </tr>
    <!-- Fullscreen preview modal -->
    <div v-if="showFullscreen"
         class="preview-modal"
         @click.self="closeFullscreen"
         role="dialog"
         aria-modal="true"
         aria-label="Image preview">
      <button
        type="button"
        class="preview-modal-close"
        @click="closeFullscreen"
        aria-label="Close preview"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
      <div class="preview-modal-body">
        <img v-if="previewUrl"
             :src="previewUrl"
             :alt="file.name"
             class="preview-modal-image"
         />
        <div v-else class="preview-modal-empty">
          <p>Preview not available for this file type</p>
        </div>
      </div>
      <p class="preview-modal-caption">{{ file.name }}</p>
    </div>
  `,
};