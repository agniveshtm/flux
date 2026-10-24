/**
 * Mount the real, uninstrumented frontend and report what the browser says.
 *
 *   node scripts/ui/check-app.js
 *
 * This is the only check that runs the shipped files rather than the
 * instrumented copy, so it is the one that catches a missing asset, a
 * template that throws on mount, or a script that fails to load - the
 * things that would otherwise only show up in the packaged app. It reads the
 * app straight off disk over file://, exactly as the packaged app does.
 */
'use strict';

const { check, finish, openPage, repoFrontendUrl } = require('./lib');

(async () => {
  const page = await openPage({ url: repoFrontendUrl(), settle: 3000 });

  try {
    const problems = page.problems;
    check('the app mounts without console errors', problems.length === 0,
      problems.join('\n'));

    check('the app mounts into #app',
      await page.evaluate("!!document.querySelector('#app .drop-zone')"),
      'the drop zone is missing');

    check('the drop zone is rendered',
      await page.evaluate(`
        (function(){
          var zone = document.querySelector('.drop-zone');
          return zone ? Math.round(zone.getBoundingClientRect().height) > 0 : false;
        })()
      `),
      'the drop zone has no height');

    check('the format ring is rendered',
      await page.evaluate("!!document.querySelector('.format-donut')"),
      'the format ring is missing');

    check('the file list is rendered',
      await page.evaluate("!!document.querySelector('table')"),
      'the file list is missing');

    check('the empty state is shown',
      await page.evaluate(`
        (function(){
          var body = document.querySelector('tbody');
          return body ? body.textContent.trim().length > 0 : false;
        })()
      `),
      'the empty state is blank');

    // A native <select> would be the browser's own dropdown, which the
    // WebView2 shell cannot style to match the rest of the app.
    check('no native selects are left',
      await page.evaluate("document.querySelectorAll('select').length") === 0,
      'a native <select> is still in the page');

    // The branding logo resolves against ../assets/, so a broken copy of the
    // frontend loses it - which silently changes the height of the header.
    check('the branding logo loads',
      await page.evaluate(`
        (function(){
          var img = document.querySelector('img');
          if (!img) return false;
          return img.complete && img.naturalWidth > 0;
        })()
      `),
      'the logo did not load');
  } finally {
    page.close();
  }

  finish();
})().catch((error) => {
  console.error('FAILED', error);
  process.exit(1);
});
