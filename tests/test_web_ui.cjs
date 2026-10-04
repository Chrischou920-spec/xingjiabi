// Dependency-free checks for the UI contract; visual/DOM checks also run in the browser.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'web/styles.css'), 'utf8');
const script = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');

function setup({ reduced = false } = {}) {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  const elements = new Map();
  let focused = null;
  let animations = 0;
  const effects = [];
  let preference = 'balanced';
  const inputs = new Set([...html.matchAll(/<input\b[^>]*\bid="([^"]+)"/g)].map(match => match[1]));
  for (const id of ids) {
    const attrs = new Map();
    const classes = new Set();
    const label = { textContent: '' };
    elements.set(id, {
      id, value: '', checked: false, disabled: false, hidden: false, textContent: '', innerHTML: '', validity: { valid: true },
      classList: { add: name => classes.add(name), toggle(name, on) { const active = on ?? !classes.has(name); active ? classes.add(name) : classes.delete(name); }, contains: name => classes.has(name) },
      setAttribute: (name, value) => attrs.set(name, value), removeAttribute: name => attrs.delete(name),
      getAttribute: name => attrs.get(name), hasAttribute: name => attrs.has(name),
      focus() { focused = id; }, animate(frames, options) {
        animations++;
        const effect = { id, frames, options, cancelled: false, cancel() { this.cancelled = true; } };
        effects.push(effect);
        return effect;
      },
      querySelector: () => label, addEventListener() {},
    });
    if (elements.has(`${id}-error`)) continue;
  }
  for (const id of inputs) if (elements.has(`${id}-error`)) elements.get(id).setAttribute('aria-describedby', `${id}-error`);
  const document = {
    title: '',
    getElementById: id => elements.get(id) || null,
    querySelector: selector => selector.includes('preference') ? { value: preference } : null,
    querySelectorAll: selector => selector.includes('aria-describedby')
      ? [...elements.values()].filter(element => element.hasAttribute('aria-describedby'))
      : selector.includes('#plan-form input') ? [...inputs].map(id => elements.get(id)).concat(elements.get('swap-cities')) : [],
  };
  const context = vm.createContext({
    document, window: { matchMedia: query => ({ matches: query.includes('reduced-motion') && reduced, addEventListener() {} }), scrollTo() {} },
    Date, Set, AbortController, crypto: require('node:crypto').webcrypto,
    setInterval: () => 1, clearInterval() {},
  });
  vm.runInContext(script.replace(/^initialize\(\);$/m, ''), context);
  const values = { origin: '上海', destination: '北京', 'outbound-date': '2026-10-01', 'outbound-start': '06:00', 'outbound-end': '12:00', 'return-date': '2026-10-03', 'return-start': '16:00', 'return-end': '22:30', 'accommodation-cost': '200', 'dorm-time': '23:00' };
  for (const [id, value] of Object.entries(values)) elements.get(id).value = value;
  for (const id of ['round-trip', 'mode-train', 'mode-flight', 'accommodation']) elements.get(id).checked = true;
  vm.runInContext('state.cities = new Set(["上海", "北京", "呼和浩特"]);', context);
  return { context, elements, run: source => vm.runInContext(source, context), setPreference: value => { preference = value; }, focused: () => focused, animations: () => animations, effects: () => effects };
}

test('HTML has unique IDs and every inline-error reference resolves', () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const [, id] of html.matchAll(/aria-describedby="([^"]+)"/g)) assert.ok(ids.includes(id), id);
  assert.equal((html.match(/<\/html>/g) || []).length, 1);
  assert.ok(!html.includes('<img'));
});

test('round-trip request preserves the existing API contract', () => {
  const ui = setup();
  const request = ui.run('validateAndBuildRequest()');
  assert.equal(request.origin, '上海');
  assert.equal(request.return_after, '2026-10-03T16:00:00');
  assert.equal(request.max_transfers, 0);
  assert.equal(request.budget, null);
  assert.equal(request.include_accommodation, true);
  assert.deepEqual(Array.from(request.allowed_modes), ['train', 'flight']);
});

