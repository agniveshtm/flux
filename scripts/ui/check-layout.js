/**
 * Check the layout invariants the top of the window has to keep.
 *
 *   node scripts/ui/check-layout.js
 *
 * These are the rules a static check cannot see, because they only exist
 * once the browser has laid the page out:
 *
 *   1. the drop area and the format ring are two equal wings
 *   2. the "Select files" button is centred in the drop area
 *   3. the ring is centred in its wing
 *   4. every format gets its own colour, and the selected slice stands out
 *   5. the page does not scroll sideways
 */
'use strict';

const { check, fail, finish, instrumentFrontend, openPage, ok } = require('./lib');

(async () => {
  const page = await openPage({ url: instrumentFrontend() });

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
        f.handleSelectTarget('webp');
        return true;
      })()
    `);
    await new Promise((resolve) => setTimeout(resolve, 400));

    const info = await page.evaluate(`
      (function(){
        var rect = function(el){
          if (!el) return null;
          var r = el.getBoundingClientRect();
          return { x: Math.round(r.x), y: Math.round(r.y),
                   w: Math.round(r.width), h: Math.round(r.height) };
        };
        var dropZone = document.querySelector('.drop-zone');
        var row = dropZone.parentElement;
        var wings = Array.prototype.map.call(row.children, rect);
        var button = dropZone.querySelector('button');
        var buttonRect = button.getBoundingClientRect();
        var dropRect = dropZone.getBoundingClientRect();
        var ring = document.querySelector('.format-donut');
        var ringRect = ring.getBoundingClientRect();
        var centre = ring.parentElement.querySelector('button');
        var centreRect = centre.getBoundingClientRect();
        // The colour lives in the rim: each well is theme-coloured, and its
        // inset crimson border is a sibling path rendered in the same order,
        // so the pair is made by index.
        var rims = Array.prototype.map.call(
          document.querySelectorAll('.format-donut path.format-donut-rim'),
          function(p){ return p.getAttribute('stroke'); }
        );
        var slices = Array.prototype.map.call(
          document.querySelectorAll('.format-donut path[role="option"]'), function(p, i){
            return { label: p.getAttribute('aria-label'),
                     rim: rims[i],
                     opacity: p.style.opacity,
                     selected: p.getAttribute('aria-selected') };
          });
        return {
          wings: wings,
          dropArea: rect(dropZone),
          buttonCentreOffset: Math.round(
            (buttonRect.x + buttonRect.width / 2) - (dropRect.x + dropRect.width / 2)
          ),
          ringCentreOffset: Math.round(
            (centreRect.x + centreRect.width / 2) - (ringRect.x + ringRect.width / 2)
          ),
          ringSize: Math.round(ringRect.width),
          sliceCount: slices.length,
          slices: slices,
          pageOverflows: document.documentElement.scrollWidth > innerWidth + 1,
          viewportWidth: innerWidth,
          fileListHeight: (function(){
            var table = document.querySelector('table');
            return table ? Math.round(table.getBoundingClientRect().height) : 0;
          })()
        };
      })()
    `);

    const [left, right] = info.wings;
    check(
      'the drop area and the format ring are the same width',
      left && right && left.w === right.w,
      `drop area ${left && left.w}px, ring wing ${right && right.w}px`
    );
    check(
      'the drop area and the format ring are the same height',
      left && right && left.h === right.h,
      `drop area ${left && left.h}px, ring wing ${right && right.h}px`
    );
    check(
      'the "Select files" button is centred in the drop area',
      info.buttonCentreOffset === 0,
      `off centre by ${info.buttonCentreOffset}px`
    );
    check(
      'the ring is centred in its wing',
      info.ringCentreOffset === 0,
      `off centre by ${info.ringCentreOffset}px`
    );
    check(
      'the page does not scroll sideways',
      !info.pageOverflows,
      `the page is wider than the ${info.viewportWidth}px viewport`
    );
    check(
      'every format has a slice',
      info.sliceCount > 0,
      'the ring has no slices'
    );

    const rims = new Set(info.slices.map((slice) => slice.rim));
    check(
      'every format has its own colour',
      rims.size === info.sliceCount,
      `${rims.size} colours for ${info.sliceCount} slices`
    );

    const selected = info.slices.filter((slice) => slice.selected === 'true');
    check(
      'exactly one slice is selected',
      selected.length === 1,
      `${selected.length} slices are selected`
    );
    if (selected.length === 1) {
      const others = info.slices.filter((slice) => slice !== selected[0]);
      const dimmed = others.every((slice) => slice.opacity !== '1');
      check(
        'the selected slice stands out from the rest',
        dimmed,
        'the unselected slices are not dimmed'
      );
    }

    console.log('');
    console.log('wings:', JSON.stringify(info.wings));
    console.log('ring:', info.ringSize + 'px');
    console.log('file list height:', info.fileListHeight + 'px');
    info.slices.forEach((slice) => {
      console.log(`   ${slice.label.padEnd(5)} rim=${slice.rim} opacity=${slice.opacity} selected=${slice.selected}`);
    });
  } finally {
    page.close();
  }

  finish();
})().catch((error) => {
  console.error('FAILED', error);
  process.exit(1);
});
