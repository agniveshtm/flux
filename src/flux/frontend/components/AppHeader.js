/**
 * Flux App Header Component
 * Wordmark on left, theme toggle on right
 */
window.Flux = window.Flux || {};
window.Flux.AppHeader = {
  name: 'AppHeader',
  components: {
    ThemeToggle: window.Flux.ThemeToggle,
    UpdateBell: window.Flux.UpdateBell,
  },
  props: {
    theme: {
      type: String,
      required: true,
    },
    update: { type: Object, default: null },
    updateBadge: { type: Boolean, default: false },
    updateState: { type: String, default: 'idle' },
    updateProgress: { type: Number, default: 0 },
    updateReceived: { type: Number, default: 0 },
    updateTotal: { type: Number, default: 0 },
    updateError: { type: String, default: '' },
    updateCheckError: { type: String, default: '' },
    isNative: { type: Boolean, default: false },
  },
  emits: [
    'toggle-theme',
    'update-check',
    'update-download',
    'update-install',
    'update-dismiss',
    'update-mark-read',
  ],
  template: `
    <header class="h-14 px-4 flex items-center justify-between border-b border-line bg-surface sticky top-0 z-10">
      <div class="flex items-center gap-3">
        <span class="text-xl font-semibold text-accent select-none" aria-label="Flux">Flux</span>
      </div>
      <div class="flex items-center gap-2">
        <UpdateBell
          :update="update"
          :badge="updateBadge"
          :state="updateState"
          :progress="updateProgress"
          :received="updateReceived"
          :total="updateTotal"
          :error="updateError"
          :check-error="updateCheckError"
          :is-native="isNative"
          @check="$emit('update-check')"
          @download="$emit('update-download')"
          @install="$emit('update-install')"
          @dismiss="$emit('update-dismiss')"
          @mark-read="$emit('update-mark-read')"
        />
        <ThemeToggle
          :theme="theme"
          @toggle="$emit('toggle-theme')"
        />
      </div>
    </header>
  `,
};