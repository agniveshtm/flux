/**
 * Check the format donut's interactions.
 *
 *   node scripts/ui/check-donut.js
 *
 * The donut is the app's only bulk format picker, so its behaviour is worth
 * pinning: a slice picks its format, the centre toggles between the image
 * and the video ring, and a slice can be reached and activated from the
 * keyboard alone.
 */
'use strict';

const { check, finish, instrumentFrontend, openPage } = require('./lib');

(async () => {
  const page = await openPage({ url: instrumentFrontend() });

  const state = `
    (function(){
      var svg = document.querySelector('.format-donut');
      return {
        centre: svg.parentElement.querySelector('button').textContent.trim(),
        slices: document.querySelectorAll('.format-donut path[role="option"]').length,
        ring: document.querySelectorAll('.format-donut circle').length,
        caption: svg.parentElement.parentElement.querySelector('p').textContent.trim(),
        selected: Array.prototype.map.call(
          document.querySelectorAll('.format-donut path[aria-selected="true"]'),
          function(p){ return p.getAttribute('aria-label'); }),
        rowTarget: window.__flux.files.value[0].targetFormat
      };
    })()
  `;

  try {
    await page.evaluate(`
      (function(){
        var f = window.__flux;
        ['a.jpg','b.png'].forEach(function(n, i){
          f.files.value.push({
            id: 'f' + i, name: n, size: 1, type: 'image/jpeg',
            path: 'C:/' + n, objectUrl: null, targetFormat: 'png',
            status: 'ready', progress: 0
          });
        });
        return true;
      })()
    `);
    await new Promise((resolve) => setTimeout(resolve, 400));

    const initial = await page.evaluate(state);
    check('the ring shows a slice per image format', initial.slices > 0,
      'the ring has no slices');
    check('the centre starts on the image ring', initial.centre === 'IMG',
      `the centre reads "${initial.centre}"`);
    check('the first row is preselected', initial.rowTarget === 'png',
      `the row targets "${initial.rowTarget}"`);

    // Click a slice.
    await page.evaluate(`
      (function(){
        var options = document.querySelectorAll('.format-donut path[role="option"]');
        for (var i = 0; i < options.length; i++) {
          if (options[i].getAttribute('aria-label') === 'ICO') {
            options[i].dispatchEvent(new MouseEvent('click', { bubbles: true }));
            return true;
          }
        }
        return false;
      })()
    `);
    await new Promise((resolve) => setTimeout(resolve, 300));
    const picked = await page.evaluate(state);
    check('clicking a slice selects it',
      picked.selected.length === 1 && picked.selected[0] === 'ICO',
      `selected: ${JSON.stringify(picked.selected)}`);
    check('the caption follows the selected slice', picked.caption === 'ICO',
      `the caption reads "${picked.caption}"`);
    check('the rows follow the selected slice', picked.rowTarget === 'ico',
      `the row targets "${picked.rowTarget}"`);

    // Toggle to the video ring and back.
    await page.evaluate(
      "document.querySelector('.format-donut').parentElement.querySelector('button').click()"
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    const video = await page.evaluate(state);
    check('the centre toggles to the video ring', video.centre === 'VID',
      `the centre reads "${video.centre}"`);
    check('the video ring has no slices yet', video.slices === 0,
      `${video.slices} slices`);
    check('the video ring still reads as a ring', video.ring === 1,
      `${video.ring} circles`);
    check('the video ring says so', video.caption === 'Video',
      `the caption reads "${video.caption}"`);

    await page.evaluate(
      "document.querySelector('.format-donut').parentElement.querySelector('button').click()"
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    const back = await page.evaluate(state);
    check('the centre toggles back to the image ring', back.centre === 'IMG',
      `the centre reads "${back.centre}"`);
    check('the image slices come back', back.slices === initial.slices,
      `${back.slices} slices, expected ${initial.slices}`);

    // Keyboard: focus a slice and activate it.
    await page.evaluate(`
      (function(){
        var options = document.querySelectorAll('.format-donut path[role="option"]');
        options[0].focus();
        return true;
      })()
    `);
    await new Promise((resolve) => setTimeout(resolve, 200));
    const focused = await page.evaluate(
      "document.activeElement ? document.activeElement.getAttribute('aria-label') : null"
    );
    check('a slice can be focused', !!focused, 'nothing took the focus');

    await page.evaluate(
      "document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))"
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    const entered = await page.evaluate(state);
    check('Enter activates the focused slice',
      entered.selected.length === 1 && entered.selected[0] === focused,
      `selected: ${JSON.stringify(entered.selected)}, focused: ${focused}`);
  } finally {
    page.close();
  }

  finish();
})().catch((error) => {
  console.error('FAILED', error);
  process.exit(1);
});
