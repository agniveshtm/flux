/**
 * Flux App Header Component
 * Wordmark on left, theme toggle and settings on right
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
  emits: ['toggle-theme', 'open-settings'],
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
        <button
          type="button"
          class="btn-ghost p-2 rounded-lg"
          @click="$emit('open-settings')"
          aria-label="Settings"
          title="Settings"
        >
          <svg class="w-5 h-5 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>
    </header>
  `,
};