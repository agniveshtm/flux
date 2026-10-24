/**
 * Check the per-row format picker's popover.
 *
 *   node scripts/ui/check-picker.js
 *
 * The popover is position: fixed, because the file list clips its overflow -
 * so it has to be placed from the button's own rectangle and has to survive
 * the list scrolling under it. It also has to behave like a listbox: open on
 * click, move with the arrow keys, close on Escape and on an outside press,
 * and hand the focus back to the button it came from.
 */
'use strict';

const { check, finish, instrumentFrontend, openPage } = require('./lib');

(async () => {
  const page = await openPage({ url: instrumentFrontend() });

  const settle = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
    await settle(400);

    // 1. Opens on click.
    await page.evaluate("document.querySelector('.format-pick').click()");
    await settle(300);
    check('the popover opens on click',
      await page.evaluate("!!document.querySelector('.format-pop')"),
      'no popover appeared');

    // 2. The arrow key moves the roving focus.
    const before = await page.evaluate(
      "document.activeElement ? document.activeElement.textContent.trim() : null"
    );
    check('an option is focused when the popover opens', !!before, 'nothing held the focus');

    await page.evaluate(`
      (function(){
        var option = document.querySelector('.format-pop .format-tile');
        if (option) {
          option.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
        }
        return true;
      })()
    `);
    await settle(150);
    const after = await page.evaluate(
      "document.activeElement ? document.activeElement.textContent.trim() : null"
    );
    check('ArrowDown moves the focus', after && after !== before, 'focus did not move');

    // 3. Picking closes it and updates the row.
    await page.evaluate(`
      (function(){
        var options = document.querySelectorAll('.format-pop .format-tile');
        for (var i = 0; i < options.length; i++) {
          if (options[i].textContent.trim() === 'ICO') { options[i].click(); return true; }
        }
        return false;
      })()
    `);
    await settle(300);
    check('the popover closes after a pick',
      await page.evaluate("!document.querySelector('.format-pop')"),
      'the popover is still open');
    check('the focus returns to the button',
      await page.evaluate(
        "document.activeElement ? document.activeElement.className.indexOf('format-pick') >= 0 : false"
      ),
      'the focus went elsewhere');
    check('the row follows the pick',
      await page.evaluate("window.__flux.files.value[0].targetFormat") === 'ico',
      'the row still targets its old format');
    check('the button label follows the pick',
      await page.evaluate("document.querySelector('.format-pick').textContent.trim()") === 'ICO',
      'the button still shows the old format');

    // 4. Escape closes it.
    await page.evaluate("document.querySelector('.format-pick').click()");
    await settle(250);
    await page.evaluate(`
      (function(){
        var option = document.querySelector('.format-pop .format-tile');
        if (option) {
          option.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        }
        return true;
      })()
    `);
    await settle(250);
    check('Escape closes the popover',
      await page.evaluate("!document.querySelector('.format-pop')"),
      'the popover is still open');

    // 5. An outside press closes it.
    await page.evaluate("document.querySelector('.format-pick').click()");
    await settle(250);
    await page.evaluate(
      "document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))"
    );
    await settle(250);
    check('an outside press closes the popover',
      await page.evaluate("!document.querySelector('.format-pop')"),
      'the popover is still open');

    // 6. It is disabled while the row is converting.
    await page.evaluate("window.__flux.files.value[0].status = 'converting'");
    await settle(250);
    check('the picker is disabled while converting',
      await page.evaluate("document.querySelector('.format-pick').disabled"),
      'the picker is still enabled');

    // 7. The popover is actually painted and on top, rather than clipped
    //    away by an ancestor's overflow. elementFromPoint at its centre
    //    answers it.
    await page.evaluate("window.__flux.files.value[0].status = 'ready'");
    await settle(200);
    await page.evaluate("document.querySelector('.format-pick').click()");
    await settle(300);
    const hit = await page.evaluate(`
      (function(){
        var pop = document.querySelector('.format-pop');
        if (!pop) return 'no popover';
        var r = pop.getBoundingClientRect();
        var hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        if (!hit) return 'nothing at the centre';
        return (pop.contains(hit) || hit === pop) ? 'yes' : 'HIT BY: ' + (hit.className || hit.tagName);
      })()
    `);
    check('the popover is not clipped away', hit === 'yes', `the centre is ${hit}`);
  } finally {
    page.close();
  }

  finish();
})().catch((error) => {
  console.error('FAILED', error);
  process.exit(1);
});
