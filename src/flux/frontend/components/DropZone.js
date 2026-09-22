/**
 * Flux Drop Zone Component
 * Large dashed border, crimson-tinted on drag-over, red "Select files" button
 */
window.Flux = window.Flux || {};
window.Flux.DropZone = {
  name: 'DropZone',
  props: {
    isDragOver: {
      type: Boolean,
      default: false,
    },
    isDisabled: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['drop', 'click', 'dragover', 'dragleave'],
  template: `
    <div
      class="drop-zone flex-1 flex flex-col items-center justify-center p-8 min-h-[200px]"
      :class="{ active: isDragOver }"
      @dragover.prevent="onDragOver"
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
      @click="onClick"
      role="button"
      tabindex="0"
      :aria-label="isDragOver ? 'Drop files to upload' : 'Click to select files or drag and drop'"
      :aria-disabled="isDisabled"
    >
      <svg
        class="w-12 h-12 text-muted mb-4 transition-colors duration-150"
        :class="{ 'text-accent': isDragOver }"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
      <p class="text-base text-fg mb-2" v-if="!isDragOver">Drag and drop images here, or click to select</p>
      <p class="text-base text-accent font-medium mb-2" v-else>Drop files to convert</p>
      <p class="text-sm text-muted mb-6">Supports JPG, PNG, WebP</p>
      <button
        type="button"
        class="btn-primary"
        @click.stop="onClick"
        :disabled="isDisabled"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        Select files
      </button>
    </div>
  `,
  methods: {
    onDragOver(e) {
      e.preventDefault();
      e.stopPropagation();
      this.$emit('dragover', e);
    },
    onDragLeave(e) {
      e.preventDefault();
      e.stopPropagation();
      this.$emit('dragleave', e);
    },
    onDrop(e) {
      e.preventDefault();
      e.stopPropagation();
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        this.$emit('drop', files);
      }
    },
    onClick(e) {
      if (!this.isDisabled) {
        this.$emit('click', e);
      }
    },
  },
};