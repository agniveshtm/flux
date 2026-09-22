/**
 * Flux Format Select Component
 * Dropdown for target format, only valid targets for input type
 */
window.Flux = window.Flux || {};
window.Flux.FormatSelect = {
  name: 'FormatSelect',
  props: {
    inputFormat: {
      type: String,
      required: true,
    },
    targetFormat: {
      type: String,
      required: true,
    },
    disabled: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['update:targetFormat'],
  computed: {
    options() {
      const formatMap = {
        jpg: ['png', 'webp'],
        jpeg: ['png', 'webp'],
        png: ['jpg', 'webp'],
        webp: ['jpg', 'png'],
      };
      const key = this.inputFormat.toLowerCase();
      const targets = formatMap[key] || [];
      return targets.map(fmt => ({
        value: fmt,
        label: fmt.toUpperCase(),
      }));
    },
  },
  template: `
    <select
      class="input-select w-auto min-w-[100px]"
      :value="targetFormat"
      @change="$emit('update:targetFormat', $event.target.value)"
      :disabled="disabled || options.length === 0"
      aria-label="Target format"
    >
      <option v-for="opt in options" :key="opt.value" :value="opt.value">
        {{ opt.label }}
      </option>
      <option v-if="options.length === 0" value="" disabled>
        No targets
      </option>
    </select>
  `,
};