test('single trip disables return and dorm controls without discarding date values', () => {
  const ui = setup();
  ui.elements.get('round-trip').checked = false;
  ui.run('updateRoundTrip()');
  assert.equal(ui.elements.get('return-date').disabled, true);
  assert.equal(ui.elements.get('dorm-enabled').disabled, true);
  assert.equal(ui.elements.get('return-date').value, '2026-10-03');
  assert.equal(ui.run('validateAndBuildRequest().return_after'), null);
  assert.equal(ui.elements.get('preview-type').textContent, '单程');
});

test('live preview follows route, budget, preference and transportation', () => {
  const ui = setup();
  ui.elements.get('origin').value = '呼和浩特';
  ui.elements.get('budget').value = '1300';
  ui.elements.get('mode-flight').checked = false;
  ui.setPreference('cheapest');
  ui.run('updatePreview()');
  assert.equal(ui.elements.get('preview-budget').textContent, '¥1,300');
  assert.equal(ui.elements.get('preview-modes').textContent, '火车');
  assert.equal(ui.elements.get('preview-preference').textContent, '最省钱');
  assert.equal(ui.elements.get('origin').classList.contains('is-long'), true);
});

test('route illustration reuses the clear plane glyph and switches to train when needed', () => {
  assert.match(html, /id="route-vehicle-use" href="#icon-plane"/);
  assert.ok(!html.includes('m139 22 17 10'));
  const ui = setup();
  ui.run('updatePreview()');
  assert.equal(ui.elements.get('route-vehicle-use').getAttribute('href'), '#icon-plane');
  assert.equal(ui.elements.get('route-vehicle-heading').getAttribute('transform'), 'rotate(90)');
  ui.elements.get('mode-flight').checked = false;
  ui.run('updatePreview(true)');
  assert.equal(ui.elements.get('route-vehicle-use').getAttribute('href'), '#icon-train');
  assert.equal(ui.elements.get('route-vehicle-heading').getAttribute('transform'), 'rotate(0)');
  ui.elements.get('mode-train').checked = false;
  ui.run('updatePreview(true)');
  assert.equal(ui.elements.get('route-vehicle').getAttribute('visibility'), 'hidden');
});

test('rapid preview feedback cancels prior motion without delaying final content', () => {
  const ui = setup();
  ui.run('setPreviewText("preview-origin", "上海", true); setPreviewText("preview-origin", "北京", true)');
  assert.equal(ui.elements.get('preview-origin').textContent, '北京');
  assert.equal(ui.animations(), 2);
  assert.equal(ui.effects()[0].cancelled, true);
  assert.equal(ui.effects()[1].cancelled, false);
});

test('reduced-motion preview retains feedback content without new movement', () => {
  const ui = setup({ reduced: true });
  ui.run('updatePreview(true)');
  assert.equal(ui.elements.get('preview-origin').textContent, '上海');
  assert.equal(ui.elements.get('route-vehicle-use').getAttribute('href'), '#icon-plane');
  assert.equal(ui.animations(), 0);
});

test('selection indicator sets final geometry before animation and retargets safely', () => {
  const ui = setup();
  const nav = ui.elements.get('page-nav');
  nav.getBoundingClientRect = () => ({ left: 10, top: 10 });
  nav.clientLeft = nav.clientTop = 1;
  const indicator = ui.elements.get('nav-indicator');
  indicator.style = {};
  indicator.getBoundingClientRect = () => ({ left: 20, top: 16, width: 120, height: 48 });
  for (const id of ['nav-planning', 'nav-results']) ui.elements.get(id).getBoundingClientRect = () => ({ left: id === 'nav-planning' ? 16 : 150, top: 16, width: 140, height: 48 });
  ui.run('moveSelectionIndicator($("page-nav"), $("nav-planning"), $("nav-indicator"), false)');
  ui.run('moveSelectionIndicator($("page-nav"), $("nav-results"), $("nav-indicator"))');
  assert.equal(indicator.style.transform, 'translate(139px, 5px)');
  assert.equal(indicator.style.width, '140px');
  assert.equal(nav.classList.contains('has-indicator'), true);
  ui.run('moveSelectionIndicator($("page-nav"), $("nav-planning"), $("nav-indicator"))');
  assert.equal(indicator.style.transform, 'translate(5px, 5px)');
  assert.equal(ui.effects()[0].cancelled, true);
  ui.run('moveSelectionIndicator($("page-nav"), $("nav-results"), $("nav-indicator"), false)');
  assert.equal(ui.effects()[1].cancelled, true);
  assert.equal(ui.run('motionEffects.size'), 0);
});

