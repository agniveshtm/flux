/**
 * Flux Update Bell Component
 * Bell-shaped header button with a tiny yellow "!" badge when a newer GitHub
 * release is available. Clicking opens a popover card driven by props from
 * App:
 *   - idle:        current/latest rows, release size, Download update
 *   - downloading: progress bar with percent, transfer speed, done/total bytes
 *   - downloaded:  Restart & update (runs the downloaded setup, closes the app)
 * Dismiss hides the badge for this session only; Mark as read (and the
 * "Mark all as read" pill) persist the seen version so the badge stays away
 * across launches. The bell itself always reopens the card.
 */
window.Flux = window.Flux || {};
window.Flux.UpdateBell = {
  name: 'UpdateBell',
  props: {
    // Latest checkForUpdate payload, or null before the first check lands.
    update: { type: Object, default: null },
    // Whether the yellow exclamation badge shows on the bell.
    badge: { type: Boolean, default: false },
    // checking | idle | downloading | downloaded | installing | error
    state: { type: String, default: 'idle' },
    progress: { type: Number, default: 0 },
    // Bytes received / expected, pushed with each flux-update-progress event.
    received: { type: Number, default: 0 },
    total: { type: Number, default: 0 },
    error: { type: String, default: '' },
    checkError: { type: String, default: '' },
    isNative: { type: Boolean, default: false },
  },
  emits: ['check', 'download', 'install', 'dismiss', 'mark-read'],
  data() {
    return {
      open: false,
      // Smoothed download speed in bytes/sec (EMA over progress samples).
      speed: 0,
      speedTick: null,
    };
  },
  computed: {
    updateAvailable() {
      return Boolean(this.update && this.update.available);
    },
    heading() {
      if (this.updateAvailable) return 'Update Available';
      if (!this.isNative) return 'Updates';
      if (this.state === 'checking') return 'Checking for updates';
      if (this.checkError) return 'Could not check for updates';
      return 'You are up to date';
    },
    bellLabel() {
      if (this.badge) return 'Updates available';
      return this.updateAvailable ? 'Update options' : 'Update status';
    },
    percent() {
      return Math.round(this.progress);
    },
    // Content-Length once streaming; the release asset size before that.
    displayTotal() {
      return this.total || (this.update && this.update.assetSize) || 0;
    },
    sizeLabel() {
      const size = (this.update && this.update.assetSize) || 0;
      return size > 0 ? this.formatBytes(size) : '';
    },
    releaseLabel() {
      return this.update ? `Flux v${this.update.latestVersion}` : '';
    },
    transferLabel() {
      if (!this.displayTotal || !this.received) return '';
      return `${this.formatBytes(this.received)} / ${this.formatBytes(this.displayTotal)}`;
    },
    speedLabel() {
      return `${this.formatBytes(this.speed)}/s`;
    },
  },
  watch: {
    open(isOpen) {
      // Listeners only live while the popover is open: the click that opens
      // it must not immediately close it, and outside clicks are the only
      // dismissal path besides Escape.
      if (isOpen) {
        document.addEventListener('click', this.onDocumentClick);
        document.addEventListener('keydown', this.onDocumentKeydown);
      } else {
        document.removeEventListener('click', this.onDocumentClick);
        document.removeEventListener('keydown', this.onDocumentKeydown);
      }
    },
    received(bytes) {
      // Speed from consecutive throttled progress events; an EMA keeps the
      // label from jittering on a single slow chunk.
      const now = Date.now();
      const prev = this.speedTick;
      if (prev && bytes > prev.bytes && now > prev.at) {
        const instant = ((bytes - prev.bytes) * 1000) / (now - prev.at);
        this.speed = this.speed > 0 ? this.speed * 0.6 + instant * 0.4 : instant;
      }
      this.speedTick = { bytes, at: now };
    },
    state(next) {
      if (next !== 'downloading') {
        this.speed = 0;
        this.speedTick = null;
      }
    },
  },
  beforeUnmount() {
    document.removeEventListener('click', this.onDocumentClick);
    document.removeEventListener('keydown', this.onDocumentKeydown);
  },
  methods: {
    toggle() {
      this.open = !this.open;
    },
    close() {
      this.open = false;
    },
    onDocumentClick(event) {
      // $el wraps both the button and the popover, so clicks inside never
      // count as "outside" - including the toggle click that just fired.
      if (this.open && !this.$el.contains(event.target)) this.open = false;
    },
    onDocumentKeydown(event) {
      if (event.key === 'Escape') this.open = false;
    },
    dismiss() {
      this.$emit('dismiss');
      this.close();
    },
    markRead() {
      this.$emit('mark-read');
      this.close();
    },
    // 24.6 MB / 960.0 KB/s style labels: one decimal above bytes, whole bytes.
    formatBytes(bytes) {
      const value = Number(bytes);
      if (!Number.isFinite(value) || value <= 0) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB'];
      let index = 0;
      let scaled = value;
      while (scaled >= 1024 && index < units.length - 1) {
        scaled /= 1024;
        index += 1;
      }
      return `${scaled.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
    },
  },
  template: `
    <div class="relative">
      <button
        type="button"
        class="btn-ghost p-2 rounded-lg relative"
        :aria-label="bellLabel"
        :title="bellLabel"
        :aria-expanded="open"
        @click="toggle"
      >
        <svg
          class="w-5 h-5 text-fg transition-opacity duration-200"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        <span v-if="badge" class="update-badge" aria-hidden="true">!</span>
      </button>

      <div
        v-if="open"
        class="absolute right-0 top-full mt-2 w-80 p-4 bg-surface border border-line rounded-lg shadow-lg z-20"
        role="dialog"
        aria-label="Update status"
      >
        <div class="flex items-start justify-between gap-2">
          <p class="text-base font-semibold text-fg">{{ heading }}</p>
          <button
            type="button"
            class="btn-ghost p-1 rounded flex-shrink-0"
            @click="close"
            aria-label="Close"
            title="Close"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Browser dev: there is no bridge, so there is nothing to check. -->
        <template v-if="!isNative">
          <p class="text-xs text-muted mt-2">Update checks run in the desktop app.</p>
        </template>

        <!-- Update available: version rows, release size, actions. -->
        <template v-else-if="updateAvailable">
          <div class="flex justify-end mt-2">
            <button type="button" class="update-pill" @click="markRead">Mark all as read</button>
          </div>

          <div class="mt-1">
            <div class="flex items-center justify-between text-sm">
              <span class="text-muted">Current</span>
              <span class="text-fg font-medium">v{{ update.currentVersion }}</span>
            </div>
            <div class="flex items-center justify-between text-sm mt-1">
              <span class="text-muted">Latest</span>
              <span class="text-accent font-medium">v{{ update.latestVersion }}</span>
            </div>
          </div>

          <p class="text-xs italic text-muted mt-3">{{ releaseLabel }}</p>
          <p v-if="sizeLabel" class="text-xs text-muted mt-1">{{ sizeLabel }}</p>

          <!-- Not started yet -->
          <template v-if="state === 'idle' || state === 'checking'">
            <button type="button" class="btn-primary w-full mt-3" @click="$emit('download')">
              Download update
            </button>
          </template>

          <!-- Downloading: bar, percent + speed, transferred/total -->
          <template v-else-if="state === 'downloading'">
            <div class="mt-3">
              <div
                class="progress-bar w-full"
                role="progressbar"
                :aria-valuenow="percent"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-label="Update download progress"
              >
                <div class="progress-bar-fill" :style="{ width: percent + '%' }"></div>
              </div>
              <div class="flex items-center justify-between mt-1.5 text-xs">
                <span class="font-semibold text-fg">{{ percent }}%</span>
                <span class="text-muted">{{ speedLabel }}</span>
              </div>
              <p v-if="transferLabel" class="text-xs text-muted text-center mt-1">{{ transferLabel }}</p>
            </div>
          </template>

          <template v-else-if="state === 'downloaded' || state === 'installing'">
            <p class="text-xs text-muted mt-2">
              Ready to install. Flux will restart on v{{ update.latestVersion }}.
            </p>
            <button
              type="button"
              class="btn-primary w-full mt-3"
              :disabled="state === 'installing'"
              @click="$emit('install')"
            >
              {{ state === 'installing' ? 'Restarting...' : 'Restart & update' }}
            </button>
          </template>

          <template v-else-if="state === 'error'">
            <p class="text-xs text-accent mt-3">{{ error }}</p>
            <button type="button" class="btn-primary w-full mt-3" @click="$emit('download')">
              Retry download
            </button>
          </template>

          <!-- Shared footer across every available-update state. -->
          <div class="flex gap-2 mt-3">
            <button type="button" class="btn-ghost border border-line flex-1 text-sm" @click="dismiss">
              Dismiss
            </button>
            <button type="button" class="btn-ghost border border-line flex-1 text-sm" @click="markRead">
              Mark as read
            </button>
          </div>
        </template>

        <template v-else-if="state === 'checking'">
          <p class="text-xs text-muted mt-2">One moment.</p>
        </template>

        <!-- Up to date; a failed check reads the same way, with a retry.
             The heading itself already lives in the card header. -->
        <template v-else>
          <p class="text-xs text-muted mt-2">
            {{ checkError || ('Flux v' + (update ? update.currentVersion : '') + ' is the latest version.') }}
          </p>
          <button type="button" class="btn-ghost w-full mt-3" @click="$emit('check')">Check again</button>
        </template>
      </div>
    </div>
  `,
};
