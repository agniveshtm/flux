/**
 * Flux Format Donut Component
 *
 * The format picker that sits beside the drop area: a ring of slices, one
 * per format the backend can write, with the kind of format (image, video)
 * chosen by the label in the middle.
 *
 * A row of format chips was the previous answer and it did not survive
 * contact with Phase 2: image formats plus video formats in one line is a
 * long, generic list. A ring has room for both - the slices are grouped by
 * kind, and the centre toggles between them - so adding video formats
 * changes the ring rather than doubling the row.
 *
 * The formats and their kinds are passed in, never listed here: they come
 * from the backend's getSupportedFormats(), which reports the kind from the
 * converter that writes each format. A format the converter cannot write is
 * never offered, so the video half stays empty until a video converter is
 * actually registered, rather than advertising formats the app cannot
 * produce.
 */
window.Flux = window.Flux || {};
window.Flux.FormatDonut = {
  name: 'FormatDonut',
  props: {
    // Output formats the backend can write, already normalized.
    formats: {
      type: Array,
      default: () => [],
    },
    // format -> kind ('image', 'video'), as reported by the backend.
    kinds: {
      type: Object,
      default: () => ({}),
    },
    // The format currently targeted.
    active: {
      type: String,
      default: '',
    },
    disabled: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['select'],
  data() {
    return {
      // Which kind the ring is showing. 'image' is the default because that
      // is the only kind the app can convert today.
      mode: 'image',
      // The slice the pointer is over, if any. It takes the caption over
      // from the selected format while it is being pointed at.
      hovered: '',
      // The rendered size of the ring, in pixels. The SVG works in its own
      // 100x100 units; this only sets how big it is on screen.
      size: 170,
      // The ring's geometry, in the SVG's own 100x100 units. These live in
      // data() rather than in methods: Vue only binds function entries from
      // methods onto the instance, so plain numbers there would come back
      // undefined.
      //
      // The band between the two radii is the slice's thickness, and it is
      // what the label has to sit in - so the inner radius is pulled in to
      // give the slices room rather than shrinking the label.
      outerRadius: 47,
      innerRadius: 24,
      centreX: 50,
      centreY: 50,
    };
  },
  computed: {
    // The formats of each kind, in the order the backend listed them.
    groups() {
      const byKind = {};
      (this.formats || []).forEach((format) => {
        const id = String(format);
        const kind = this.kinds[id] || 'image';
        if (!byKind[kind]) byKind[kind] = [];
        byKind[kind].push(id);
      });
      return byKind;
    },
    currentFormats() {
      return this.groups[this.mode] || [];
    },
    // One colour per format, assigned across every format the backend
    // reports, so no two formats ever read as the same colour and a format
    // keeps its colour in both kinds.
    colorMap() {
      const all = (this.formats || []).map(String);
      // Evenly spaced hues give the widest possible spread, and each format
      // takes the slot nearest its own hashed hue - so the palette is tied
      // to the format rather than to its position in the list.
      const slots = Array.from({ length: all.length }, (_, i) => (i + 0.5) * (360 / all.length));
      const taken = new Set();
      const map = {};
      all.forEach((id) => {
        const preferred = this.hueFor(id);
        let chosen = 0;
        let bestDistance = Infinity;
        slots.forEach((hue, index) => {
          if (taken.has(index)) return;
          const gap = Math.abs(hue - preferred);
          const distance = Math.min(gap, 360 - gap);
          if (distance < bestDistance) {
            bestDistance = distance;
            chosen = index;
          }
        });
        taken.add(chosen);
        const hue = slots[chosen];
        map[id] = {
          // A vivid tint of that hue with a deep version of the *same* hue as
          // the label - which keeps every label at 5.5:1 or better, where a
          // single label colour (white on a yellow slice) would fall to 2.5:1.
          background: `hsl(${hue}, 88%, 74%)`,
          label: `hsl(${hue}, 90%, 18%)`,
        };
      });
      return map;
    },
    // One slice per format of the current kind.
    slices() {
      const ids = this.currentFormats;
      const count = ids.length;
      if (!count) return [];

      const midRadius = (this.outerRadius + this.innerRadius) / 2;
      const step = 360 / count;
      // A small gap between slices so they read as separate formats.
      const gap = count > 1 ? Math.min(2.5, step * 0.08) : 0;

      return ids.map((id, index) => {
        const start = index * step + gap / 2;
        const end = (index + 1) * step - gap / 2;
        // A slice's chord is what has to hold its label, so the label size
        // follows the number of slices: a ring of seven can carry a readable
        // extension, a ring of twenty can only carry a hint.
        const chord = 2 * midRadius * Math.sin(Math.PI / count);
        const longest = Math.max(...ids.map((item) => item.length));
        const fontSize = Math.max(5, Math.min(9, chord / (longest * 0.62)));
        const [labelX, labelY] = this.pointOnCircle(midRadius, (start + end) / 2);
        const colors = this.colorMap[id] || { background: 'transparent', label: 'currentColor' };
        const selected = id === this.active;
        return {
          id,
          label: id.toUpperCase(),
          path: this.annulus(start, end),
          fill: colors.background,
          labelFill: colors.label,
          labelX,
          labelY,
          fontSize,
          selected,
        };
      });
    },    // The single-format case cannot be drawn as an arc (a full turn is not
    // a valid SVG arc), so it becomes a plain ring.
    isSingle() {
      return this.currentFormats.length === 1;
    },
    singleFill() {
      const id = this.currentFormats[0];
      if (!id) return 'transparent';
      return this.colorMap[id].background;
    },
    activeInMode() {
      return this.currentFormats.indexOf(this.active) !== -1;
    },
    caption() {
      if (this.hovered) return this.hovered.toUpperCase();
      if (this.activeInMode) return this.active.toUpperCase();
      return this.mode === 'video' ? 'Video' : 'Image';
    },
    detail() {
      const count = this.currentFormats.length;
      if (!count) {
        return this.mode === 'video'
          ? 'Video formats arrive with Phase 2'
          : 'No image formats available';
      }
      return `${count} ${this.mode} formats`;
    },
    centreLabel() {
      return this.mode === 'video' ? 'VID' : 'IMG';
    },
    centreTitle() {
      return this.mode === 'video'
        ? 'Showing video formats. Click for image formats.'
        : 'Showing image formats. Click for video formats.';
    },
  },
  methods: {
    // A stable per-format hue, seeded by the format's name and spread by
    // the golden angle.
    hueFor(id) {
      let hash = 0;
      for (let i = 0; i < id.length; i += 1) {
        hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
      }
      return Math.round((hash * 137.508) % 360);
    },
    // A point on a circle, measured from twelve o'clock.
    pointOnCircle(radius, degrees) {
      const radians = ((degrees - 90) * Math.PI) / 180;
      return [
        this.centreX + radius * Math.cos(radians),
        this.centreY + radius * Math.sin(radians),
      ];
    },
    // The path of one slice: an annular sector from start to end.
    annulus(start, end) {
      const large = end - start > 180 ? 1 : 0;
      const [x1, y1] = this.pointOnCircle(this.outerRadius, start);
      const [x2, y2] = this.pointOnCircle(this.outerRadius, end);
      const [x3, y3] = this.pointOnCircle(this.innerRadius, end);
      const [x4, y4] = this.pointOnCircle(this.innerRadius, start);
      const f = (n) => n.toFixed(2);
      return `M ${f(x1)} ${f(y1)} A ${this.outerRadius} ${this.outerRadius} 0 ${large} 1 ${f(x2)} ${f(y2)} `
        + `L ${f(x3)} ${f(y3)} A ${this.innerRadius} ${this.innerRadius} 0 ${large} 0 ${f(x4)} ${f(y4)} Z`;
    },
    toggleMode() {
      if (this.disabled) return;
      this.mode = this.mode === 'image' ? 'video' : 'image';
      this.hovered = '';
    },
    select(id) {
      if (this.disabled) return;
      this.$emit('select', id);
    },
  },
  template: `
    <div class="card flex flex-col items-center justify-center gap-1.5 px-6 py-3 min-w-0">
      <div class="relative flex-shrink-0" :style="{ width: size + 'px', height: size + 'px' }">
        <svg
          class="format-donut w-full h-full"
          viewBox="0 0 100 100"
          role="listbox"
          :aria-label="'Target format (' + mode + ')'"
        >
          <circle
            v-if="isSingle"
            :cx="centreX"
            :cy="centreY"
            :r="(outerRadius + innerRadius) / 2"
            fill="none"
            :stroke="singleFill"
            :stroke-width="outerRadius - innerRadius"
          />
          <!-- A kind with no formats yet still shows a ring, so the picker
               reads as a ring rather than as something that failed to load. -->
          <circle
            v-else-if="!slices.length"
            :cx="centreX"
            :cy="centreY"
            :r="(outerRadius + innerRadius) / 2"
            fill="none"
            stroke="var(--color-border)"
            :stroke-width="outerRadius - innerRadius"
            stroke-dasharray="4 4"
          />
          <template v-else>
            <path
              v-for="slice in slices"
              :key="slice.id"
              :d="slice.path"
              :fill="slice.fill"
              role="option"
              tabindex="0"
              :aria-selected="slice.selected"
              :aria-label="slice.label"
              class="cursor-pointer transition-opacity duration-150"
              :style="{ opacity: slice.selected || hovered ? 1 : 0.6 }"
              @click="select(slice.id)"
              @mouseenter="hovered = slice.id"
              @mouseleave="hovered = ''"
              @focus="hovered = slice.id"
              @blur="hovered = ''"
              @keydown.enter.prevent="select(slice.id)"
              @keydown.space.prevent="select(slice.id)"
            >
              <title>{{ slice.label }}</title>
            </path>
          </template>
          <text
            v-for="slice in slices"
            :key="'label-' + slice.id"
            :x="slice.labelX"
            :y="slice.labelY"
            :font-size="slice.fontSize"
            text-anchor="middle"
            dominant-baseline="central"
            class="pointer-events-none font-bold"
            :fill="slice.labelFill"
          >{{ slice.label }}</text>
        </svg>

        <!-- The centre is a real button: it is the kind toggle, and it has
             to be reachable by keyboard. -->
        <button
          type="button"
          class="absolute inset-0 m-auto h-[48px] w-[48px] rounded-full flex items-center justify-center text-xs font-bold tracking-widest text-muted transition-colors duration-150 hover:text-accent focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="disabled"
          :title="centreTitle"
          :aria-label="centreTitle"
          @click="toggleMode"
        >
          {{ centreLabel }}
        </button>
      </div>

      <!-- The name of the format under the pointer, and how many the
           current kind has. Under the ring rather than beside it, so the
           ring can sit dead centre in its wing. -->
      <div class="text-center min-w-0 max-w-full">
        <p class="text-xl font-semibold text-fg leading-none truncate">
          {{ caption }}
        </p>
        <p class="text-xs text-muted mt-1.5">
          {{ detail }}
        </p>
      </div>
    </div>
  `,
};
