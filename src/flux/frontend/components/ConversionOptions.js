/**
 * Flux Conversion Options Component
 * Quality slider for lossy targets, dithering toggle for GIF
 *
 * Which controls are shown is decided by the caller from the targets actually
 * selected across the pending rows: offering a GIF-only control while every row
 * targets PNG would be noise, and hiding the quality slider for AVIF - the
 * format most likely to be resized for size - would defeat the point of
 * exposing it.
 */
window.Flux = window.Flux || {};
window.Flux.ConversionOptions = {
  name: 'ConversionOptions',
  props: {
    // A null quality means "the format's own default" - see the note on
    // qualityOverride in main.js.
    quality: {
      type: Number,
      default: null,
      validator: (value) => value === null || (value >= 0 && value <= 100),
    },
    dither: {
      type: Boolean,
      default: true,
    },
    showQuality: {
      type: Boolean,
      default: false,
    },
    showDither: {
      type: Boolean,
      default: false,
    },
    disabled: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['update:quality', 'update:dither', 'reset-quality'],
  computed: {
    // The slider always shows a position, so while nothing has been overridden
    // it rests at the same default the encoders use. It reads "Default" rather
    // than a number that is not actually in effect.
    sliderValue() {
      return this.quality === null ? 80 : this.quality;
    },
    qualityLabel() {
      return this.quality === null ? 'Default' : String(this.quality);
    },
  },
  template: `
    <div
      v-if="showQuality || showDither"
      class="flex items-center gap-5 px-4 py-2 border-t border-line bg-surface flex-wrap"
    >
      <div v-if="showQuality" class="flex items-center gap-2">
        <label for="flux-quality" class="text-xs text-muted whitespace-nowrap">Quality</label>
        <input
          id="flux-quality"
          type="range"
          min="0"
          max="100"
          step="5"
          class="input-range w-32"
          :value="sliderValue"
          :disabled="disabled"
          @input="$emit('update:quality', Number($event.target.value))"
        />
        <span class="text-xs text-fg tabular-nums w-14" aria-live="polite">{{ qualityLabel }}</span>
        <button
          v-if="quality !== null"
          type="button"
          class="btn-ghost text-xs px-2 py-1"
          :disabled="disabled"
          @click="$emit('reset-quality')"
        >
          Reset
        </button>
      </div>

      <div v-if="showDither" class="flex items-center gap-2">
        <input
          id="flux-dither"
          type="checkbox"
          class="input-checkbox"
          :checked="dither"
          :disabled="disabled"
          @change="$emit('update:dither', $event.target.checked)"
        />
        <label for="flux-dither" class="text-xs text-muted whitespace-nowrap">
          Dither colours
        </label>
      </div>
    </div>
  `,
};
