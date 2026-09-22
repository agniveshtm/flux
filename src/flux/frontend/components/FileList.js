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
  },
  emits: ['remove', 'format-change'],
  template: `
    <div class="card flex-1 overflow-hidden min-h-0 flex flex-col">
      <div class="overflow-x-auto scrollbar-thin flex-1">
        <table class="w-full" role="table">
          <thead>
            <tr class="bg-surface-2 border-b border-line">
              <th class="px-4 py-2 text-left text-xs font-semibold text-muted uppercase tracking-wider w-8">#</th>
              <th class="px-4 py-2 text-left text-xs font-semibold text-muted uppercase tracking-wider">File</th>
              <th class="px-4 py-2 text-left text-xs font-semibold text-muted uppercase tracking-wider w-36">Target</th>
              <th class="px-4 py-2 text-left text-xs font-semibold text-muted uppercase tracking-wider w-32">Status</th>
              <th class="px-4 py-2 text-left text-xs font-semibold text-muted uppercase tracking-wider w-40">Progress</th>
              <th class="px-4 py-2 text-right text-xs font-semibold text-muted uppercase tracking-wider w-12"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="files.length === 0 && !isConverting" class="text-center">
              <td colspan="6" class="py-12">
                <svg class="w-12 h-12 mx-auto text-muted mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
                <p class="text-muted">No files added</p>
                <p class="text-xs text-muted mt-1">Drag and drop images or click "Select files" to get started</p>
              </td>
            </tr>
            <tr v-else>
              <FileRow
                v-for="(file, index) in files"
                :key="file.id"
                :file="file"
                :index="index"
                :supported-formats="supportedFormats"
                @remove="$emit('remove', index)"
                @format-change="val => $emit('format-change', index, val)"
              />
            </tr>
            <tr v-if="files.length > 0 && files.every(f => f.status === 'done')" class="text-center">
              <td colspan="6" class="py-8">
                <svg class="w-10 h-10 mx-auto text-success mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
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