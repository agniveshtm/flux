/**
 * Flux App Header Component
 * Wordmark on left, theme toggle on right
 */
window.Flux = window.Flux || {};
window.Flux.AppHeader = {
  name: 'AppHeader',
  components: {
    ThemeToggle: window.Flux.ThemeToggle,
  },
  props: {
    theme: {
      type: String,
      required: true,
    },
  },
  emits: ['toggle-theme'],
  template: `
    <header class="h-14 px-4 flex items-center justify-between border-b border-line bg-surface sticky top-0 z-10">
      <div class="flex items-center gap-3">
        <span class="text-xl font-semibold text-accent select-none" aria-label="Flux">Flux</span>
      </div>
      <div class="flex items-center gap-2">
        <ThemeToggle
          :theme="theme"
          @toggle="$emit('toggle-theme')"
        />
      </div>
    </header>
  `,
};