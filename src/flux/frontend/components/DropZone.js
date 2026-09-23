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
      class="drop-zone flex-1 flex flex-col items-center justify-center p-6 min-h-[180px]"
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
        class="w-10 h-10 text-muted mb-3 transition-colors duration-150"
        :class="{ 'text-accent': isDragOver }"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
      <p class="text-base text-fg mb-1 text-center" v-if="!isDragOver">Drag and drop images here, or click to select</p>
      <p class="text-base text-accent font-medium mb-1 text-center" v-else>Drop files to convert</p>
      <p class="text-sm text-muted mb-4 text-center">Supports JPG, PNG, WebP</p>
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
      if (this.isDisabled) return;
      this.$emit('dragover', e);
    },
    onDragLeave(e) {
      e.preventDefault();
      e.stopPropagation();
      this.$emit('dragleave', e);
    },
    onDrop(e) {
      // preventDefault stops the browser from navigating to the dropped
      // file. stopPropagation is deliberately NOT called: pywebview's
      // Python-side document-level drop listener must still receive this
      // event - it is what delivers the dropped files' real paths back to
      // the app (see FluxAPI.attach_drop_listener).
      e.preventDefault();
      // Mid-conversion drops would add "ready" rows that no job covers and
      // stall checkAllComplete (every() never clears), so they are ignored.
      if (this.isDisabled) return;
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        this.$emit('drop', e, files);
      }
    },
    onClick(e) {
      if (!this.isDisabled) {
        this.$emit('click', e);
      }
    },
  },
};