test('pointer and keyboard press waves are decorative and clean up after completion', async () => {
  const ui = setup();
  const waves = [];
  ui.context.document.createElement = () => {
    const attrs = new Map();
    const wave = {
      style: {}, removed: false, setAttribute: (key, value) => attrs.set(key, value), getAttribute: key => attrs.get(key),
      remove() { this.removed = true; },
      animate(frames, options) { this.frames = frames; this.timing = options; return { finished: Promise.resolve(), cancel() {} }; },
    };
    waves.push(wave);
    return wave;
  };
  const button = ui.elements.get('submit-button');
  button.getBoundingClientRect = () => ({ left: 10, top: 20, width: 320, height: 60 });
  button.append = () => {};
  ui.run('showPressWave($("submit-button"), {clientX:30,clientY:40})');
  assert.equal(waves[0].getAttribute('aria-hidden'), 'true');
  assert.equal(ui.run('pressWaves.size'), 1);
  await Promise.resolve();
  assert.equal(waves[0].removed, true);
  assert.equal(ui.run('pressWaves.size'), 0);
  ui.run('showPressWave($("submit-button"))');
  assert.equal(waves[1].timing.duration, 440);
  await Promise.resolve();
  assert.equal(waves[1].removed, true);
  assert.equal(ui.run('motionEffects.size'), 0);
});

test('press waves do not run on disabled controls or with reduced motion', () => {
  const disabled = setup();
  disabled.elements.get('submit-button').disabled = true;
  disabled.run('showPressWave($("submit-button"))');
  const reduced = setup({ reduced: true });
  reduced.run('showPressWave($("submit-button"))');
  assert.equal(disabled.run('pressWaves.size'), 0);
  assert.equal(reduced.run('pressWaves.size'), 0);
});

test('validation collects multiple errors instead of losing later fields', () => {
  const ui = setup();
  ui.elements.get('origin').value = '';
  ui.elements.get('budget').value = '-1';
  ui.elements.get('return-date').value = '2026-09-30';
  assert.throws(() => ui.run('validateAndBuildRequest()'), error => {
    const ids = Array.from(error.fields, item => item.id);
    return ['origin', 'budget', 'return-date'].every(id => ids.includes(id));
  });
});

test('unknown cities, equal routes and unselected transport are rejected', () => {
  const ui = setup();
  ui.elements.get('origin').value = '不存在的城市';
  ui.elements.get('mode-train').checked = false;
  ui.elements.get('mode-flight').checked = false;
  assert.throws(() => ui.run('validateAndBuildRequest()'), error => error.fields.length === 2);
  ui.elements.get('origin').value = '北京';
  assert.throws(() => ui.run('validateAndBuildRequest()'), error => error.fields.some(item => item.id === 'destination'));
});

test('incomplete dorm time and reverse time windows are rejected', () => {
  const ui = setup();
  ui.elements.get('dorm-enabled').checked = true;
  ui.elements.get('dorm-time').value = '';
  ui.elements.get('outbound-end').value = '05:00';
  assert.throws(() => ui.run('validateAndBuildRequest()'), error => error.fields.length === 2);
});

test('disabled accommodation is excluded from the request', () => {
  const ui = setup();
  ui.elements.get('accommodation').checked = false;
  ui.elements.get('accommodation-cost').value = '-999';
  assert.equal(ui.run('validateAndBuildRequest().accommodation_cost'), 0);
});

test('inline errors and linked summary expose invalid fields', () => {
  const ui = setup();
  ui.run('showFieldErrors([{id:"origin",message:"请选择出发地。"}], true)');
  assert.equal(ui.elements.get('origin').getAttribute('aria-invalid'), 'true');
  assert.match(ui.elements.get('error-summary').innerHTML, /href="#origin"/);
  assert.equal(ui.elements.get('origin-error').textContent, '请选择出发地。');
  ui.run('showFieldErrors([], true)');
  assert.equal(ui.elements.get('error-summary').hidden, true);
  assert.equal(ui.elements.get('origin').hasAttribute('aria-invalid'), false);
});

