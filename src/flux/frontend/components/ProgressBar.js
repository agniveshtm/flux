/**
 * Flux Progress Bar Component
 * Crimson progress bar with success/error states
 */
window.Flux = window.Flux || {};
window.Flux.ProgressBar = {
  name: 'ProgressBar',
  props: {
    progress: {
      type: Number,
      default: 0,
    },
    status: {
      type: String,
      default: 'ready', // ready, converting, done, error
    },
  },
  template: `
    <div class="progress-bar w-full" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100" :aria-label="progressLabel">
      <div
        class="progress-bar-fill"
        :class="fillClass"
        :style="{ width: progress + '%' }"
      ></div>
    </div>
  `,
  computed: {
    fillClass() {
      if (this.status === 'done') return 'success';
      if (this.status === 'error') return 'error';
      return '';
    },
    progressLabel() {
      switch (this.status) {
        case 'converting':
          return `Converting, ${this.progress}% complete`;
        case 'done':
          return 'Conversion complete';
        case 'error':
          return 'Conversion failed';
        default:
          return 'Ready to convert';
      }
    },
  },
};