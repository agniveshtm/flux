/**
 * Check the format donut's interactions.
 *
 *   node scripts/ui/check-donut.js
 *
 * The donut is the app's only bulk format picker, so its behaviour is worth
 * pinning: a slice picks its format, the centre cycles through the image,
 * video and audio rings, and a slice can be reached and activated from the
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
        // Only the empty-kind placeholder is a dashed circle; the track and
        // hub hairline are solid dressing on a real ring.
        placeholder: document.querySelectorAll(
          '.format-donut circle[stroke-dasharray]').length,
        caption: svg.parentElement.parentElement.querySelector(
          '.format-donut-caption').textContent.trim(),
        labels: Array.prototype.map.call(
          document.querySelectorAll('.format-donut path[role="option"]'),
          function(p){ return p.getAttribute('aria-label'); }),
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

    // Cycle to the video ring.
    await page.evaluate(
      "document.querySelector('.format-donut').parentElement.querySelector('button').click()"
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    const video = await page.evaluate(state);
    check('the centre toggles to the video ring', video.centre === 'VID',
      `the centre reads "${video.centre}"`);
    // The video ring carries every backend video output plus GIF - gif ->
    // mp4 is a video conversion, and a video -> gif clip is a video
    // conversion too. The ring is no longer the single-circle placeholder it
    // was while MP4 was the only output.
    check('the video ring shows every video target',
      JSON.stringify(video.labels) === JSON.stringify(['AVI', 'GIF', 'MKV', 'MOV', 'MP4', 'WEBM']),
      `the video ring shows ${JSON.stringify(video.labels)}`);
    check('the video ring draws slices, not a placeholder circle', video.placeholder === 0,
      `${video.placeholder} placeholder circles`);
    check('the video ring says so', video.caption === 'Video',
      `the caption reads "${video.caption}"`);

    // Then the audio ring (MP3/WAV extraction).
    await page.evaluate(
      "document.querySelector('.format-donut').parentElement.querySelector('button').click()"
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    const audio = await page.evaluate(state);
    check('the centre cycles to the audio ring', audio.centre === 'AUD',
      `the centre reads "${audio.centre}"`);
    check('the audio ring shows MP3 and WAV',
      JSON.stringify(audio.labels) === JSON.stringify(['MP3', 'WAV']),
      `the audio ring shows ${JSON.stringify(audio.labels)}`);
    check('the audio ring draws slices, not a placeholder circle', audio.placeholder === 0,
      `${audio.placeholder} placeholder circles`);
    check('the audio ring says so', audio.caption === 'Audio',
      `the caption reads "${audio.caption}"`);

    // The third click wraps back to the image ring.
    await page.evaluate(
      "document.querySelector('.format-donut').parentElement.querySelector('button').click()"
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    const back = await page.evaluate(state);
    check('the centre cycles back to the image ring', back.centre === 'IMG',
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