test('busy UI keeps cancellation reachable and restores original disabled states', () => {
  const ui = setup();
  ui.elements.get('dorm-time').disabled = true;
  ui.run('setQueryBusy(true)');
  assert.equal(ui.elements.get('origin').disabled, true);
  assert.equal(ui.elements.get('submit-button').disabled, false);
  assert.equal(ui.elements.get('query-status').hidden, false);
  ui.run('setQueryBusy(false)');
  assert.equal(ui.elements.get('origin').disabled, false);
  assert.equal(ui.elements.get('dorm-time').disabled, true);
  assert.equal(ui.elements.get('query-status').hidden, true);
});

test('page navigation manages focus and honours reduced motion', () => {
  const ui = setup({ reduced: true });
  ui.run('setView("results")');
  assert.equal(ui.elements.get('planning-view').hidden, true);
  assert.equal(ui.elements.get('nav-results').getAttribute('aria-current'), 'page');
  assert.equal(ui.focused(), 'results-title');
  assert.equal(ui.animations(), 0);
  const moving = setup();
  moving.run('setView("results"); setView("planning")');
  assert.equal(moving.animations(), 2);
});

test('backend strings are escaped in ticket and warning rendering', () => {
  const ui = setup();
  const rendered = ui.run(`segmentHtml({mode:'flight',number:'<img src=x>',departure_at:'2026-10-01T09:00:00',arrival_at:'2026-10-01T11:20:00',departure_station:'<script>bad</script>',arrival_station:'北京',price:680,seat_or_cabin:'经济舱'})`);
  assert.ok(!rendered.includes('<img'));
  assert.ok(!rendered.includes('<script>'));
  assert.match(rendered, /&lt;img/);
  assert.match(rendered, /2小时20分/);
});

test('comparison copy uses actual price and time differences', () => {
  const ui = setup();
  const rendered = ui.run(`resultHtml({total_cost:1173,total_duration_minutes:411,ticket_cost:1173,outbound:[],inbound:[]},1,{origin:'上海',destination:'北京',return_after:'2026-10-03'},{total_cost:1300,total_duration_minutes:275})`);
  assert.match(rendered, /较推荐省 ¥127/);
  assert.match(rendered, /多耗时 2小时16分/);
});

test('partial source failure keeps verified results and escapes diagnostic details', () => {
  const ui = setup({ reduced: true });
  ui.run(`state.health = {flight_browser_engine:'safari'};
    renderResults({data_mode:'live',source_errors:{flight:'CONTENT_NOT_READY <script>bad</script>'},plans:[{total_cost:576,total_duration_minutes:273,ticket_cost:576,outbound:[{mode:'train',number:'G44',departure_at:'2026-10-08T15:04:00',arrival_at:'2026-10-08T19:37:00',departure_station:'上海虹桥',arrival_station:'北京南',price:576,seat_or_cabin:'二等座',source:'12306'}],inbound:[]}]},validateAndBuildRequest());`);
  const notice = ui.elements.get('results-message').innerHTML;
  assert.match(notice, /请确认 Safari 中携程已登录/);
  assert.match(notice, /查看来源诊断/);
  assert.match(notice, /&lt;script&gt;/);
  assert.ok(!notice.includes('<script>'));
  assert.equal(ui.elements.get('flight-results').hidden, true);
  assert.match(ui.elements.get('results-overview').innerHTML, /火车 · 直达方案/);
  assert.ok(!ui.elements.get('results-overview').innerHTML.includes('飞机'));
  assert.match(ui.elements.get('result-list').innerHTML, /G44/);
});

test('critical colour pairs meet contrast thresholds', () => {
  const luminance = colour => {
    const values = colour.match(/../g).map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
    return .2126 * values[0] + .7152 * values[1] + .0722 * values[2];
  };
  const ratio = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
  for (const [a, b] of [['5b6b7c','edf2f6'], ['5b6b7c','f6f8fb'], ['235de5','ffffff'], ['c3d1df','142c42'], ['ad362e','fff2ef']]) assert.ok(ratio(a, b) >= 4.5, `${a}/${b}`);
  assert.ok(ratio('7c8ca0', 'f6f8fb') >= 3);
});

test('motion fallback and zoom remain supported without third-party UI code', () => {
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /prefers-reduced-transparency: reduce/);
  assert.match(css, /font-size: 100%/);
  assert.ok(!html.includes('user-scalable=no'));
  assert.ok(!html.includes('https://'));
  for (const endpoint of ['/health', '/cities', '/plan', '/cancel']) assert.ok(script.includes(`"${endpoint}"`));
});
