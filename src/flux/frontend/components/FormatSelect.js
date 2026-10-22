/**
 * Flux Format Select Component
 *
 * A tile-grid picker for a row's target format. It replaces the native
 * <select>, which WebView2 draws as an OS-shaped grey box: it was the one
 * control in the row that looked like it belonged to a different app, and it
 * had no room to show what the format actually is.
 *
 * The options are still the row's valid targets, resolved from the app-wide
 * input->target matrix by FileRow - this component does not know the matrix
 * and must not re-derive it. The tile faces are the format's extension, the
 * same language the format-tile strip above the list uses.
 *
 * The popover is position: fixed and placed from the button's rect: the file
 * list sits inside two overflow containers (the card is overflow-hidden, the
 * table body is overflow-x-auto) and an absolutely positioned panel would be
 * clipped by both.
 */
window.Flux = window.Flux || {};
window.Flux.FormatSelect = {
  name: 'FormatSelect',
  props: {
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
  data() {
    return {
      open: false,
      // Roving focus index within the option grid.
      activeIndex: -1,
      // The button's viewport rect, captured when the popover opens and
      // refreshed whenever the page scrolls or resizes.
      anchor: null,
    };
  },
  computed: {
    items() {
      return (this.options || []).map((fmt) => {
        const id = String(fmt);
        return {
          value: id,
          label: id.toUpperCase(),
          // Four-character extensions need a smaller face to stay inside the
          // tile - the same rule the format-tile strip uses.
          sizeClass: id.length > 3
            ? 'text-xs tracking-tighter'
            : (id.length > 2 ? 'text-sm' : 'text-base'),
        };
      });
    },
    currentItem() {
      return this.items.find((item) => item.value === this.targetFormat) || null;
    },
    canOpen() {
      return !this.disabled && this.items.length > 0;
    },
    // Placement for the fixed-position popover. Two columns of 49px tiles.
    popStyle() {
      if (!this.anchor) return { display: 'none' };
      const panelWidth = 132;
      const rows = Math.ceil(this.items.length / 2);
      const panelHeight = 16 + rows * 57;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      let left = this.anchor.left;
      let top = this.anchor.bottom + 6;
      if (left + panelWidth > vw - 8) left = vw - panelWidth - 8;
      if (left < 8) left = 8;
      if (top + panelHeight > vh - 8) {
        // Not enough room below: open above the button instead.
        top = Math.max(8, this.anchor.top - panelHeight - 6);
      }
      return { left: left + 'px', top: top + 'px', width: panelWidth + 'px' };
    },
  },
  mounted() {
    // mousedown, not click: a press that starts outside the panel and ends
    // inside it still has to dismiss it.
    document.addEventListener('mousedown', this.onOutsidePress);
    window.addEventListener('resize', this.reposition);
    // capture: true so the list's own scroll is caught as well - the popover
    // is fixed, so it has to follow the button when the table scrolls.
    document.addEventListener('scroll', this.reposition, true);
  },
  beforeUnmount() {
    document.removeEventListener('mousedown', this.onOutsidePress);
    window.removeEventListener('resize', this.reposition);
    document.removeEventListener('scroll', this.reposition, true);
  },
  methods: {
    toggle() {
      if (this.open) this.closeMenu(false);
      else this.openMenu(false);
    },
    openMenu(focusSelected) {
      if (!this.canOpen) return;
      this.anchor = this.$refs.button.getBoundingClientRect();
      this.open = true;
      const index = this.items.findIndex((item) => item.value === this.targetFormat);
      this.activeIndex = focusSelected && index >= 0 ? index : 0;
      this.$nextTick(() => this.focusActive());
    },
    closeMenu(refocus) {
      this.open = false;
      this.activeIndex = -1;
      if (refocus && this.$refs.button) this.$refs.button.focus();
    },
    reposition() {
      if (!this.open || !this.$refs.button) return;
      this.anchor = this.$refs.button.getBoundingClientRect();
    },
    onOutsidePress(event) {
      if (!this.open) return;
      if (this.$refs.root && this.$refs.root.contains(event.target)) return;
      this.closeMenu(false);
    },
    focusActive() {
      const els = this.$refs.optionEls;
      if (els && els[this.activeIndex]) els[this.activeIndex].focus();
    },
    move(delta) {
      if (!this.open) {
        this.openMenu(true);
        return;
      }
      const count = this.items.length;
      if (!count) return;
      this.activeIndex = (this.activeIndex + delta + count) % count;
      this.focusActive();
    },
    select(value) {
      this.$emit('update:targetFormat', value);
      this.closeMenu(true);
    },
    onOptionKeydown(event) {
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          this.move(1);
          break;
        case 'ArrowUp':
          event.preventDefault();
          this.move(-1);
          break;
        case 'Home':
          event.preventDefault();
          this.activeIndex = 0;
          this.focusActive();
          break;
        case 'End':
          event.preventDefault();
          this.activeIndex = this.items.length - 1;
          this.focusActive();
          break;
        case 'Escape':
          event.preventDefault();
          this.closeMenu(true);
          break;
        case 'Tab':
          // Let the tab move on, but do not leave the popover hanging open.
          this.closeMenu(false);
          break;
        default:
          break;
      }
    },
  },
  template: `
    <div ref="root" class="relative">
      <button
        ref="button"
        type="button"
        class="format-pick flex items-center gap-2 w-full px-3 h-9 rounded-lg bg-surface text-sm font-semibold tracking-wide transition-colors duration-150"
        :class="[
          open ? 'border-accent text-accent' : 'border border-line text-fg hover:border-accent hover:text-accent',
          { 'opacity-50 cursor-not-allowed': !canOpen },
        ]"
        :disabled="!canOpen"
        :aria-expanded="open"
        aria-haspopup="listbox"
        :aria-label="'Target format: ' + (currentItem ? currentItem.label : 'none available')"
        :title="currentItem ? 'Convert to ' + currentItem.label : 'No target formats available'"
        @click="toggle"
        @keydown.down.prevent="openMenu(true)"
        @keydown.up.prevent="openMenu(true)"
      >
        <span class="flex-1 text-left truncate">
          {{ currentItem ? currentItem.label : (items.length ? '-' : 'No targets') }}
        </span>
        <svg
          class="w-3.5 h-3.5 flex-shrink-0 transition-transform duration-150"
          :class="{ 'rotate-180': open }"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <div
        v-if="open"
        class="format-pop fixed z-40 rounded-lg border border-line bg-surface p-3"
        :style="popStyle"
        @keydown="onOptionKeydown"
      >
        <div class="grid grid-cols-2 gap-2" role="listbox" aria-label="Target format">
          <button
            v-for="(item, index) in items"
            :key="item.value"
            ref="optionEls"
            type="button"
            role="option"
            :aria-selected="item.value === targetFormat"
            :tabindex="index === activeIndex ? 0 : -1"
            class="format-tile flex-shrink-0 w-14 h-14 rounded-lg flex items-center justify-center font-bold transition-colors duration-150 active:scale-95"
            :class="item.value === targetFormat
              ? 'bg-accent text-on-accent border border-accent'
              : 'bg-surface-2 text-fg border border-line hover:border-accent hover:text-accent'"
            @click="select(item.value)"
          >
            <span :class="item.sizeClass">{{ item.label }}</span>
          </button>
        </div>
      </div>
    </div>
  `,
};
