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
  },
  emits: ['remove', 'format-change'],
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
      <td class="px-4 py-3 w-8 text-center">
        <span class="text-sm text-muted">{{ index + 1 }}</span>
      </td>
      <td class="px-4 py-3 min-w-0">
        <div class="flex items-center gap-3 min-w-0">
          <svg class="w-8 h-8 flex-shrink-0 text-muted" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M21 19V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2zM17 1H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V3a2 2 0 00-2-2H9.5a2 2 0 00-.82.16L5.16 4.84A2 2 0 005 5.5V19a2 2 0 002 2h14a2 2 0 002-2V4.5A2 2 0 0017.5 3H17V1z"/>
          </svg>
          <div class="min-w-0">
            <p class="text-sm font-medium text-fg truncate">{{ file.name }}</p>
            <p class="text-xs text-muted">{{ fileSize }}</p>
          </div>
        </div>
      </td>
      <td class="px-4 py-3">
        <FormatSelect
          :input-format="inputFormat"
          :target-format="file.targetFormat"
          :disabled="file.status === 'converting' || file.status === 'done'"
          @update:targetFormat="val => $emit('format-change', val)"
        />
      </td>
      <td class="px-4 py-3 w-32">
        <span :class="statusClass">{{ statusText }}</span>
      </td>
      <td class="px-4 py-3 w-40">
        <ProgressBar
          :progress="file.progress || 0"
          :status="file.status"
        />
      </td>
      <td class="px-4 py-3 w-12 text-right">
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
  `,
};