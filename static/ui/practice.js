/* Ejercicios del plan de práctica (sección de expresión). */
(function () {
  'use strict';

  var App = window.App, $ = App.$, el = App.el;
  var data = JSON.parse($('practice-data').textContent);
  var WORD = /[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]/;

  function fold(s) { return (s || '').toLowerCase().replace(/\s+/g, ' ').trim(); }
  function countWords(s) { var m = (s || '').match(/[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+/g); return m ? m.length : 0; }
  function tokens(s, punct) {
    var re = punct ? /[0-9a-záéíóúüñ]+|[^\s0-9a-záéíóúüñ]/g : /[0-9a-záéíóúüñ]+/g;
    return (fold(s).match(re) || []).filter(function (t) { return t !== '¿' && t !== '¡'; });
  }
  function same(a, b, punct) { return tokens(a, punct).join(' ') === tokens(b, punct).join(' '); }
  function feedback(node, ok, title, body) {
    node.hidden = false;
    node.className = 'p-feedback ' + (ok ? 'ok' : 'bad');
    node.textContent = '';
    node.appendChild(el('strong', null, title));
    if (body) { node.appendChild(document.createTextNode(' ')); node.appendChild(el('span', null, body)); }
    App.replay(node, ok ? 'rise' : 'shake');
  }
  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  function per100(count, words) { return words ? Math.round(count * 1000 / words) / 10 : 0; }

  /* =================== Muletillas =================== */
  function muletillas() {
    var text = data.original, counts = data.before.map, box = $('m-text'), spans = [];
    var W = '0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ';
    // Ubica cada muletilla: el modelo dice cuántas veces aparece; se prefieren las que están
    // al inicio de una oración, junto a una coma o junto a otra muletilla.
    Object.keys(counts).sort(function (a, b) { return b.length - a.length; }).forEach(function (f) {
      var re = new RegExp('(^|[^' + W + '])(' + escapeRe(f) + ')(?=$|[^' + W + '])', 'gi'), m, found = [];
      while ((m = re.exec(text))) {
        var start = m.index + m[1].length, end = start + m[2].length;
        if (spans.some(function (s) { return start < s.end && end > s.start; })) continue;
        var before = text.slice(Math.max(0, start - 2), start), after = text.slice(end, end + 1);
        var hint = /^$|[.,;:!?¿¡]\s*$/.test(before) || /[,.;:]/.test(after) ? 0 : 1;
        found.push({ start: start, end: end, hint: hint });
      }
      found.sort(function (a, b) { return a.hint - b.hint || a.start - b.start; });
      found.slice(0, counts[f]).forEach(function (s) { spans.push(s); });
    });
    spans.sort(function (a, b) { return a.start - b.start; });
    var found = 0, total = spans.length;
    $('m-total').textContent = total;

    function addWords(fragment) {
      fragment.split(/([^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)/).forEach(function (part) {
        if (!part) return;
        if (!WORD.test(part)) { box.appendChild(document.createTextNode(part)); return; }
        var b = el('button', 'tap-word', part);
        b.type = 'button';
        box.appendChild(b);
      });
    }
    var pos = 0;
    spans.forEach(function (s) {
      addWords(text.slice(pos, s.start));
      var b = el('button', 'tap-word', text.slice(s.start, s.end));
      b.type = 'button';
      b.dataset.filler = '1';
      box.appendChild(b);
      pos = s.end;
    });
    addWords(text.slice(pos));

    box.addEventListener('click', function (e) {
      var b = e.target.closest('.tap-word');
      if (!b || b.classList.contains('hit')) return;
      if (b.dataset.filler) {
        b.classList.add('hit');
        found += 1;
        $('m-found').textContent = found;
        App.replay($('m-found'), 'rise');
        if (found === total) App.toast('¡Las encontraste todas!');
      } else {
        App.replay(b, 'shake');
      }
    });
    $('m-reveal').addEventListener('click', function () {
      box.querySelectorAll('[data-filler]:not(.hit)').forEach(function (b) { b.classList.add('missed'); });
    });
    var keys = Object.keys(counts);
    $('m-map').textContent = keys.length ? 'Tus muletillas en este texto: ' + keys.map(function (k) { return '«' + k + '» ×' + counts[k]; }).join(', ') + '.' : '';
    $('m-map').hidden = !keys.length;

    // Paso 2: un minuto hablando con pausas
    $('m-next').addEventListener('click', function () {
      $('m-step1').hidden = true;
      $('m-step2').hidden = false;
      $('m-s1').classList.remove('on');
      $('m-s2').classList.add('on');
      App.replay($('m-step2'), 'rise');
    });
    var LIMIT = 60, taps = 0, tick = null, transcript = $('m-transcript');
    var voice = window.Voice.create({
      textarea: transcript,
      context: 'practice',
      silenceMs: 0,   // el ejercicio pide hacer pausas: no se corta por silencio
      onState: function (st) {
        var mic = $('m-mic');
        mic.classList.toggle('is-rec', st === 'listening');
        mic.disabled = st === 'transcribing';
        mic.textContent = '';
        if (st === 'listening') {
          mic.appendChild(el('span', 'stop-dot'));
          mic.setAttribute('aria-label', 'Detener');
          $('m-tap').disabled = false;
          $('m-breath').classList.add('on');
          $('m-hint').textContent = 'Pausa, respira y sigue';
          clearInterval(tick);
          tick = setInterval(function () {
            var left = Math.max(0, LIMIT - Math.round(voice.elapsed()));
            $('m-time').textContent = App.formatTime(left);
            if (left <= 0) voice.stop();
          }, 250);
        } else {
          mic.appendChild(App.icon('i-mic'));
          mic.setAttribute('aria-label', 'Empezar a hablar');
          clearInterval(tick);
          $('m-breath').classList.remove('on');
          if (st === 'transcribing') { $('m-hint').textContent = 'Transcribiendo…'; return; }
          $('m-tap').disabled = true;
          if (voice.added || transcript.value.trim()) results();
          else $('m-hint').textContent = 'Presiona el micrófono para empezar';
        }
      },
      onStatus: function (msg) { App.toast(msg, true); }
    });
    $('m-mic').addEventListener('click', function () { voice.toggle(); });
    $('m-tap').addEventListener('click', function () {
      taps += 1;
      $('m-taps').textContent = taps;
      App.replay($('m-tap'), 'bump');
    });
    function results() {
      var said = transcript.value;
      $('m-hint').textContent = 'Contando tus muletillas…';
      App.api('/api/expresion/muletillas', { text: said }).then(function (res) {
        var before = data.before.rate, after = per100(res.count, res.words);
        $('m-before').textContent = before;
        $('m-after').textContent = after;
        $('m-results').hidden = false;
        App.replay($('m-results'), 'cascade');
        var parts = [];
        if (res.words < 30) parts.push('Hablaste poco para comparar bien; intenta llenar el minuto.');
        else if (after < before) parts.push('Bajaste de ' + before + ' a ' + after + ' muletillas por cada 100 palabras.');
        else parts.push('Todavía no baja: repítelo y exagera las pausas en silencio.');
        parts.push('Notaste ' + taps + ' y el sistema detectó ' + res.count + '. Darte cuenta tú es parte del avance.');
        var v = $('m-verdict');
        v.hidden = false;
        v.textContent = parts.join(' ');
        $('m-hint').textContent = 'Listo';
        $('m-again').hidden = false;
      }).catch(function (err) { App.toast(err.message, true); $('m-hint').textContent = 'Inténtalo de nuevo'; $('m-again').hidden = false; });
    }
    $('m-again').addEventListener('click', function () {
      taps = 0;
      $('m-taps').textContent = '0';
      transcript.value = '';
      voice.reset();
      $('m-time').textContent = '01:00';
      $('m-results').hidden = true;
      $('m-verdict').hidden = true;
      $('m-again').hidden = true;
      voice.start();
    });
  }

  /* =================== Ortografía: mira, cubre, escribe y compara =================== */
  function ortografia() {
    var words = data.words || [], index = 0, phase = 'look', status = {};
    var action = $('o-action'), input = $('o-input');

    function renderList() {
      var list = $('o-list');
      list.textContent = '';
      if (!words.length) { list.appendChild(el('span', 'muted', 'No tienes palabras pendientes.')); return; }
      words.forEach(function (w, i) {
        var row = el('div', 'o-row' + (i === index && phase !== 'done' ? ' now' : ''));
        row.appendChild(el('span', null, w.word));
        var st = status[w.id];
        row.appendChild(el('span', st === 'ok' ? 'ok' : st === 'retry' ? 'retry' : 'pend',
          st === 'ok' ? '✓ a la primera' : st === 'retry' ? 'repetida' : i === index ? 'en curso' : 'pendiente'));
        list.appendChild(row);
      });
    }
    function renderSchedule(s) {
      var box = $('o-sched');
      box.textContent = '';
      [['Hoy', s.today], ['Mañana', s.tomorrow], ['Después', s.later], ['Aprendidas', s.learned]].forEach(function (p, i) {
        box.appendChild(el('span', i === 0 ? 'now' : null, p[0] + ' · ' + p[1]));
      });
    }
    function steps(n) { for (var i = 1; i <= 4; i++) $('o-s' + i).classList.toggle('on', i === n); }
    function show() {
      if (index >= words.length) { $('o-card').hidden = true; $('o-done').hidden = false; App.replay($('o-done'), 'rise'); phase = 'done'; renderList(); return; }
      var w = words[index];
      phase = 'look';
      steps(1);
      $('p-progress').textContent = 'Palabra ' + (index + 1) + ' de ' + words.length;
      var word = $('o-word');
      word.className = 'ccc-word';
      word.textContent = w.word;
      App.replay(word, 'rise');
      $('o-instr').textContent = 'Mira bien la palabra, sobre todo sus tildes.';
      $('o-field').hidden = true;
      $('o-feedback').hidden = true;
      input.value = '';
      action.textContent = 'Ya la vi, tápala';
      renderList();
    }
    function cover() {
      phase = 'write';
      steps(3);
      $('o-word').classList.add('covered');
      $('o-instr').textContent = 'La palabra está cubierta. Escríbela de memoria.';
      $('o-field').hidden = false;
      input.focus();
      action.textContent = 'Comparar';
    }
    function compare() {
      var w = words[index];
      if (!input.value.trim()) { App.replay(input, 'shake'); return; }
      steps(4);
      $('o-instr').textContent = 'Compara lo que escribiste con la palabra.';
      var ok = input.value.trim().toLowerCase() === w.word.toLowerCase();
      $('o-word').classList.remove('covered');
      App.replay($('o-word'), 'rise');
      if (ok) {
        if (!status[w.id]) status[w.id] = 'ok';
        feedback($('o-feedback'), true, '¡Correcto!', w.explanation || '');
        action.textContent = 'Siguiente palabra';
        phase = 'next';
      } else {
        status[w.id] = 'retry';
        feedback($('o-feedback'), false, 'Casi: se escribe «' + w.word + '».', w.explanation || 'Vuelve a mirarla y escríbela otra vez.');
        action.textContent = 'Intentar de nuevo';
        phase = 'retry';
      }
      App.api('/api/expresion/ortografia', { id: w.id, correct: ok && status[w.id] === 'ok' })
        .then(function (res) { if (res && res.schedule) renderSchedule(res.schedule); })
        .catch(function () { /* el repaso se intentará de nuevo la próxima vez */ });
      renderList();
    }
    action.addEventListener('click', function () {
      if (phase === 'look') { steps(2); $('o-word').classList.add('covered'); setTimeout(cover, 450); }
      else if (phase === 'write') compare();
      else if (phase === 'next') { index += 1; show(); }
      else if (phase === 'retry') show();
    });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); if (phase === 'write') compare(); } });
    renderSchedule(data.schedule || { today: 0, tomorrow: 0, later: 0, learned: 0 });
    if (!words.length) { $('o-card').hidden = true; $('o-done').hidden = false; }
    show();
  }

  /* =================== Gramática y puntuación =================== */
  function items(kind) {
    var list = [], index = 0, checked = false, right = 0;
    var input = $('x-input'), action = $('x-action'), bar = $('x-bar');
    function render() {
      checked = false;
      $('x-feedback').hidden = true;
      input.value = '';
      input.disabled = false;
      bar.textContent = '';
      list.forEach(function (_, i) { bar.appendChild(el('span', i < index ? 'done' : i === index ? 'now' : null)); });
      if (index >= list.length) {
        $('x-count').textContent = 'Terminaste';
        var prompt = $('x-prompt');
        prompt.textContent = '';
        prompt.appendChild(el('strong', null, 'Acertaste ' + right + ' de ' + list.length + '.'));
        input.disabled = true;
        action.textContent = 'Volver a mi revisión';
        action.onclick = function () { window.location.href = '/gramatica'; };
        $('p-progress').textContent = right + ' de ' + list.length;
        return;
      }
      var item = list[index];
      $('x-count').textContent = (kind === 'gramatica' ? 'Oración ' : 'Reactivo ') + (index + 1) + ' de ' + list.length;
      $('p-progress').textContent = (index + 1) + ' de ' + list.length;
      var prompt = $('x-prompt');
      prompt.textContent = '';
      if (kind === 'gramatica') {
        prompt.appendChild(el('div', 'x-sentence', item.sentence));
      } else {
        item.parts.forEach(function (p) { prompt.appendChild(el('div', 'x-sentence', p)); });
        if (item.connector) prompt.appendChild(el('span', 'chip', 'Conector: ' + item.connector));
      }
      App.replay(prompt, 'cascade');
      action.textContent = 'Revisar';
      input.focus();
    }
    action.addEventListener('click', function () {
      if (index >= list.length) return;
      var item = list[index];
      if (!checked) {
        if (!input.value.trim()) { App.replay(input, 'shake'); return; }
        var ok = same(input.value, item.answer, kind === 'puntuacion');
        if (ok) right += 1;
        feedback($('x-feedback'), ok, ok ? '¡Correcto!' : 'Se escribe así: «' + item.answer + '»', item.rule);
        checked = true;
        input.disabled = true;
        action.textContent = index + 1 < list.length ? 'Siguiente' : 'Ver resultado';
      } else {
        index += 1;
        render();
      }
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); action.click(); }
    });
    App.api('/api/expresion/practica', { kind: kind, message_id: data.message_id })
      .then(function (res) { list = res.items || []; action.disabled = false; render(); })
      .catch(function (err) { $('x-prompt').textContent = err.message; });
  }

  /* =================== Claridad =================== */
  function claridad() {
    var input = $('c-input'), limit = data.summary_limit, model = null;
    $('c-source').textContent = data.original;
    function count() {
      var n = countWords(input.value);
      var c = $('c-count');
      c.textContent = n + ' de ' + limit + ' palabras';
      c.style.color = n > limit ? 'var(--pink-ink)' : 'var(--blue)';
    }
    input.addEventListener('input', count);
    count();
    $('c-action').addEventListener('click', function () {
      var n = countWords(input.value);
      if (!n) { App.replay(input, 'shake'); return; }
      if (n > limit) { App.toast('Te pasaste por ' + (n - limit) + ' palabras: quita lo que no sea la idea principal.', true); App.replay(input, 'shake'); return; }
      var restore = App.busyButton($('c-action'), 'Preparando…');
      (model ? Promise.resolve(model) : App.api('/api/expresion/practica', { kind: 'claridad', message_id: data.message_id }))
        .then(function (res) {
          model = res;
          $('c-model-text').textContent = '«' + res.model + '»';
          $('c-tip').textContent = res.tip || '';
          $('c-model').hidden = false;
          App.replay($('c-model'), 'rise');
        })
        .catch(function (err) { App.toast(err.message, true); })
        .then(restore);
    });
  }

  if (data.kind === 'muletillas') muletillas();
  else if (data.kind === 'ortografia') ortografia();
  else if (data.kind === 'gramatica' || data.kind === 'puntuacion') items(data.kind);
  else if (data.kind === 'claridad') claridad();
})();
