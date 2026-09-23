/**
 * Flux Branding Component
 * Logo + wordmark in content area, theme-aware colors
 */
window.Flux = window.Flux || {};
window.Flux.Branding = {
  name: 'Branding',
  props: {
    theme: {
      type: String,
      required: true,
    },
  },
  data() {
    return {
      logoLoaded: false,
      logoError: false,
    };
  },
  computed: {
    logoSrc() {
      // Light mark on dark surfaces, dark mark on light surfaces.
      return this.theme === 'dark' ? '../assets/logo-light.png' : '../assets/logo-dark.png';
    },
  },
  watch: {
    logoSrc() {
      // Re-run the fade-in for the swapped asset so the old colour never flashes.
      this.logoLoaded = false;
      this.logoError = false;
    },
  },
  template: `
    <div class="flex items-center justify-center gap-4 py-4 transition-colors duration-200">
      <img
        v-if="!logoError"
        :src="logoSrc"
        alt=""
        class="h-14 w-auto transition-opacity duration-300"
        :class="{ 'opacity-0': !logoLoaded, 'opacity-100': logoLoaded }"
        @load="logoLoaded = true"
        @error="logoError = true"
        aria-hidden="true"
      />
      <span
        class="text-4xl font-semibold leading-none tracking-tight select-none transition-colors duration-200"
        :class="theme === 'dark' ? 'text-white' : 'text-black'"
      >
        flux
      </span>
    </div>
  `,
};