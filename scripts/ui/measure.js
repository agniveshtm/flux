/**
 * Measure the rendered layout of the Flux frontend.
 *
 *   node scripts/ui/measure.js [--out shot.png] [--width 900] [--height 620]
 *
 * Prints the geometry of the pieces the layout depends on - the drop area,
 * the format ring, the file list - so a change to the design can be checked
 * against the numbers rather than against a screenshot. The instrumented
 * copy is used, so file rows are present and the picker can be opened.
 */
'use strict';

const path = require('path');
const { instrumentFrontend, openPage } = require('./lib');

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1 || index === process.argv.length - 1) return fallback;
  return process.argv[index + 1];
}

(async () => {
  const width = Number(arg('width', 900));
  const height = Number(arg('height', 620));
  const out = arg('out', null);

  const page = await openPage({
    url: instrumentFrontend(),
    width,
    height,
  });

  try {
    // Seed a few rows so the file list and the row pickers are rendered.
    const seeded = await page.evaluate(`
      (function(){
        try {
          var f = window.__flux;
          if (!f) return 'NO_APP';
          ['photo.jpg','poster.png','clip.webp','banner.gif'].forEach(function(n, i){
            f.files.value.push({
              id: 'f' + i, name: n, size: 240000 + i * 7,
              type: 'image/' + n.split('.').pop(), path: 'C:/pics/' + n,
              objectUrl: null, targetFormat: 'png', status: 'ready', progress: 0
            });
          });
          f.handleSelectTarget('webp');
          return 'SEEDED';
        } catch (error) {
          return 'ERR:' + error.message;
        }
      })()
    `);

    // Open the first row's picker so the popover is part of the measurement.
    await page.evaluate(`
      (function(){
        var button = document.querySelector('.format-pick');
        if (button) button.click();
        return !!button;
      })()
    `);
    await new Promise((resolve) => setTimeout(resolve, 500));

    const measured = await page.evaluate(`
      (function(){
        var box = function(el){
          if (!el) return null;
          var r = el.getBoundingClientRect();
          return { x: Math.round(r.x), y: Math.round(r.y),
                   w: Math.round(r.width), h: Math.round(r.height) };
        };
        var dropZone = document.querySelector('.drop-zone');
        var row = dropZone ? dropZone.parentElement : null;
        var wings = row ? Array.prototype.map.call(row.children, box) : [];
        var card = document.querySelector('.card');
        var pop = document.querySelector('.format-pop');
        var popRect = pop ? pop.getBoundingClientRect() : null;
        var options = Array.prototype.map.call(
          document.querySelectorAll('.format-pop .format-tile'), function(tile){
            var r = tile.getBoundingClientRect();
            return { label: tile.textContent.trim(),
                     w: Math.round(r.width), h: Math.round(r.height),
                     selected: tile.getAttribute('aria-selected') };
          });
        var rims = Array.prototype.map.call(
          document.querySelectorAll('.format-donut path.format-donut-rim'),
          function(p){ return p.getAttribute('stroke'); }
        );
        var slices = Array.prototype.map.call(
          document.querySelectorAll('.format-donut path[role="option"]'), function(p, i){
            return { label: p.getAttribute('aria-label'),
                     rim: rims[i],
                     selected: p.getAttribute('aria-selected') };
          });
        var ring = document.querySelector('.format-donut');
        return {
          viewport: [innerWidth, innerHeight],
          pageScrollWidth: document.documentElement.scrollWidth,
          pageOverflows: document.documentElement.scrollWidth > innerWidth + 1,
          dropZone: box(dropZone),
          wings: wings,
          dropAreaCentreOffset: (function(){
            var button = document.querySelector('.drop-zone button');
            if (!button || !dropZone) return null;
            var b = button.getBoundingClientRect();
            var d = dropZone.getBoundingClientRect();
            return Math.round((b.x + b.width / 2) - (d.x + d.width / 2));
          })(),
          ring: box(ring),
          ringCentreOffset: (function(){
            var centre = ring ? ring.parentElement.querySelector('button') : null;
            if (!centre || !ring) return null;
            var c = centre.getBoundingClientRect();
            var r = ring.getBoundingClientRect();
            return Math.round((c.x + c.width / 2) - (r.x + r.width / 2));
          })(),
          slices: slices,
          fileList: box(document.querySelector('table')),
          fileRows: document.querySelectorAll('tbody tr').length,
          popoverVisible: !!popRect && popRect.width > 0 && popRect.height > 0,
          popover: popRect ? box(pop) : null,
          popoverOptions: options
        };
      })()
    `);

    console.log('seeded:', seeded);
    console.log(JSON.stringify(measured, null, 2));

    if (out) {
      const target = path.resolve(out);
      await page.screenshot(target);
      console.log('screenshot:', target);
    }
  } finally {
    page.close();
  }
})().catch((error) => {
  console.error('FAILED', error);
  process.exit(1);
});
