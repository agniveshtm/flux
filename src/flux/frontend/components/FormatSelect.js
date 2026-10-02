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
    // Valid targets for this input, resolved by FileRow from the app-wide
    // input->target matrix. Passed in rather than re-derived here so the
    // conversion matrix has a single definition.
    options: {
      type: Array,
      default: () => [],
    },
    disabled: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['update:targetFormat'],
  computed: {
    selectOptions() {
      return this.options.map(fmt => ({
        value: fmt,
        label: fmt.toUpperCase(),
      }));
    },
  },
  template: `
    <select
      class="input-select w-auto min-w-[120px]"
      :value="targetFormat"
      @change="$emit('update:targetFormat', $event.target.value)"
      :disabled="disabled || selectOptions.length === 0"
      aria-label="Target format"
    >
      <option v-for="opt in selectOptions" :key="opt.value" :value="opt.value">
        {{ opt.label }}
      </option>
      <option v-if="selectOptions.length === 0" value="" disabled>
        No targets
      </option>
    </select>
  `,
};