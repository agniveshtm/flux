/**
 * Flux App Footer Component
 * Convert all (primary), Open output folder (ghost), output folder selector, Clear completed
 */
window.Flux = window.Flux || {};
window.Flux.AppFooter = {
  name: 'AppFooter',
  props: {
    files: {
      type: Array,
      default: () => [],
    },
    isConverting: {
      type: Boolean,
      default: false,
    },
    outputDir: {
      type: String,
      default: '',
    },
    hasCompleted: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['convert-all', 'pick-output-dir', 'open-output-dir', 'clear-completed'],
  computed: {
    canConvert() {
      return this.files.length > 0 && !this.isConverting && this.files.some(f => f.status !== 'done');
    },
    isBatchConversion() {
      return this.files.filter(f => f.status !== 'done').length > 1;
    },
    convertButtonText() {
      if (this.isConverting) return 'Converting...';
      if (this.files.length > 0 && this.files.every(f => f.status === 'done')) return 'Converted';
      return this.isBatchConversion ? 'Convert all' : 'Convert';
    },
    completedCount() {
      return this.files.filter(f => f.status === 'done').length;
    },
    isDevModePath() {
      return this.outputDir && this.outputDir.startsWith('[Dev Mode]');
    },
    canOpenOutputDir() {
      return this.outputDir && this.hasCompleted && !this.isDevModePath;
    },
  },
  template: `
    <footer class="h-18 px-4 flex items-center justify-between border-t border-line bg-surface sticky bottom-0 z-10">
      <div class="flex items-center gap-3 flex-1 min-w-0">
        <button
          type="button"
          class="btn-primary whitespace-nowrap"
          @click="$emit('convert-all')"
          :disabled="!canConvert"
        >
          <svg v-if="isConverting" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          {{ convertButtonText }}
        </button>
        <button
          type="button"
          class="btn-ghost whitespace-nowrap"
          @click="$emit('open-output-dir')"
          :disabled="!canOpenOutputDir"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          Open output folder
        </button>
      </div>
      <div class="flex items-center gap-3 flex-shrink-0">
        <div class="flex items-center gap-2 px-3 py-2 bg-surface border border-line rounded-lg min-w-[240px] max-w-[360px] relative">
          <svg class="w-4 h-4 text-muted flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          <span 
            class="text-sm text-fg truncate flex-1" 
            :title="outputDir || 'No output folder selected'"
          >
            {{ outputDir || 'No output folder selected' }}
          </span>
          <button
            type="button"
            class="btn-ghost p-1.5 rounded flex-shrink-0"
            @click="$emit('pick-output-dir')"
            aria-label="Select output folder"
            title="Select output folder"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
          </button>
        </div>
        <button
          type="button"
          class="btn-ghost whitespace-nowrap"
          @click="$emit('clear-completed')"
          :disabled="completedCount === 0"
        >
          Clear completed
        </button>
      </div>
    </footer>
  `,
};