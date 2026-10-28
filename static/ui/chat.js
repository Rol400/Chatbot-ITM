/* Página de práctica: conversación, panel de la sesión y dictado por voz. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var state = JSON.parse($('initial-state').textContent);
  var busy = false;
  var voiceDraft = false; // el texto actual del campo vino (al menos en parte) de un dictado

  var DEFAULT_STATUS = 'Enter para enviar · Shift + Enter para salto de línea';
  var MODE_ICON = { interview: 'i-briefcase', grammar: 'i-pen' };

  /* ---------- Utilidades de DOM (todo con textContent: nada de HTML del servidor) ---------- */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function icon(name, size) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    if (size) { svg.style.width = size + 'px'; svg.style.height = size + 'px'; }
    var use = document.createElementNS(ns, 'use');
    use.setAttribute('href', '#' + name);
    svg.appendChild(use);
    return svg;
  }

  // Texto con **negritas** y saltos de línea, sin interpretar HTML.
  function rich(parent, text) {
    String(text || '').split('\n').forEach(function (line, i) {
      if (i > 0) parent.appendChild(document.createElement('br'));
      line.split(/\*\*(.+?)\*\*/g).forEach(function (part, j) {
        if (!part) return;
        parent.appendChild(j % 2 ? el('strong', null, part) : document.createTextNode(part));
      });
    });
    return parent;
  }

  function list(items) {
    var ul = el('ul', 'list');
    (items || []).forEach(function (item) { ul.appendChild(rich(el('li'), item)); });
    return ul;
  }

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function storageGet(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* sin almacenamiento */ } }

  /* ---------- API ---------- */

  function api(path, options) {
    options = options || {};
    var headers = { 'X-CSRFToken': csrfToken() };
    var body = options.body;
    if (body && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    return fetch(path, { method: options.method || 'POST', headers: headers, body: body, credentials: 'same-origin' })
      .then(function (response) {
        if (response.status === 401) { window.location.href = '/login?next=/chatbot'; throw new Error('Sesión expirada'); }
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok) throw new Error(data.error || 'Algo salió mal. Intenta de nuevo.');
          return data;
        });
      }, function () { throw new Error('No hay conexión con el servidor. Revisa tu internet.'); });
  }

  /* ---------- Mensajes ---------- */

  function metaLine(m) {
    var meta = el('div', 'meta');
    if (m.sender === 'user' && m.data && m.data.source === 'voice') {
      meta.appendChild(icon('i-mic'));
      meta.appendChild(document.createTextNode('Dictado por voz · '));
    }
    meta.appendChild(document.createTextNode(m.time || ''));
    if (m.data && m.data.source === 'intent') {
      var tag = el('span', 'local-tag');
      tag.title = 'Respondido por el modelo de intenciones entrenado para este proyecto, sin usar la API';
      tag.appendChild(icon('i-chip', 12));
      tag.appendChild(document.createTextNode('Modelo propio · ' + Math.round((m.data.confidence || 0) * 100) + '%'));
      meta.appendChild(tag);
    }
    return meta;
  }

  function feedbackCard(d) {
    var card = el('div', 'card');
    var head = el('div', 'card-head');
    head.appendChild(el('span', null, 'Retroalimentación'));
    if (d.scores) {
      var chips = el('div', 'chips-inline');
      [['claridad', 'Claridad'], ['estructura', 'Estructura'], ['seguridad', 'Seguridad']].forEach(function (pair) {
        if (d.scores[pair[0]] != null) chips.appendChild(el('span', 'chip-static', pair[1] + ' ' + d.scores[pair[0]] + '/5'));
      });
      head.appendChild(chips);
    }
    card.appendChild(head);

    var cols = el('div', 'card-section two-col');
    var good = el('div'); good.appendChild(el('div', 'eyebrow good-title', 'Lo que funcionó')); good.appendChild(list(d.feedback.good));
    var improve = el('div'); improve.appendChild(el('div', 'eyebrow improve-title', 'Para mejorar')); improve.appendChild(list(d.feedback.improve));
    cols.appendChild(good); cols.appendChild(improve);
    card.appendChild(cols);

    if (d.fillers && d.fillers.length) card.appendChild(fillerSection(d.fillers));
    if (d.feedback.example) {
      var ex = el('div', 'card-section');
      ex.appendChild(el('div', 'eyebrow', 'Prueba algo así'));
      ex.appendChild(el('div', 'example', '«' + d.feedback.example + '»'));
      card.appendChild(ex);
    }
    return card;
  }

  function fillerSection(fillers) {
    var counts = {};
    fillers.forEach(function (f) { counts[f] = (counts[f] || 0) + 1; });
    var section = el('div', 'card-section');
    section.appendChild(el('div', 'eyebrow', 'Muletillas detectadas'));
    var chips = el('div', 'chips-inline');
    Object.keys(counts).forEach(function (f) {
      chips.appendChild(el('span', 'chip-static chip-filler', f + (counts[f] > 1 ? ' · ' + counts[f] : '')));
    });
    section.appendChild(chips);
    return section;
  }

  function correctionCard(d) {
    var card = el('div', 'card');
    var head = el('div', 'card-head');
    head.appendChild(el('span', null, d.errors && d.errors.length ? 'Tu texto, corregido' : 'Tu texto está bien'));
    var copy = el('button', 'btn btn-quiet');
    copy.type = 'button';
    copy.style.minHeight = '36px';
    copy.appendChild(icon('i-copy', 15));
    copy.appendChild(document.createTextNode('Copiar'));
    copy.addEventListener('click', function () {
      if (navigator.clipboard) navigator.clipboard.writeText(d.corrected || '').then(function () {
        copy.lastChild.textContent = 'Copiado';
        setTimeout(function () { copy.lastChild.textContent = 'Copiar'; }, 1500);
      });
    });
    head.appendChild(copy);
    card.appendChild(head);

    var body = el('div', 'card-section corrected');
    (d.segments || []).forEach(function (seg) {
      if (seg.space) body.appendChild(document.createTextNode(' '));
      if (seg.type === 'eq') body.appendChild(document.createTextNode(seg.text));
      else {
        var span = el('span', seg.type === 'del' ? 'seg-del' : 'seg-ins', seg.text);
        if (seg.type === 'del') span.setAttribute('aria-label', 'quitar: ' + seg.text);
        else span.setAttribute('aria-label', 'agregar: ' + seg.text);
        body.appendChild(span);
      }
    });
    card.appendChild(body);

    if (d.errors && d.errors.length) {
      var errs = el('div', 'card-section');
      errs.style.display = 'flex'; errs.style.flexDirection = 'column'; errs.style.gap = '10px';
      d.errors.forEach(function (e) {
        var row = el('div', 'error-row');
        row.appendChild(el('span', 'error-type', e.type));
        var txt = el('span');
        txt.appendChild(el('strong', null, e.wrong + ' → ' + e.right));
        if (e.explanation) txt.appendChild(document.createTextNode('. ' + e.explanation));
        row.appendChild(txt);
        errs.appendChild(row);
      });
      card.appendChild(errs);
    }
    if (d.fillers && d.fillers.length) card.appendChild(fillerSection(d.fillers));
    if (d.tip) {
      var tip = el('div', 'card-section tip');
      tip.appendChild(icon('i-bulb'));
      tip.appendChild(rich(el('span'), d.tip));
      card.appendChild(tip);
    }
    return card;
  }

  function summaryCard(d) {
    var card = el('div', 'card');
    card.appendChild(el('div', 'card-head', 'Calificación final'));
    var top = el('div', 'card-section');
    if (d.score != null) {
      var score = el('div', 'score-big');
      score.appendChild(el('strong', null, String(d.score)));
      score.appendChild(el('span', null, '/ 10'));
      top.appendChild(score);
    }
    if (d.summary) top.appendChild(rich(el('p'), d.summary));
    card.appendChild(top);
    var cols = el('div', 'card-section two-col');
    var a = el('div'); a.appendChild(el('div', 'eyebrow good-title', 'Fortalezas')); a.appendChild(list(d.strengths));
    var b = el('div'); b.appendChild(el('div', 'eyebrow improve-title', 'Qué practicar')); b.appendChild(list(d.improve));
    cols.appendChild(a); cols.appendChild(b);
    card.appendChild(cols);
    var actions = el('div', 'card-section');
    var again = el('button', 'btn btn-primary', 'Practicar de nuevo');
    again.type = 'button';
    again.addEventListener('click', function () { startMode(state.session.mode, false); });
    actions.appendChild(again);
    card.appendChild(actions);
    return card;
  }

  function renderMessage(m) {
    if (m.sender === 'user') {
      var wrap = el('div', 'msg-user');
      wrap.appendChild(el('div', 'user-bubble', m.text));
      wrap.appendChild(metaLine(m));
      return wrap;
    }
    if (m.kind === 'notice') {
      return rich(el('div', 'notice' + (m.data && m.data.error ? ' error' : '')), m.text);
    }
    var row = el('div', 'msg-bot');
    var badge = el('div', 'bot-badge');
    badge.appendChild(icon(MODE_ICON[state.session ? state.session.mode : 'grammar']));
    row.appendChild(badge);
    var body = el('div', 'bot-body');
    var d = m.data || {};
    if (m.kind === 'summary') body.appendChild(summaryCard(d));
    else if (m.text) body.appendChild(rich(el('div', 'bot-text'), m.text));
    if (m.kind === 'feedback' && d.feedback) body.appendChild(feedbackCard(d));
    if (m.kind === 'correction') body.appendChild(correctionCard(d));
    if (d.next_question) {
      var q = el('div', 'question');
      var total = state.session ? state.session.total_questions : '';
      q.appendChild(el('div', 'question-label', 'Pregunta ' + (d.question_number || '') + (total ? ' de ' + total : '')));
      q.appendChild(el('div', 'question-text', d.next_question));
      body.appendChild(q);
    }
    body.appendChild(metaLine(m));
    row.appendChild(body);
    return row;
  }

  function typingNode() {
    var row = el('div', 'msg-bot');
    row.id = 'typing';
    var badge = el('div', 'bot-badge');
    badge.appendChild(icon(MODE_ICON[state.session ? state.session.mode : 'grammar']));
    row.appendChild(badge);
    var dots = el('div', 'typing');
    dots.setAttribute('aria-label', 'Escribiendo');
    dots.appendChild(el('span')); dots.appendChild(el('span')); dots.appendChild(el('span'));
    row.appendChild(dots);
    return row;
  }

  function scrollToEnd() {
    var scroll = $('scroll');
    requestAnimationFrame(function () { scroll.scrollTop = scroll.scrollHeight; });
  }

  /* ---------- Sugerencias, panel y encabezado ---------- */

  function suggestionList() {
    var s = state.session;
    if (!s) return [];
    if (s.finished) return [{ label: 'Practicar de nuevo', action: 'new' }];
    if (s.mode === 'interview') {
      if (!s.role) return ['Desarrollador web', 'Contador', 'Atención a clientes', 'Enfermería'].map(function (t) { return { label: t }; });
      return [{ label: 'Dame una pista' }, { label: 'Dame un ejemplo' }, { label: 'Otra pregunta' },
              { label: 'Terminar y calificarme', action: 'finish' }];
    }
    return [{ label: 'Dame un ejercicio' }, { label: 'Explícame el último error' },
            { label: 'Terminar y calificarme', action: 'finish' }];
  }

  function renderSuggestions() {
    var box = $('suggestions');
    box.textContent = '';
    suggestionList().forEach(function (s) {
      var chip = el('button', 'chip', s.label);
      chip.type = 'button';
      chip.addEventListener('click', function () {
        if (s.action === 'new') startMode(state.session.mode, false);
        else if (s.action === 'finish') sendMessage(s.label, { action: 'finish' });
        else sendMessage(s.label);
      });
      box.appendChild(chip);
    });
  }

  function metricNode(label, value, max) {
    var metric = el('div', 'metric');
    var row = el('div', 'metric-row');
    row.appendChild(el('span', null, label));
    row.appendChild(el('strong', null, value == null ? '—' : value + ' / ' + max));
    metric.appendChild(row);
    var bar = el('div', 'bar');
    var fill = el('div');
    fill.style.width = value == null ? '0%' : Math.round((value / max) * 100) + '%';
    bar.appendChild(fill);
    metric.appendChild(bar);
    return metric;
  }

  function renderPanel() {
    var panel = $('panel');
    var body = $('panel-body');
    var s = state.session, st = state.stats;
    panel.hidden = !s;
    $('session-pill').hidden = !s;
    if (!s || !st) return;
    body.textContent = '';
    body.style.display = 'flex'; body.style.flexDirection = 'column'; body.style.gap = '20px';

    var head = el('div');
    head.appendChild(el('h2', null, 'Esta sesión'));
    var big = el('div', 'score-big');
    var pill;
    if (s.mode === 'interview') {
      var value = s.finished && s.score != null ? s.score : null;
      big.appendChild(el('strong', null, value != null ? String(value) : s.questions_asked + ' / ' + s.total_questions));
      big.appendChild(el('span', null, value != null ? '/ 10' : 'preguntas'));
      head.appendChild(big);
      head.appendChild(el('div', 'empty-note', s.role ? 'Puesto: ' + s.role : 'Aún no eliges el puesto'));
      pill = value != null ? value + '/10' : s.questions_asked + '/' + s.total_questions;
    } else {
      var avg = s.finished && s.score != null ? s.score : st.average;
      big.appendChild(el('strong', null, avg != null ? String(avg) : '—'));
      big.appendChild(el('span', null, '/ 10'));
      head.appendChild(big);
      head.appendChild(el('div', 'empty-note', st.texts === 1 ? '1 texto revisado' : st.texts + ' textos revisados'));
      pill = avg != null ? avg + '/10' : 'Sesión';
    }
    $('session-pill-text').textContent = pill;
    body.appendChild(head);

    if (s.mode === 'interview') {
      body.appendChild(metricNode('Avance', s.questions_asked, s.total_questions));
    }
    var hasMetric = st.metrics.some(function (m) { return m.value != null; });
    if (hasMetric) {
      var metrics = el('div');
      metrics.style.display = 'flex'; metrics.style.flexDirection = 'column'; metrics.style.gap = '12px';
      st.metrics.forEach(function (m) { metrics.appendChild(metricNode(m.label, m.value, m.max)); });
      body.appendChild(metrics);
    } else {
      body.appendChild(el('div', 'empty-note', s.mode === 'interview'
        ? 'Tus calificaciones aparecerán cuando respondas la primera pregunta.'
        : 'Tus calificaciones aparecerán cuando revises tu primer texto.'));
    }

    if (s.mode === 'grammar' && st.errors && st.errors.length) {
      body.appendChild(el('div', 'panel-divider'));
      var errs = el('div');
      errs.appendChild(el('h2', null, 'Errores frecuentes'));
      var listBox = el('div');
      listBox.style.display = 'flex'; listBox.style.flexDirection = 'column'; listBox.style.gap = '8px'; listBox.style.marginTop = '10px';
      st.errors.forEach(function (e) {
        var row = el('div', 'error-freq');
        row.appendChild(el('span', null, e.wrong + ' → ' + e.right));
        row.appendChild(el('span', null, e.count + '×'));
        listBox.appendChild(row);
      });
      errs.appendChild(listBox);
      body.appendChild(errs);
    }

    if (st.fillers && st.fillers.length) {
      body.appendChild(el('div', 'panel-divider'));
      var fill = el('div');
      fill.appendChild(el('h2', null, 'Muletillas'));
      var chips = el('div', 'chips-inline');
      chips.style.marginTop = '10px';
      st.fillers.forEach(function (f) { chips.appendChild(el('span', 'chip-static chip-filler', f.word + ' · ' + f.count)); });
      fill.appendChild(chips);
      body.appendChild(fill);
    }
  }

  function render() {
    var s = state.session;
    ['interview', 'grammar'].forEach(function (mode) {
      $('tab-' + mode).setAttribute('aria-selected', s && s.mode === mode ? 'true' : 'false');
    });
    $('welcome').hidden = !!s;
    $('composer-wrap').hidden = !s;
    $('new-session').hidden = !s;
    $('input').placeholder = !s ? '' : s.mode === 'interview'
      ? (s.role ? 'Escribe o dicta tu respuesta…' : 'Escribe el puesto para el que practicas…')
      : 'Escribe o dicta un texto para revisarlo…';

    var box = $('messages');
    box.textContent = '';
    state.messages.forEach(function (m) { box.appendChild(renderMessage(m)); });
    renderSuggestions();
    renderPanel();
    scrollToEnd();
  }

  function showTransientNotice(text) {
    var notice = el('div', 'notice error', text);
    $('messages').appendChild(notice);
    scrollToEnd();
    setTimeout(function () { if (notice.parentNode) notice.parentNode.removeChild(notice); }, 7000);
  }

  /* ---------- Acciones ---------- */

  function setBusy(value) {
    busy = value;
    $('send').disabled = value;
    Array.prototype.forEach.call(document.querySelectorAll('.chip, .tab, .mode-card'), function (b) { b.disabled = value; });
  }

  function startMode(mode, resume) {
    if (busy) return;
    stopVoice();
    setBusy(true);
    api('/api/session', { body: { mode: mode, resume: !!resume } })
      .then(function (data) { state = data; render(); $('input').focus(); })
      .catch(function (err) { showTransientNotice(err.message); })
      .then(function () { setBusy(false); });
  }

  function sendMessage(text, opts) {
    opts = opts || {};
    text = (text || '').trim();
    if (busy || (!text && !opts.action)) return;
    stopVoice();
    var source = opts.source || 'text';
    var box = $('messages');
    var temp = renderMessage({ sender: 'user', text: text, time: '', data: { source: source } });
    box.appendChild(temp);
    box.appendChild(typingNode());
    scrollToEnd();
    setBusy(true);

    api('/api/message', { body: { text: text, source: source, action: opts.action || null } })
      .then(function (data) {
        if (data.reload) {
          state = data;
        } else {
          state.messages = state.messages.concat(data.messages);
          state.session = data.session;
          state.stats = data.stats;
        }
        render();
      })
      .catch(function (err) {
        if (temp.parentNode) temp.parentNode.removeChild(temp);
        if (opts.fromComposer && !$('input').value) $('input').value = text;
        autoresize();
        showTransientNotice(err.message);
      })
      .then(function () {
        var typing = $('typing');
        if (typing) typing.parentNode.removeChild(typing);
        setBusy(false);
      });
  }

  /* ---------- Compositor ---------- */

  var input = $('input');

  function autoresize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 180) + 'px';
  }

  input.addEventListener('input', function () {
    autoresize();
    if (!input.value.trim()) voiceDraft = false;
  });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $('composer').requestSubmit ? $('composer').requestSubmit() : submitComposer();
    }
  });
  function submitComposer() {
    var text = input.value;
    if (!text.trim() || busy) return;
    var source = voiceDraft ? 'voice' : 'text';
    input.value = '';
    voiceDraft = false;
    autoresize();
    sendMessage(text, { source: source, fromComposer: true });
  }
  $('composer').addEventListener('submit', function (e) { e.preventDefault(); submitComposer(); });

  /* ---------- Pestañas, menú, tema, panel ---------- */

  Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (tab) {
    tab.addEventListener('click', function () {
      var mode = tab.dataset.mode;
      if (state.session && state.session.mode === mode) return;
      startMode(mode, true);
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-start]'), function (card) {
    card.addEventListener('click', function () { startMode(card.dataset.start, true); });
  });
  $('new-session').addEventListener('click', function () { if (state.session) startMode(state.session.mode, false); });

  var accountBtn = $('account-btn'), menu = $('account-menu');
  function closeMenu() { menu.hidden = true; accountBtn.setAttribute('aria-expanded', 'false'); }
  accountBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    accountBtn.setAttribute('aria-expanded', String(!menu.hidden));
  });
  document.addEventListener('click', function (e) { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });

  var panel = $('panel'), pillBtn = $('session-pill');
  function setPanel(open) { panel.classList.toggle('open', open); pillBtn.setAttribute('aria-expanded', String(open)); }
  pillBtn.addEventListener('click', function () { setPanel(!panel.classList.contains('open')); });
  $('panel-close').addEventListener('click', function () { setPanel(false); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeMenu(); setPanel(false); }
  });

  function currentTheme() {
    var t = document.documentElement.dataset.theme;
    if (t) return t;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function paintThemeIcon() {
    var dark = currentTheme() === 'dark';
    $('theme-icon').setAttribute('href', dark ? '#i-sun' : '#i-moon');
    $('theme-toggle').setAttribute('aria-label', dark ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro');
  }
  $('theme-toggle').addEventListener('click', function () {
    var next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    storageSet('theme', next);
    paintThemeIcon();
  });

  /* ---------- Voz ----------
     Orden: 1) reconocimiento en el dispositivo (Chrome 139+), 2) reconocimiento del
     navegador en la nube, 3) grabación + Whisper en el servidor como respaldo.
     El texto dictado se queda en el campo para revisarlo antes de enviar. */

  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var storedPref = storageGet('voicePref');
  var voice = {
    pref: storedPref === 'local' ? 'local' : 'cloud',
    local: 'unknown',     // available | downloadable | downloading | unavailable | unsupported
    localLang: 'es-MX',
    mode: 'idle',         // idle | listening | transcribing
    rec: null, recorder: null, stream: null, chunks: [],
    fallback: false, timer: null, added: false
  };
  var MAX_SECONDS = 90;

  function setStatus(content, recording) {
    var status = $('status');
    status.textContent = '';
    status.classList.toggle('hint', !content);
    if (recording) status.appendChild(el('span', 'rec-dot'));
    status.appendChild(document.createTextNode(content || DEFAULT_STATUS));
  }

  function setMic(mode) {
    voice.mode = mode;
    var mic = $('mic');
    mic.classList.toggle('listening', mode === 'listening');
    mic.classList.toggle('busy', mode === 'transcribing');
    mic.disabled = mode === 'transcribing';
    $('mic-icon').setAttribute('href', mode === 'listening' ? '#i-stop' : '#i-mic');
    mic.setAttribute('aria-label', mode === 'listening' ? 'Detener dictado' : 'Dictar por voz');
    if (mode === 'idle') setStatus(voice.added ? 'Revisa el texto dictado y envíalo cuando esté listo.' : DEFAULT_STATUS);
  }

  function updateVoiceNote() {
    var note = $('voice-note'), install = $('voice-install');
    install.hidden = true;
    if (!SR) {
      note.textContent = 'Tu navegador no tiene dictado integrado: se grabará el audio y se transcribirá en el servidor.';
      return;
    }
    if (voice.pref === 'cloud') {
      note.textContent = 'Tu voz se reconoce con el servicio del navegador. Si falla, se graba y se transcribe en el servidor.';
      return;
    }
    var messages = {
      available: 'El español está listo en tu dispositivo: funciona sin internet y tu voz no sale de tu computadora.',
      downloadable: 'Descarga el español una sola vez para reconocer tu voz en tu dispositivo.',
      downloading: 'Descargando el español para tu dispositivo…',
      unavailable: 'Tu navegador no ofrece español en el dispositivo; se usará el servicio del navegador.',
      unsupported: 'Tu navegador no permite reconocer la voz en el dispositivo (requiere Chrome 139 o más reciente); se usará el servicio del navegador.',
      unknown: 'Comprobando tu navegador…'
    };
    note.textContent = messages[voice.local] || '';
    install.hidden = voice.local !== 'downloadable';
  }

  // Solo se consulta cuando el usuario elige "En mi dispositivo", nunca al cargar la página.
  function checkLocal() {
    if (!SR || typeof SR.available !== 'function') {
      voice.local = 'unsupported'; updateVoiceNote(); return Promise.resolve();
    }
    voice.local = 'unknown'; updateVoiceNote();
    var langs = ['es-MX', 'es-US', 'es-ES'];
    function tryNext(i) {
      if (i >= langs.length) { voice.local = 'unavailable'; updateVoiceNote(); return Promise.resolve(); }
      return Promise.resolve(SR.available({ langs: [langs[i]], processLocally: true }))
        .then(function (result) {
          if (result === 'unavailable') return tryNext(i + 1);
          voice.local = result; voice.localLang = langs[i]; updateVoiceNote();
        });
    }
    return tryNext(0).catch(function () { voice.local = 'unsupported'; updateVoiceNote(); });
  }

  $('voice-pref').value = voice.pref;
  $('voice-pref').addEventListener('change', function () {
    voice.pref = this.value;
    storageSet('voicePref', voice.pref);
    if (voice.pref === 'local' && voice.local === 'unknown') checkLocal();
    else updateVoiceNote();
  });
  $('voice-install').addEventListener('click', function () {
    var btn = this;
    btn.disabled = true;
    voice.local = 'downloading'; updateVoiceNote();
    Promise.resolve(SR.install({ langs: [voice.localLang], processLocally: true }))
      .then(function (ok) { voice.local = ok ? 'available' : 'downloadable'; })
      .catch(function () { voice.local = 'downloadable'; })
      .then(function () { btn.disabled = false; updateVoiceNote(); });
  });

  function insertDictation(base, text) {
    input.value = (base + text).replace(/\s+$/, '');
    autoresize();
  }

  function startSpeech(useLocal) {
    var rec = new SR();
    voice.rec = rec;
    voice.fallback = false;
    rec.lang = useLocal ? voice.localLang : 'es-MX';
    rec.continuous = true;
    rec.interimResults = true;
    if (useLocal && 'processLocally' in rec) rec.processLocally = true;
    var base = input.value.trim() ? input.value.replace(/\s+$/, '') + ' ' : '';
    var heard = false;

    rec.onstart = function () {
      setMic('listening');
      setStatus(useLocal ? 'Escuchando en tu dispositivo… toca para terminar' : 'Escuchando… toca para terminar', true);
      voice.timer = setTimeout(stopVoice, MAX_SECONDS * 1000);
    };
    rec.onresult = function (e) {
      var text = '';
      for (var i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      if (text.trim()) { heard = true; insertDictation(base, text.trim()); }
    };
    rec.onerror = function (e) {
      if (e.error === 'network' || e.error === 'service-not-allowed' || e.error === 'language-not-supported') {
        voice.fallback = true; // se usará la grabación con Whisper
      } else if (e.error === 'not-allowed') {
        setStatus('Permite el acceso al micrófono en tu navegador para dictar.');
      } else if (e.error === 'no-speech') {
        setStatus('No escuché nada. Intenta de nuevo, más cerca del micrófono.');
      }
    };
    rec.onend = function () {
      clearTimeout(voice.timer);
      voice.rec = null;
      if (voice.fallback) { voice.fallback = false; startRecorder(true); return; }
      if (heard) { voiceDraft = true; voice.added = true; }
      var status = $('status').textContent;
      setMic('idle');
      if (!heard && /micrófono|escuché/.test(status)) setStatus(status);
      input.focus();
    };
    try { rec.start(); } catch (err) { startRecorder(true); }
  }

  function pickMime() {
    var types = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
    for (var i = 0; i < types.length; i++) if (MediaRecorder.isTypeSupported(types[i])) return types[i];
    return '';
  }

  function startRecorder(isFallback) {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      setMic('idle');
      setStatus('Tu navegador no permite grabar audio. Escribe tu mensaje.');
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      .then(function (stream) {
        var mime = pickMime();
        var recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 64000 } : {});
        voice.stream = stream; voice.recorder = recorder; voice.chunks = [];
        recorder.ondataavailable = function (e) { if (e.data && e.data.size) voice.chunks.push(e.data); };
        recorder.onstop = function () {
          clearTimeout(voice.timer);
          stream.getTracks().forEach(function (t) { t.stop(); });
          var type = recorder.mimeType || mime || 'audio/webm';
          var blob = new Blob(voice.chunks, { type: type });
          voice.recorder = null; voice.stream = null;
          uploadAudio(blob, type);
        };
        recorder.start(250);
        setMic('listening');
        setStatus(isFallback ? 'Grabando (modo alternativo)… toca para terminar' : 'Grabando… toca para terminar', true);
        voice.timer = setTimeout(stopVoice, MAX_SECONDS * 1000);
      })
      .catch(function () {
        setMic('idle');
        setStatus('Permite el acceso al micrófono en tu navegador para dictar.');
      });
  }

  function uploadAudio(blob, type) {
    if (blob.size < 3000) { setMic('idle'); setStatus('La grabación fue muy corta. Intenta de nuevo.'); return; }
    setMic('transcribing');
    setStatus('Transcribiendo…');
    var form = new FormData();
    form.append('audio', blob, 'audio');
    form.append('mime', type);
    api('/api/transcribe', { body: form })
      .then(function (data) {
        if (data.text) {
          var base = input.value.trim() ? input.value.replace(/\s+$/, '') + ' ' : '';
          insertDictation(base, data.text);
          voiceDraft = true; voice.added = true;
          setMic('idle');
        } else {
          setMic('idle');
          setStatus('No se entendió el audio. Intenta de nuevo.');
        }
        input.focus();
      })
      .catch(function (err) { setMic('idle'); setStatus(err.message); });
  }

  function startVoice() {
    voice.added = false;
    if (!SR) { startRecorder(false); return; }
    if (voice.pref !== 'local') { startSpeech(false); return; }
    var ready = voice.local === 'unknown' ? checkLocal() : Promise.resolve();
    ready.then(function () { startSpeech(voice.local === 'available'); });
  }

  function stopVoice() {
    clearTimeout(voice.timer);
    if (voice.rec) { try { voice.rec.stop(); } catch (e) { /* ya detenido */ } }
    if (voice.recorder && voice.recorder.state === 'recording') voice.recorder.stop();
  }

  $('mic').addEventListener('click', function () {
    if (voice.mode === 'listening') stopVoice();
    else if (voice.mode === 'idle') startVoice();
  });

  /* ---------- Inicio ---------- */
  paintThemeIcon();
  updateVoiceNote();
  render();
  autoresize();
})();
