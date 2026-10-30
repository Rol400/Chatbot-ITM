/* Editor de gramática: revisar, marcar errores en el texto, aplicar correcciones y ejercicios. */
(function () {
  'use strict';

  var App = window.App, $ = App.$, el = App.el;
  // Paleta de 4 colores: cada tipo se distingue por color y por estilo de subrayado.
  var TYPES = {
    'Gramática': { key: 'gramatica', color: '#D6157A', bg: '#FCE8F2', fg: '#A3125F' },
    'Acentos': { key: 'acentos', color: '#0B7C80', bg: '#E3F7F7', fg: '#075E61' },
    'Ortografía': { key: 'ortografia', color: '#19202C', bg: '#EEF1F5', fg: '#19202C' },
    'Puntuación': { key: 'puntuacion', color: '#54CFD2', bg: '#E3F7F7', fg: '#075E61' },
    'Muletilla': { key: 'muletilla', color: '#A3125F', bg: '#FCE8F2', fg: '#A3125F' },
    'Estilo': { key: 'estilo', color: '#8A93A1', bg: '#EEF1F5', fg: '#3A4456' }
  };
  var textarea = $('g-text'), review = $('g-review'), pop = $('g-pop');
  var result = null, text = '', fixes = [], activeIndex = null, busy = false, allFixed = false;

  function typeInfo(t) { return TYPES[t] || TYPES['Estilo']; }
  function words(s) { var m = s.trim().match(/\S+/g); return m ? m.length : 0; }
  function status(msg) { $('g-status').textContent = msg || (words(textarea.value) + ' palabras'); }

  function setReviewing(on) {
    review.hidden = !on;
    textarea.hidden = on;
    $('g-edit').hidden = !on;
    pop.hidden = true;
    if (!on) { textarea.value = text || textarea.value; textarea.focus(); status(); }
  }

  /* ---------- Dibujo del texto con errores subrayados ---------- */
  function renderReview() {
    review.textContent = '';
    if (allFixed) { review.appendChild(el('span', 'fixed', text)); renderAside(); return; }
    var marks = [];
    (result.errors || []).forEach(function (e, i) {
      if (!e.done && e.start != null) marks.push({ start: e.start, end: e.end, index: i, kind: 'err' });
    });
    fixes.forEach(function (f) { marks.push({ start: f.start, end: f.end, kind: 'fix' }); });
    marks.sort(function (a, b) { return a.start - b.start; });
    var pos = 0;
    marks.forEach(function (m) {
      if (m.start < pos) return;
      review.appendChild(document.createTextNode(text.slice(pos, m.start)));
      var fragment = text.slice(m.start, m.end);
      if (m.kind === 'fix') {
        review.appendChild(el('span', 'fixed', fragment));
      } else {
        var err = result.errors[m.index];
        var btn = el('button', 'err t-' + typeInfo(err.type).key, fragment);
        btn.type = 'button';
        btn.dataset.index = m.index;
        btn.setAttribute('aria-label', err.type + ': ' + fragment + ', debe ir ' + err.right);
        review.appendChild(btn);
      }
      pos = m.end;
    });
    review.appendChild(document.createTextNode(text.slice(pos)));
    renderAside();
  }

  function renderAside() {
    var pending = (result.errors || []).filter(function (e) { return !e.done; });
    $('g-count').textContent = pending.length === 0 ? 'Sin errores pendientes'
      : pending.length === 1 ? '1 detalle por corregir' : pending.length + ' detalles por corregir';
    var types = $('g-types');
    types.textContent = '';
    var counts = {};
    pending.forEach(function (e) { counts[e.type] = (counts[e.type] || 0) + 1; });
    Object.keys(TYPES).forEach(function (t) {
      if (!counts[t]) return;
      var row = el('div');
      row.style.cssText = 'display:flex;justify-content:space-between;align-items:center';
      var name = el('span');
      name.style.cssText = 'display:flex;align-items:center;gap:10px';
      var dot = el('span', 'type-dot t-' + TYPES[t].key);
      name.appendChild(dot);
      name.appendChild(document.createTextNode(t));
      row.appendChild(name);
      row.appendChild(el('strong', null, String(counts[t])));
      types.appendChild(row);
    });
    if (!pending.length) types.appendChild(el('span', 'chip good', 'Todo corregido'));
    var unplaced = pending.filter(function (e) { return e.start == null; });
    unplaced.forEach(function (e) {
      var p = el('div', 'muted');
      p.style.fontSize = '13px';
      p.textContent = e.wrong + ' → ' + e.right + '. ' + (e.explanation || '');
      types.appendChild(p);
    });
    $('g-apply-all').hidden = !pending.length || !result.corrected;
  }

  function showResult() {
    $('g-empty').hidden = true;
    $('g-result').hidden = false;
    var score = result.score == null ? 0 : result.score;
    $('g-ring').setAttribute('aria-label', score + ' de 100');
    App.fillRing($('g-ring'), $('g-score'), score);
    App.replay($('g-result'), 'cascade');
    $('g-label').textContent = result.label || '';
    $('g-tip-box').hidden = !result.tip;
    $('g-tip').textContent = result.tip || '';
    var fb = $('g-fillers-box');
    fb.textContent = '';
    fb.hidden = !(result.fillers && result.fillers.length);
    if (!fb.hidden) {
      fb.appendChild(el('strong', null, 'Muletillas'));
      var counts = {};
      result.fillers.forEach(function (f) { counts[f] = (counts[f] || 0) + 1; });
      Object.keys(counts).forEach(function (k) { fb.appendChild(el('span', 'chip filler', k + ' · ' + counts[k])); });
    }
    renderReview();
    setReviewing(true);
    status('Revisado · ' + words(text) + ' palabras');
  }

  function showMessage(message, warn) {
    var box = $('g-message');
    box.hidden = !message;
    if (!message) return;
    box.className = 'speech' + (warn ? ' warn' : '');
    App.rich(box, message.text || message);
    if (warn) { App.replay(box, 'shake'); App.replay($('editor'), 'shake'); }
    if (message.data && message.data.source === 'intent') {
      box.appendChild(document.createElement('br'));
      var tag = el('span', 'chip good', 'Modelo propio · ' + Math.round((message.data.confidence || 0) * 100) + '%');
      tag.title = 'Respondido por el modelo de intenciones entrenado para este proyecto, sin usar la API';
      tag.style.marginTop = '6px';
      box.appendChild(tag);
    }
  }

  /* ---------- Plan de práctica ---------- */
  function renderPlan(plan, messageId) {
    var box = $('g-plan'), grid = $('g-plan-grid');
    grid.textContent = '';
    box.hidden = !plan.length;
    plan.forEach(function (item, i) {
      var card = el('div', 'plan-card' + (i === 0 ? ' first' : ''));
      var head = el('div', 'p-row');
      head.appendChild(el('span', 'label-up', item.criterion + (i === 0 ? ' · prioridad' : '')));
      head.appendChild(el('span', 'muted', item.minutes + ' min'));
      card.appendChild(head);
      card.appendChild(el('h3', 'display', item.title));
      card.appendChild(el('p', null, item.summary));
      var why = el('details');
      why.appendChild(el('summary', null, '¿Por qué funciona?'));
      why.appendChild(document.createTextNode(item.why));
      card.appendChild(why);
      var go = el('a', 'btn btn-sm ' + (i === 0 ? 'btn-dark' : 'btn-light'), 'Empezar');
      go.href = '/expresion/practica/' + item.kind + '/' + messageId;
      card.appendChild(go);
      grid.appendChild(card);
    });
    if (plan.length) App.replay(grid, 'cascade');
  }

  /* ---------- Ventanita de cada error ---------- */
  function openPop(index, anchor) {
    var e = result.errors[index];
    activeIndex = index;
    Array.prototype.forEach.call(review.querySelectorAll('.err'), function (b) { b.classList.toggle('active', b === anchor); });
    var info = typeInfo(e.type);
    var chip = $('pop-type');
    chip.textContent = e.type;
    chip.style.background = info.bg;
    chip.style.color = info.fg;
    $('pop-wrong').textContent = e.wrong;
    $('pop-right').textContent = e.right || '(quitar)';
    $('pop-exp').textContent = e.explanation || '';
    pop.hidden = false;
    var box = $('editor').getBoundingClientRect(), r = anchor.getBoundingClientRect();
    var left = Math.min(Math.max(12, r.left - box.left), box.width - 312);
    pop.style.left = Math.max(12, left) + 'px';
    pop.style.top = (r.bottom - box.top + 8) + 'px';
    $('pop-apply').focus();
  }
  function closePop() {
    pop.hidden = true;
    activeIndex = null;
    Array.prototype.forEach.call(review.querySelectorAll('.err.active'), function (b) { b.classList.remove('active'); });
  }

  function applyError(index) {
    var e = result.errors[index];
    if (e.start == null) return;
    var replacement = e.right || '';
    var delta = replacement.length - (e.end - e.start);
    text = text.slice(0, e.start) + replacement + text.slice(e.end);
    result.errors.forEach(function (o, i) {
      if (i !== index && o.start != null && o.start >= e.end) { o.start += delta; o.end += delta; }
    });
    fixes.forEach(function (f) { if (f.start >= e.end) { f.start += delta; f.end += delta; } });
    if (replacement) fixes.push({ start: e.start, end: e.start + replacement.length });
    e.done = true;
    textarea.value = text;
  }

  review.addEventListener('click', function (e) {
    var btn = e.target.closest('.err');
    if (btn) openPop(parseInt(btn.dataset.index, 10), btn);
  });
  $('pop-apply').addEventListener('click', function () {
    if (activeIndex == null) return;
    applyError(activeIndex);
    closePop();
    renderReview();
  });
  $('pop-ignore').addEventListener('click', function () {
    if (activeIndex == null) return;
    result.errors[activeIndex].done = true;
    closePop();
    renderReview();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePop(); });
  document.addEventListener('click', function (e) {
    if (!pop.hidden && !pop.contains(e.target) && !e.target.closest('.err')) closePop();
  });
  $('g-apply-all').addEventListener('click', function () {
    if (!result || !result.corrected) return;
    text = result.corrected;
    textarea.value = text;
    result.errors.forEach(function (e) { e.done = true; });
    allFixed = true;
    renderReview();
    App.toast('Se aplicaron todas las correcciones.');
  });
  $('g-edit').addEventListener('click', function () { setReviewing(false); });

  /* ---------- Revisar ---------- */
  function setBusy(on, label) {
    busy = on;
    ['g-check', 'g-exercise', 'g-mic'].forEach(function (id) { $(id).disabled = on; });
    var check = $('g-check');
    check.textContent = '';
    check.classList.toggle('is-loading', on);
    if (on) check.appendChild(el('span', 'spinner'));
    check.appendChild(el('span', null, on ? (label || 'Revisando…') : 'Revisar texto'));
  }

  $('g-check').addEventListener('click', function () {
    if (busy) return;
    if (!textarea.hidden) text = textarea.value;
    if (!text.trim()) { App.toast('Escribe o dicta un texto para revisarlo.', true); return; }
    if (voice.state === 'listening') voice.stop();
    setBusy(true);
    showMessage(null);
    App.api('/api/gramatica/revisar', { text: text, source: voice.added ? 'voice' : 'text' })
      .then(function (data) {
        if (data.navigate) { window.location.href = data.navigate; return; }
        var msg = data.message;
        if (data.status === 'text') {
          result = msg.data;
          renderPlan(result.plan || [], msg.id);
          text = result.original;
          fixes = [];
          allFixed = false;
          showResult();
          if (msg.text) showMessage({ text: msg.text });
        } else {
          showMessage(msg, data.status === 'invalid');
        }
        voice.reset();
      })
      .catch(function (err) { App.toast(err.message, true); })
      .then(function () { setBusy(false); });
  });

  $('g-exercise').addEventListener('click', function () {
    if (busy) return;
    setBusy(true, 'Preparando…');
    App.api('/api/gramatica/ejercicio', {})
      .then(function (data) {
        setReviewing(false);
        text = data.text;
        textarea.value = data.text;
        status();
        showMessage({ text: '**Ejercicio: ' + data.title + '.** Corrige el texto en el editor y luego presiona «Revisar texto».' });
      })
      .catch(function (err) { App.toast(err.message, true); })
      .then(function () { setBusy(false); });
  });

  /* ---------- Dictado ---------- */
  var voice = window.Voice.create({
    textarea: textarea,
    context: 'grammar',
    onState: function (st) {
      var btn = $('g-mic');
      btn.textContent = '';
      btn.classList.toggle('is-rec', st === 'listening');
      if (st === 'listening') { btn.appendChild(el('span', 'stop-dot')); btn.appendChild(el('span', null, 'Detener')); status('Escuchando…'); }
      else { btn.appendChild(App.icon('i-mic', 15)); btn.appendChild(el('span', null, st === 'transcribing' ? 'Transcribiendo…' : 'Dictar')); status(); }
      btn.disabled = st === 'transcribing';
    },
    onStatus: function (msg) { App.toast(msg, true); }
  });
  $('g-mic').addEventListener('click', function () {
    if (textarea.hidden) setReviewing(false);
    voice.toggle();
  });
  textarea.addEventListener('input', function () { text = textarea.value; status(); });
  status();
})();
