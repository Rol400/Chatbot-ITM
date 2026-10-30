/* Simulador de entrevista: preparación, pregunta, respuesta, retroalimentación y siguiente pregunta. */
(function () {
  'use strict';

  var App = window.App, $ = App.$, el = App.el;
  var state = JSON.parse($('interview-state').textContent);
    var busy = false, shownAt = Date.now(), currentQuestionId = null, spokenId = null, pendingSend = false;
  var timerId = null;

  /* =================== Preparación =================== */
  var setup = { level: 'junior', total: '8', interview_type: 'mixta' };

  Array.prototype.forEach.call(document.querySelectorAll('[data-group]'), function (group) {
    group.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-value]');
      if (!btn) return;
      Array.prototype.forEach.call(group.querySelectorAll('button[data-value]'), function (b) {
        b.setAttribute('aria-pressed', String(b === btn));
      });
      setup[group.dataset.group] = btn.dataset.value;
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-role]'), function (btn) {
    btn.addEventListener('click', function () { $('role').value = btn.dataset.role; $('role').focus(); });
  });
  $('cv').addEventListener('change', function () {
    var file = this.files[0];
    $('cv-zone').classList.toggle('has-file', !!file);
    $('cv-name').textContent = file ? file.name : 'Sube tu CV en PDF';
  });

  $('setup-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var role = $('role').value.trim();
    if (!role) { App.toast('Escribe el puesto para el que quieres practicar.', true); $('role').focus(); return; }
    var form = new FormData();
    form.append('role', role);
    Object.keys(setup).forEach(function (k) { form.append(k, setup[k]); });
    form.append('job_description', $('job_description').value);
    if ($('cv').files[0]) form.append('cv', $('cv').files[0]);
    App.cover('Preparando tu entrevista…');
    App.api('/api/entrevista/iniciar', form)
      .then(function (data) {
        state = data;
        history.replaceState(null, '', '/entrevista');
        showSession();
      })
      .catch(function (err) { App.toast(err.message, true); })
      .then(function () { App.cover(null); });
  });

  /* =================== Sesión =================== */
  var answer = $('answer');
  var interviewer = $('interviewer');

  function orb(name, text) { interviewer.dataset.orb = name; $('orb-text').textContent = text; }

  function showSession() {
    $('setup-view').hidden = true;
    $('session-view').hidden = false;
    render();
  }

  function renderHeader() {
    var s = state.session;
    $('s-title').textContent = 'Entrevista para ' + s.role;
    $('s-count').textContent = 'Pregunta ' + s.questions_asked + ' de ' + s.total_questions;
    var dots = $('s-dots');
    dots.textContent = '';
    for (var i = 1; i <= s.total_questions; i++) {
      var dot = el('span');
      if (i < s.questions_asked || (i === s.questions_asked && state.phase === 'feedback')) dot.className = 'done';
      else if (i === s.questions_asked) dot.className = 'now';
      dots.appendChild(dot);
    }
  }

  function render() {
    if (state.phase === 'finished') { window.location.href = '/reporte/' + state.session.id; return; }
    renderHeader();
    if (state.phase === 'feedback') showFeedback(); else showQuestion();
  }

  function showSpeech(message) {
    var speech = $('speech');
    if (!message) { speech.hidden = true; return; }
    speech.hidden = false;
    speech.className = 'speech' + (message.data && message.data.invalid ? ' warn' : '');
    App.rich(speech, message.text);
    if (message.data && message.data.invalid) { App.replay(speech, 'shake'); App.replay($('answer-box'), 'shake'); }
    if (message.data && message.data.source === 'intent') {
      speech.appendChild(document.createElement('br'));
      var tag = el('span', 'chip good');
      tag.style.marginTop = '6px';
      tag.title = 'Respondido por el modelo de intenciones entrenado para este proyecto, sin usar la API';
      tag.appendChild(App.icon('i-chip', 12));
      tag.appendChild(document.createTextNode(' Modelo propio · ' + Math.round((message.data.confidence || 0) * 100) + '%'));
      speech.appendChild(tag);
    }
  }

  function speakQuestion(force) {
    var q = state.question;
    if (!q || (!force && spokenId === q.id)) { orb('idle', 'Te toca responder'); return; }
    spokenId = q.id;
    if (!App.tts.enabled()) { orb('idle', 'Te toca responder'); return; }
    orb('speaking', 'Haciendo la pregunta…');
    App.tts.speak(q.text, function () { if (voice.state === 'idle' && !busy) orb('idle', 'Te toca responder'); });
  }

  function showQuestion() {
    $('q-view').hidden = false;
    $('f-view').hidden = true;
    var q = state.question;
    var type = q.data.question_type ? ' · ' + q.data.question_type : '';
    $('q-label').textContent = 'Pregunta ' + q.data.question_number + type;
    $('q-text').textContent = q.text;
    if (currentQuestionId !== q.id) {
      currentQuestionId = q.id;
      answer.value = '';
      voice.reset();
      shownAt = Date.now();
      $('answer-status').textContent = 'Tómate unos segundos para pensar antes de responder.';
    }
    showSpeech(state.interviewer);
    if (state.interviewer && App.tts.enabled()) {
      orb('speaking', 'Hablando…');
      App.tts.speak(state.interviewer.text, function () { orb('idle', 'Te toca responder'); });
    } else {
      speakQuestion(false);
    }
  }

  function metric(label, value) {
    var box = el('div', 'metric');
    var row = el('div', 'row');
    row.appendChild(el('span', null, label));
    row.appendChild(el('strong', null, value == null ? '—' : value + '/5'));
    box.appendChild(row);
    var bar = el('div', 'bar' + (value != null && value <= 2 ? ' low' : ''));
    var fill = el('div');
    fill.style.width = value == null ? '0%' : (value / 5 * 100) + '%';
    bar.appendChild(fill);
    box.appendChild(bar);
    return box;
  }

  function fillList(id, items) {
    var ul = $(id);
    ul.textContent = '';
    (items || []).forEach(function (item) { ul.appendChild(App.rich(el('li'), item)); });
  }

  function showFeedback() {
    $('q-view').hidden = true;
    $('f-view').hidden = false;
    var msg = state.feedback, d = msg.data;
    var score = d.score || 0;
    var ring = $('f-ring');
    ring.style.setProperty('--ring', score < 60 ? 'var(--pink)' : 'var(--blue)');
    ring.setAttribute('aria-label', score + ' de 100');
    App.fillRing(ring, $('f-score'), score);
    App.replay($('f-view'), 'cascade');
    $('f-label').textContent = d.label || '';
    $('f-message').textContent = msg.text || '';
    var metrics = $('f-metrics');
    metrics.textContent = '';
    var sc = d.scores || {};
    metrics.appendChild(metric('Claridad', sc.claridad));
    metrics.appendChild(metric('Estructura', sc.estructura));
    metrics.appendChild(metric('Confianza', sc.seguridad));
    fillList('f-good', (d.feedback || {}).good);
    fillList('f-improve', (d.feedback || {}).improve);
    var example = (d.feedback || {}).example;
    $('f-example-box').hidden = !example;
    if (example) $('f-example').textContent = '«' + example + '»';

    var strip = $('f-strip');
    strip.textContent = '';
    strip.appendChild(el('strong', null, 'Muletillas'));
    var counts = {};
    (d.fillers || []).forEach(function (f) { counts[f] = (counts[f] || 0) + 1; });
    var keys = Object.keys(counts);
    if (!keys.length) strip.appendChild(el('span', 'chip good', 'Ninguna'));
    keys.forEach(function (k) { strip.appendChild(el('span', 'chip filler', k + ' · ' + counts[k])); });
    var extra = el('span', 'muted');
    extra.style.marginLeft = 'auto';
    extra.style.fontSize = '13px';
    var parts = [];
    if (d.duration) parts.push('Duración ' + App.formatTime(d.duration));
    if (d.wpm) parts.push('Ritmo: ' + d.wpm + ' palabras por minuto, ' + (d.wpm < 100 ? 'algo lento' : d.wpm > 165 ? 'algo rápido' : 'adecuado'));
    extra.textContent = parts.join(' · ');
    strip.appendChild(extra);

    $('f-answer-box').hidden = !state.answer;
    App.markFillers($('f-answer'), state.answer || '', d.fillers);
    $('next-btn').firstElementChild.textContent = state.is_last ? 'Ver mi reporte' : 'Siguiente pregunta';
    showSpeech(null);
    orb('done', 'Listo');
    if (App.tts.enabled() && msg.text) {
      orb('speaking', 'Comentando tu respuesta…');
      App.tts.speak(msg.text, function () { orb('done', 'Listo'); });
    }
  }

  /* =================== Dictado =================== */
  function micLabel(iconName, text, cls) {
    var btn = $('mic-btn');
    btn.textContent = '';
    btn.classList.toggle('is-rec', cls === 'stop');
    if (cls === 'stop') btn.appendChild(el('span', 'stop-dot'));
    else btn.appendChild(App.icon(iconName));
    btn.appendChild(el('span', null, text));
  }

  var voice = window.Voice.create({
    textarea: answer,
    context: 'interview',
    silenceMs: 4000,   // en una entrevista se hacen pausas para pensar
    onState: function (st) {
      $('answer-box').classList.toggle('recording', st === 'listening');
      $('mic-btn').disabled = st === 'transcribing';
      clearInterval(timerId);
      if (st === 'listening') {
        App.tts.stop();
        micLabel(null, 'Detener', 'stop');
        orb('listening', 'Te está escuchando');
        var tick = function () {
          var s = $('answer-status');
          s.textContent = 'Escuchando · ' + App.formatTime(voice.elapsed());
          s.className = 'rec';
        };
        tick();
        timerId = setInterval(tick, 500);
      } else if (st === 'transcribing') {
        micLabel('i-mic', 'Transcribiendo…');
        $('answer-status').className = 'muted';
        $('answer-status').textContent = 'Transcribiendo tu respuesta…';
      } else {
        micLabel('i-mic', answer.value.trim() ? 'Seguir hablando' : 'Hablar');
        $('answer-status').className = 'muted';
        if (voice.added) $('answer-status').textContent = 'Revisa el texto y presiona «Enviar respuesta».';
        if (!busy) orb('idle', 'Te toca responder');
        if (pendingSend) { pendingSend = false; send(); }
      }
    },
    onStatus: function (text) { $('answer-status').className = 'muted'; $('answer-status').textContent = text; }
  });
  $('mic-btn').addEventListener('click', function () { voice.toggle(); });

  /* =================== Acciones =================== */
  function setBusy(value) {
    busy = value;
    ['send-btn', 'hint-btn', 'other-btn', 'next-btn', 'retry-btn', 'finish-btn'].forEach(function (id) { $(id).disabled = value; });
  }

  function call(path, body, thinkingText) {
    setBusy(true);
    App.tts.stop();
    orb('thinking', thinkingText);
    return App.api(path, body).then(function (data) {
      if (data.navigate) { window.location.href = data.navigate; return null; }
      if (data.state) state = data.state;
      return data;
    }).catch(function (err) {
      App.toast(err.message, true);
      orb('idle', 'Te toca responder');
      return null;
    }).then(function (data) { setBusy(false); return data; });
  }

  function send(textOverride) {
    if (busy) return;
    if (!textOverride && voice.state === 'listening') { pendingSend = true; voice.stop(); return; }
    if (voice.state === 'transcribing') { pendingSend = true; return; }
    var text = (textOverride || answer.value).trim();
    if (!text) { App.toast('Responde la pregunta antes de enviar.', true); return; }
    var elapsed = voice.elapsed();
    var body = {
      text: text,
      source: !textOverride && voice.added ? 'voice' : 'text',
      duration: Math.round(elapsed > 1 ? elapsed : (Date.now() - shownAt) / 1000)
    };
    var restore = textOverride ? function () {} : App.busyButton($('send-btn'), 'Evaluando…');
    call('/api/entrevista/responder', body, textOverride ? 'Pensando…' : 'Evaluando tu respuesta…').then(function (data) {
      restore();
      if (!data) return;
      if (data.kind === 'answer') renderHeader();
      render();
    });
  }

  $('send-btn').addEventListener('click', function () { send(); });
  answer.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }
  });
  $('hint-btn').addEventListener('click', function () { send('Dame una pista para responder esta pregunta'); });
  $('other-btn').addEventListener('click', function () {
    call('/api/entrevista/otra', {}, 'Buscando otra pregunta…').then(function (data) { if (data) render(); });
  });
  $('next-btn').addEventListener('click', function () {
    call('/api/entrevista/siguiente', {}, state.is_last ? 'Preparando tu reporte…' : 'Siguiente pregunta…')
      .then(function (data) { if (data) render(); });
  });
  $('retry-btn').addEventListener('click', function () {
    state.phase = 'question';
    state.interviewer = null;
    currentQuestionId = null;
    renderHeader();
    showQuestion();
    answer.focus();
  });
  $('finish-btn').addEventListener('click', function () {
    if (!window.confirm('¿Terminar la entrevista y ver tu reporte? Se califican las preguntas que ya respondiste.')) return;
    App.cover('Preparando tu reporte…');
    call('/api/entrevista/terminar', {}, 'Preparando tu reporte…').then(function () { App.cover(null); });
  });
  $('replay-btn').addEventListener('click', function () {
    if (!App.tts.enabled()) { App.toast('La lectura en voz alta está apagada en el menú de tu cuenta.'); return; }
    speakQuestion(true);
  });

  function paintTts() {
    var on = App.tts.enabled();
    $('tts-btn').lastElementChild.textContent = on ? 'Voz activada' : 'Voz apagada';
    $('tts-btn').setAttribute('aria-pressed', String(on));
    var toggle = $('tts-toggle');
    if (toggle) toggle.checked = on;
  }
  $('tts-btn').addEventListener('click', function () {
    App.storage.set('tts', App.tts.enabled() ? 'off' : 'on');
    if (!App.tts.enabled()) App.tts.stop();
    paintTts();
  });
  var ttsToggle = $('tts-toggle');
  if (ttsToggle) ttsToggle.addEventListener('change', paintTts);
  paintTts();

  if (state) showSession();
})();
