/**
 * Flux File List Component
 * Table-like list of files with empty, loading, and error states
 */
window.Flux = window.Flux || {};
window.Flux.FileList = {
  name: 'FileList',
  components: {
    FileRow: window.Flux.FileRow,
  },
  props: {
    files: {
      type: Array,
      default: () => [],
    },
    supportedFormats: {
      type: Object,
      default: () => ({}),
    },
    isConverting: {
      type: Boolean,
      default: false,
    },
    getFilePreview: {
      type: Function,
      required: false,
    },
  },
  emits: ['remove', 'format-change', 'clear-all'],
  computed: {
    fileCountLabel() {
      return this.files.length === 1 ? '1 file' : `${this.files.length} files`;
    },
    completedCount() {
      return this.files.filter(f => f.status === 'done').length;
    },
    // The per-row remove button is disabled while that row converts, so the
    // bulk action is held back for the whole batch: removing every row mid-job
    // would leave a conversion running with nothing left to report onto.
    canClearAll() {
      return this.files.length > 0 && !this.isConverting;
    },
  },
  template: `
    <div class="card flex-1 overflow-hidden min-h-0 flex flex-col">
      <!-- List toolbar: counterpart to the per-row remove buttons, which alone
           made clearing a long list a click per file. Only rendered once there
           is something to clear, so the empty state stays centred. -->
      <div
        v-if="files.length > 0"
        class="flex items-center justify-between gap-3 px-4 py-2 border-b border-line bg-surface-2 flex-shrink-0"
      >
        <p class="text-xs text-muted">
          {{ fileCountLabel }}<span v-if="completedCount > 0"> · {{ completedCount }} converted</span>
        </p>
        <button
          type="button"
          class="btn-danger px-3 py-2 text-xs whitespace-nowrap"
          @click="$emit('clear-all')"
          :disabled="!canClearAll"
          aria-label="Remove all files"
          title="Remove all files from the list"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          Clear all
        </button>
      </div>
      <div class="overflow-x-auto scrollbar-thin flex-1">
        <table class="w-full table-fixed" role="table">
          <thead>
            <tr class="bg-surface-2 border-b border-line">
              <th class="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider w-10">#</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider min-w-[300px]">File</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider w-40">Target</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider w-32">Status</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider w-48">Progress</th>
              <th class="px-4 py-3 text-right text-xs font-semibold text-muted uppercase tracking-wider w-14"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="files.length === 0 && !isConverting" class="text-center">
              <td colspan="6" class="py-10">
                <svg class="w-10 h-10 mx-auto text-muted mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
                <p class="text-muted">No files added</p>
                <p class="text-xs text-muted mt-1">Drag and drop images or click "Select files" to get started</p>
              </td>
            </tr>
            <template v-else>
              <FileRow
                v-for="(file, index) in files"
                :key="file.id"
                :file="file"
                :index="index"
                :supported-formats="supportedFormats"
                :get-file-preview="getFilePreview"
                @remove="$emit('remove', index)"
                @format-change="val => $emit('format-change', index, val)"
              />
            </template>
            <tr v-if="files.length > 0 && files.every(f => f.status === 'done')" class="text-center">
              <td colspan="6" class="py-6">
                <svg class="w-8 h-8 mx-auto text-success mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p class="text-sm text-success font-medium">All files converted</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
};