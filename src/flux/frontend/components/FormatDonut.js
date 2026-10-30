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
    // Ring membership: { image: [formats], video: [formats] }, as reported
    // by the backend's getSupportedFormats().rings. GIF arrives in both
    // rings - image conversion from stills, video conversion from clips -
    // and that dual membership is the backend's answer, not a rule this
    // component may invent. Falls back to grouping formats by `kinds` when
    // an older payload has no rings key.
    rings: {
      type: Object,
      default: null,
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
      // 112x112 units (the ring plus the tick margin around it); this only
      // sets how big it is on screen.
      size: 224,
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
      // How far the crimson border sits inward from the slice's actual
      // edge, in the SVG's 100x100 units. Shared by the multi-slice rim
      // path and the single-format ring's rim circles.
      rimInset: 2,
      // The needle dot: a marker just outside the well at the marked
      // slice's mid-angle, inside the tick band. In the same units as the
      // radii above.
      needleRadius: 49.6,
      // True for the length of the ring-settle animation after a kind
      // switch, so the new slices animate in rather than snapping.
      switching: false,
      switchTimer: null,
    };
  },
  computed: {
    // The formats of each kind, in the order the backend listed them.
    groups() {
      if (this.rings && Array.isArray(this.rings.image)) {
        const byKind = {};
        Object.keys(this.rings).forEach((kind) => {
          byKind[kind] = (this.rings[kind] || []).map(String);
        });
        return byKind;
      }
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
    // keeps its colour in both kinds. The colour now lives in the slice's
    // rim rather than its fill: the wells are theme-coloured, and each
    // format's thin inset border carries a step of the crimson ramp.
    colorMap() {
      const all = (this.formats || []).map(String);
      // The assignment stays hash-stable (each format takes the free slot
      // nearest its own hashed position, so a format keeps its colour in
      // both rings); what fills a slot is a step of the crimson ramp below
      // rather than a slice of the rainbow wheel - the ring reads as one
      // brand object, and the label under the pointer carries identity.
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
        // The crimson ramp: saturated steps in the accent's own family -
        // from a bright crimson down to the deep active tone - drawn as
        // each slice's inset border, so the ring still reads as red in
        // both themes while the well beneath it flips dark to light.
        const t = all.length > 1 ? chosen / (all.length - 1) : 0;
        map[id] = `hsl(348, ${Math.round(78 + 14 * t)}%, ${Math.round(55 - 13 * t)}%)`;
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
      // A small gap between slices so they read as separate formats - a
      // touch wider than it was, since the softened corners below eat
      // slightly into it.
      const gap = count > 1 ? Math.min(3, step * 0.1) : 0;

      return ids.map((id, index) => {
        const start = index * step + gap / 2;
        const end = (index + 1) * step - gap / 2;
        // A slice's chord is what has to hold its label, so the label size
        // follows the number of slices: a ring of seven can carry a readable
        // extension, a ring of twenty can only carry a hint. The cap is low
        // enough that the words sit inside their wedge rather than filling
        // it, even once the ring is scaled up on screen.
        const chord = 2 * midRadius * Math.sin(Math.PI / count);
        const longest = Math.max(...ids.map((item) => item.length));
        const fontSize = Math.max(4.5, Math.min(7, chord / (longest * 0.62)));
        const mid = (start + end) / 2;
        const [labelX, labelY] = this.pointOnCircle(midRadius, mid);
        // The hover lift: the slice slides out along its own radius while
        // the pointer is on it, and its label and rim ride the same offset
        // (all three carry --lx/--ly; .format-donut-slice in input.css does
        // the rest).
        const radians = ((mid - 90) * Math.PI) / 180;
        const lift = 1.8;
        const rim = this.colorMap[id] || '#DC143C';
        const selected = id === this.active;
        return {
          id,
          label: id.toUpperCase(),
          path: this.annulus(start, end),
          rimPath: this.annulusInset(start, end),
          rim,
          mid,
          labelX,
          labelY,
          lx: `${(Math.cos(radians) * lift).toFixed(2)}px`,
          ly: `${(Math.sin(radians) * lift).toFixed(2)}px`,
          fontSize,
          selected,
        };
      });
    },    // The single-format case cannot be drawn as an arc (a full turn is not
    // a valid SVG arc), so it becomes a plain ring.
    isSingle() {
      return this.currentFormats.length === 1;
    },
    singleRim() {
      const id = this.currentFormats[0];
      if (!id) return '#DC143C';
      return this.colorMap[id] || '#DC143C';
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
    // Short radial ticks just outside the well, one per slice boundary, so
    // the ring reads as a dial rather than as loose wedges. The boundaries
    // sit at every step angle - the gaps are centred there.
    ticks() {
      const count = this.currentFormats.length;
      if (this.isSingle || count < 2) return [];
      const step = 360 / count;
      const from = this.outerRadius + 1.6;
      const to = from + 2.6;
      return Array.from({ length: count }, (_, k) => {
        const [x1, y1] = this.pointOnCircle(from, k * step);
        const [x2, y2] = this.pointOnCircle(to, k * step);
        const f = (n) => n.toFixed(2);
        return `M ${f(x1)} ${f(y1)} L ${f(x2)} ${f(y2)}`;
      });
    },
    // The colour dot beside the caption: the rim colour of the format the
    // caption is naming, so the words tie back to the ring's own identity.
    // Empty when the caption only names the kind (no selection in view).
    captionRim() {
      const id = this.hovered || (this.activeInMode ? this.active : '');
      return id ? (this.colorMap[id] || '#DC143C') : '';
    },
    // Where the bezel needle points: the mid-angle of the format the
    // caption is naming. Null when there is nothing to point at, and the
    // needle fades out.
    needleAngle() {
      const id = this.hovered || (this.activeInMode ? this.active : '');
      if (!id) return null;
      const slice = this.slices.find((item) => item.id === id);
      return slice ? slice.mid : null;
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
    // The slice's crimson border: the same wedge inset by rimInset on every
    // edge. The arcs just move in by rimInset; the radial edges are offset
    // by the angle whose chord reaches rimInset at that radius, so the
    // margin between border and actual edge stays the same width all the
    // way round instead of tapering toward the middle.
    annulusInset(start, end) {
      const chordAngle = (radius) =>
        (Math.asin(Math.min(1, this.rimInset / radius)) * 180) / Math.PI;
      let inset = this.rimInset;
      let outer = this.outerRadius - inset;
      let inner = this.innerRadius + inset;
      let phiOuter = chordAngle(outer);
      let phiInner = chordAngle(inner);
      // A slice under ~9 degrees wide would invert its own inset wedge;
      // back the border off rather than draw a crossed path.
      if (end - start < 2 * Math.max(phiOuter, phiInner)) {
        inset = this.rimInset / 2;
        outer = this.outerRadius - inset;
        inner = this.innerRadius + inset;
        phiOuter = chordAngle(outer);
        phiInner = chordAngle(inner);
      }
      const mid = (start + end) / 2;
      const from = Math.min(start + phiOuter, mid);
      const to = Math.max(end - phiOuter, mid);
      const fromIn = Math.min(start + phiInner, mid);
      const toIn = Math.max(end - phiInner, mid);
      const largeOuter = to - from > 180 ? 1 : 0;
      const largeInner = toIn - fromIn > 180 ? 1 : 0;
      const [x1, y1] = this.pointOnCircle(outer, from);
      const [x2, y2] = this.pointOnCircle(outer, to);
      const [x3, y3] = this.pointOnCircle(inner, toIn);
      const [x4, y4] = this.pointOnCircle(inner, fromIn);
      const f = (n) => n.toFixed(2);
      return `M ${f(x1)} ${f(y1)} A ${outer} ${outer} 0 ${largeOuter} 1 ${f(x2)} ${f(y2)} `
        + `L ${f(x3)} ${f(y3)} A ${inner} ${inner} 0 ${largeInner} 0 ${f(x4)} ${f(y4)} Z`;
    },
    toggleMode() {
      if (this.disabled) return;
      this.mode = this.mode === 'image' ? 'video' : 'image';
      this.hovered = '';
      // Let the new ring settle in rather than snap: the class rides the
      // svg for the length of the animation (see input.css).
      this.switching = true;
      clearTimeout(this.switchTimer);
      this.switchTimer = setTimeout(() => { this.switching = false; }, 260);
    },
    select(id) {
      if (this.disabled) return;
      this.$emit('select', id);
    },
  },
  beforeUnmount() {
    clearTimeout(this.switchTimer);
  },
  template: `
    <div class="card flex flex-col items-center justify-center gap-1.5 px-6 py-3 min-w-0">
      <div class="relative flex-shrink-0" :style="{ width: size + 'px', height: size + 'px' }">
        <svg
          class="format-donut w-full h-full"
          :class="{ 'is-switching': switching }"
          viewBox="-6 -6 112 112"
          role="listbox"
          :aria-label="'Target format (' + mode + ')'"
        >
          <template v-if="isSingle">
            <circle
              :cx="centreX"
              :cy="centreY"
              :r="(outerRadius + innerRadius) / 2"
              class="format-donut-single"
              :stroke-width="outerRadius - innerRadius"
            />
            <!-- The rim for the full ring: two circles, each offset inward
                 from the well's actual edge, so the same margin of dark
                 shows between border and edge as on a multi-slice ring. -->
            <circle
              :cx="centreX"
              :cy="centreY"
              :r="outerRadius - rimInset"
              class="format-donut-rim"
              :stroke="singleRim"
            />
            <circle
              :cx="centreX"
              :cy="centreY"
              :r="innerRadius + rimInset"
              class="format-donut-rim"
              :stroke="singleRim"
            />
          </template>
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
            <!-- The track: one faint full annulus under the slices, so the
                 gaps read as divisions on a single dial rather than as
                 floating wedges. -->
            <circle
              :cx="centreX"
              :cy="centreY"
              :r="(outerRadius + innerRadius) / 2"
              :stroke-width="outerRadius - innerRadius"
              class="format-donut-track"
            />
            <!-- Boundary ticks just outside the well, one per gap. -->
            <g class="format-donut-ticks" aria-hidden="true">
              <path v-for="(tick, i) in ticks" :key="'tick-' + i" :d="tick" />
            </g>
            <!-- The well: the slice's full shape, filled in the theme's own
                 background token, so it reads dark in dark mode and light
                 when the theme flips. The rim follows as its own path so
                 the border can sit inset from the well's edge with a margin
                 of the well showing on every side. -->
            <path
              v-for="slice in slices"
              :key="slice.id"
              :d="slice.path"
              role="option"
              tabindex="0"
              :aria-selected="slice.selected"
              :aria-label="slice.label"
              class="format-donut-slice cursor-pointer"
              :class="{
                'is-hovered': hovered === slice.id,
                'is-selected': slice.selected,
              }"
              :style="{
                '--lx': slice.lx,
                '--ly': slice.ly,
                opacity: (hovered === slice.id || slice.selected)
                  ? 1
                  : (hovered ? 0.55 : 0.75),
              }"
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
            <path
              v-for="slice in slices"
              :key="'rim-' + slice.id"
              :d="slice.rimPath"
              :stroke="slice.rim"
              aria-hidden="true"
              class="format-donut-rim pointer-events-none"
              :class="{
                'is-hovered': hovered === slice.id,
                'is-selected': slice.selected,
              }"
              :style="{
                '--lx': slice.lx,
                '--ly': slice.ly,
                opacity: (hovered === slice.id || slice.selected)
                  ? 1
                  : (hovered ? 0.55 : 0.75),
              }"
            />
          </template>
          <text
            v-for="slice in slices"
            :key="'label-' + slice.id"
            :x="slice.labelX"
            :y="slice.labelY"
            :font-size="slice.fontSize"
            text-anchor="middle"
            dominant-baseline="central"
            class="format-donut-label pointer-events-none font-bold"
            :class="{
              'is-hovered': hovered === slice.id,
              'is-selected': slice.selected,
            }"
            :style="{ '--lx': slice.lx, '--ly': slice.ly }"
          >{{ slice.label }}</text>
          <!-- A hairline frames the hub whenever a real ring is drawn. -->
          <circle
            v-if="slices.length"
            :cx="centreX"
            :cy="centreY"
            :r="innerRadius - 1.4"
            class="format-donut-hub"
            aria-hidden="true"
          />
          <!-- The needle: a dot that rides just outside the well at the
               mid-angle of the format the caption names, so it sweeps to
               whatever is hovered and settles on the selection when
               nothing is. -->
          <g
            v-if="slices.length"
            class="format-donut-needle"
            aria-hidden="true"
            :style="{
              transform: 'rotate(' + (needleAngle === null ? 0 : needleAngle) + 'deg)',
              opacity: needleAngle === null ? 0 : 1,
            }"
          >
            <circle
              :cx="centreX"
              :cy="centreY - needleRadius"
              r="1.4"
              :fill="captionRim || '#DC143C'"
            />
          </g>
        </svg>

        <!-- The centre is a real button: it is the kind toggle, and it has
             to be reachable by keyboard. It sits in the hub as a puck. -->
        <button
          type="button"
          class="absolute inset-0 m-auto h-16 w-16 rounded-full flex items-center justify-center text-xs font-bold tracking-widest bg-surface-2 ring-1 ring-line text-muted shadow-sm transition duration-150 hover:text-accent hover:ring-accent hover:bg-accent-tint disabled:opacity-50 disabled:cursor-not-allowed focus-visible:ring-2 focus-visible:ring-accent"
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
        <p class="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted mb-1">
          Target
        </p>
        <p class="format-donut-caption text-xl font-semibold text-fg leading-none truncate flex items-center justify-center gap-2">
          <span
            v-if="captionRim"
            class="h-2 w-2 flex-shrink-0 rounded-full"
            :style="{ backgroundColor: captionRim }"
          ></span>
          {{ caption }}
        </p>
        <p class="text-xs text-muted mt-1.5">
          {{ detail }}
        </p>
      </div>
    </div>
  `,
};
