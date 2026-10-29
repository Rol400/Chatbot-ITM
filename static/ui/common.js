/* Utilidades compartidas: DOM seguro, API con CSRF, avisos, menú de cuenta y lectura en voz alta. */
(function () {
  'use strict';

  var App = {};

  App.$ = function (id) { return document.getElementById(id); };

  App.el = function (tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };

  App.icon = function (name, size) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    if (size) { svg.style.width = size + 'px'; svg.style.height = size + 'px'; }
    var use = document.createElementNS(ns, 'use');
    use.setAttribute('href', '#' + name);
    svg.appendChild(use);
    return svg;
  };

  // Texto con **negritas**, sin interpretar HTML.
  App.rich = function (parent, text) {
    parent.textContent = '';
    String(text || '').split('\n').forEach(function (line, i) {
      if (i > 0) parent.appendChild(document.createElement('br'));
      line.split(/\*\*(.+?)\*\*/g).forEach(function (part, j) {
        if (part) parent.appendChild(j % 2 ? App.el('strong', null, part) : document.createTextNode(part));
      });
    });
    return parent;
  };

  // Marca las muletillas dentro de un texto.
  App.markFillers = function (parent, text, fillers) {
    parent.textContent = '';
    var words = (fillers || []).filter(function (f, i, all) { return f && all.indexOf(f) === i; });
    if (!words.length) { parent.textContent = text; return parent; }
    var escaped = words.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); });
    var re = new RegExp('(^|[^\\p{L}])(' + escaped.join('|') + ')(?=$|[^\\p{L}])', 'giu');
    var last = 0, match;
    while ((match = re.exec(text))) {
      var start = match.index + match[1].length;
      parent.appendChild(document.createTextNode(text.slice(last, start)));
      parent.appendChild(App.el('mark', 'filler', match[2]));
      last = start + match[2].length;
    }
    parent.appendChild(document.createTextNode(text.slice(last)));
    return parent;
  };

  App.formatTime = function (seconds) {
    seconds = Math.max(0, Math.round(seconds || 0));
    return String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
  };

  App.storage = {
    get: function (key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set: function (key, value) { try { localStorage.setItem(key, value); } catch (e) { /* sin almacenamiento */ } }
  };

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  App.api = function (path, body) {
    var headers = { 'X-CSRFToken': csrfToken() };
    var payload = body;
    if (body && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    return fetch(path, { method: 'POST', headers: headers, body: payload || '{}', credentials: 'same-origin' })
      .then(function (response) {
        if (response.status === 401) { window.location.href = '/login?next=' + encodeURIComponent(location.pathname); throw new Error('Tu sesión expiró.'); }
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok) throw new Error(data.error || 'Algo salió mal. Intenta de nuevo.');
          return data;
        });
      }, function () { throw new Error('No hay conexión con el servidor. Revisa tu internet.'); });
  };

  var toastTimer;
  App.toast = function (text, isError) {
    var node = App.$('toast');
    if (!node) { node = App.el('div', 'toast'); node.id = 'toast'; node.setAttribute('role', 'status'); document.body.appendChild(node); }
    node.textContent = text;
    node.className = 'toast' + (isError ? ' error' : '');
    node.hidden = true;
    void node.offsetWidth; // reinicia la animación de entrada
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.hidden = true; }, 6000);
  };

  /* Reinicia una animación de CSS quitando y volviendo a poner la clase. */
  App.replay = function (node, cls) {
    if (!node) return;
    node.classList.remove(cls);
    void node.offsetWidth;
    node.classList.add(cls);
  };

  /* Anillo de puntaje que se llena y número que cuenta hacia arriba. */
  App.fillRing = function (ring, scoreNode, score) {
    ring.style.setProperty('--deg', '0deg');
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { ring.style.setProperty('--deg', Math.round(score * 3.6) + 'deg'); });
    });
    if (!scoreNode) return;
    if (reduce) { scoreNode.textContent = score; return; }
    var start = null, duration = 1000;
    function step(t) {
      if (start === null) start = t;
      var k = Math.min(1, (t - start) / duration);
      scoreNode.textContent = Math.round(score * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  };

  /* Pone un botón en modo "ocupado" con girito; devuelve una función para restaurarlo. */
  App.busyButton = function (btn, label) {
    if (!btn) return function () {};
    var saved = Array.prototype.slice.call(btn.childNodes);
    btn.textContent = '';
    btn.appendChild(App.el('span', 'spinner'));
    btn.appendChild(App.el('span', null, label));
    btn.classList.add('is-loading');
    return function () {
      btn.textContent = '';
      saved.forEach(function (n) { btn.appendChild(n); });
      btn.classList.remove('is-loading');
    };
  };

  App.cover = function (text) {
    var node = App.$('loading-cover');
    if (!text) { if (node) node.hidden = true; return; }
    if (!node) {
      node = App.el('div', 'loading-cover');
      node.id = 'loading-cover';
      var orb = App.el('div', 'orb md');
      orb.style.animation = 'breathe 1.4s ease-in-out infinite';
      node.appendChild(orb);
      node.appendChild(App.el('span'));
      document.body.appendChild(node);
    }
    node.lastChild.textContent = text;
    node.hidden = false;
  };

  /* ---- Lectura en voz alta (voz del navegador, gratis) ---- */
  App.tts = {
    enabled: function () { return App.storage.get('tts') !== 'off'; },
    speak: function (text, onEnd) {
      if (!window.speechSynthesis || !App.tts.enabled() || !text) { if (onEnd) onEnd(); return; }
      window.speechSynthesis.cancel();
      var utter = new SpeechSynthesisUtterance(text.replace(/\*\*/g, ''));
      utter.lang = 'es-MX';
      var voices = window.speechSynthesis.getVoices();
      var voice = voices.find(function (v) { return v.lang === 'es-MX'; }) ||
                  voices.find(function (v) { return v.lang && v.lang.indexOf('es') === 0; });
      if (voice) utter.voice = voice;
      utter.rate = 1;
      utter.onend = utter.onerror = function () { if (onEnd) onEnd(); };
      window.speechSynthesis.speak(utter);
    },
    stop: function () { if (window.speechSynthesis) window.speechSynthesis.cancel(); }
  };

  /* ---- Menú de cuenta ---- */
  document.addEventListener('DOMContentLoaded', function () {
    var btn = App.$('account-btn'), menu = App.$('account-menu');
    if (btn && menu) {
      var close = function () { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        menu.hidden = !menu.hidden;
        btn.setAttribute('aria-expanded', String(!menu.hidden));
      });
      document.addEventListener('click', function (e) { if (!menu.hidden && !menu.contains(e.target)) close(); });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    }
    var tts = App.$('tts-toggle');
    if (tts) {
      tts.checked = App.tts.enabled();
      tts.addEventListener('change', function () {
        App.storage.set('tts', tts.checked ? 'on' : 'off');
        if (!tts.checked) App.tts.stop();
      });
    }
  });

  window.App = App;
})();
