/* Dictado por voz.
   Orden: reconocimiento del navegador (en el dispositivo si el usuario lo eligió y está
   disponible) y, si falla, grabación + Whisper en el servidor. El texto siempre se escribe
   en el campo para que la persona lo revise antes de enviar. */
(function () {
  'use strict';

  var App = window.App;
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var MAX_SECONDS = 120;
  var settings = {
    pref: App.storage.get('voicePref') === 'local' ? 'local' : 'cloud',
    local: 'unknown',   // available | downloadable | downloading | unavailable | unsupported
    localLang: 'es-MX'
  };

  /* ---------- Ajustes del menú de cuenta ---------- */
  function updateNote() {
    var note = App.$('voice-note'), install = App.$('voice-install');
    if (!note) return;
    install.hidden = true;
    if (!SR) { note.textContent = 'Tu navegador no tiene dictado integrado: el audio se transcribe en el servidor.'; return; }
    if (settings.pref === 'cloud') { note.textContent = 'Usa el reconocimiento del navegador. Si falla, el audio se transcribe en el servidor.'; return; }
    var texts = {
      available: 'El español está listo en tu dispositivo: funciona sin internet.',
      downloadable: 'Descarga el español una vez para reconocer tu voz en tu dispositivo.',
      downloading: 'Descargando el español…',
      unavailable: 'Tu navegador no ofrece español en el dispositivo; se usará el del navegador.',
      unsupported: 'Requiere Chrome 139 o más reciente; mientras tanto se usará el del navegador.',
      unknown: 'Comprobando tu navegador…'
    };
    note.textContent = texts[settings.local] || '';
    install.hidden = settings.local !== 'downloadable';
  }

  // Solo se consulta cuando el usuario elige "En mi dispositivo", nunca al cargar la página.
  function checkLocal() {
    if (!SR || typeof SR.available !== 'function') { settings.local = 'unsupported'; updateNote(); return Promise.resolve(); }
    settings.local = 'unknown'; updateNote();
    var langs = ['es-MX', 'es-US', 'es-ES'];
    function tryLang(i) {
      if (i >= langs.length) { settings.local = 'unavailable'; updateNote(); return Promise.resolve(); }
      return Promise.resolve(SR.available({ langs: [langs[i]], processLocally: true })).then(function (result) {
        if (result === 'unavailable') return tryLang(i + 1);
        settings.local = result; settings.localLang = langs[i]; updateNote();
      });
    }
    return tryLang(0).catch(function () { settings.local = 'unsupported'; updateNote(); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var select = App.$('voice-pref');
    if (!select) return;
    select.value = settings.pref;
    select.addEventListener('change', function () {
      settings.pref = select.value;
      App.storage.set('voicePref', settings.pref);
      if (settings.pref === 'local' && settings.local === 'unknown') checkLocal(); else updateNote();
    });
    App.$('voice-install').addEventListener('click', function () {
      var btn = this;
      btn.disabled = true;
      settings.local = 'downloading'; updateNote();
      Promise.resolve(SR.install({ langs: [settings.localLang], processLocally: true }))
        .then(function (ok) { settings.local = ok ? 'available' : 'downloadable'; })
        .catch(function () { settings.local = 'downloadable'; })
        .then(function () { btn.disabled = false; updateNote(); });
    });
    updateNote();
  });

  /* ---------- Controlador de dictado ----------
     opts: { textarea, onState(state), onStatus(text) }
     estados: idle | listening | transcribing */
  function create(opts) {
    var ctrl = { state: 'idle', listened: 0, added: false };
    var rec = null, recorder = null, timer = null, startedAt = 0, fallback = false;

    function setState(state) {
      if (ctrl.state === 'listening' && state !== 'listening' && startedAt) {
        ctrl.listened += (Date.now() - startedAt) / 1000;
        startedAt = 0;
      }
      if (state === 'listening') startedAt = Date.now();
      ctrl.state = state;
      if (opts.onState) opts.onState(state);
    }
    function status(text) { if (opts.onStatus) opts.onStatus(text); }
    function write(base, text) {
      opts.textarea.value = (base + text).replace(/\s+$/, '');
      opts.textarea.dispatchEvent(new Event('input'));
    }
    function baseText() {
      var v = opts.textarea.value;
      return v.trim() ? v.replace(/\s+$/, '') + ' ' : '';
    }

    function startSpeech(useLocal) {
      rec = new SR();
      fallback = false;
      rec.lang = useLocal ? settings.localLang : 'es-MX';
      rec.continuous = true;
      rec.interimResults = true;
      if (useLocal && 'processLocally' in rec) rec.processLocally = true;
      var base = baseText(), heard = false;
      rec.onstart = function () { setState('listening'); timer = setTimeout(ctrl.stop, MAX_SECONDS * 1000); };
      rec.onresult = function (e) {
        var text = '';
        for (var i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
        if (text.trim()) { heard = true; write(base, text.trim()); }
      };
      rec.onerror = function (e) {
        if (e.error === 'network' || e.error === 'service-not-allowed' || e.error === 'language-not-supported') fallback = true;
        else if (e.error === 'not-allowed') status('Permite el acceso al micrófono en tu navegador.');
        else if (e.error === 'no-speech') status('No escuché nada. Acércate al micrófono e intenta de nuevo.');
      };
      rec.onend = function () {
        clearTimeout(timer);
        rec = null;
        if (fallback) { startRecorder(); return; }
        if (heard) ctrl.added = true;
        setState('idle');
      };
      try { rec.start(); } catch (err) { startRecorder(); }
    }

    function pickMime() {
      var types = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
      if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
      for (var i = 0; i < types.length; i++) if (MediaRecorder.isTypeSupported(types[i])) return types[i];
      return '';
    }

    function startRecorder() {
      if (!navigator.mediaDevices || !window.MediaRecorder) { setState('idle'); status('Tu navegador no permite grabar audio. Escribe tu respuesta.'); return; }
      navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
        .then(function (stream) {
          var mime = pickMime(), chunks = [];
          recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 64000 } : {});
          recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
          recorder.onstop = function () {
            clearTimeout(timer);
            stream.getTracks().forEach(function (t) { t.stop(); });
            var type = recorder.mimeType || mime || 'audio/webm';
            recorder = null;
            upload(new Blob(chunks, { type: type }), type);
          };
          recorder.start(250);
          setState('listening');
          timer = setTimeout(ctrl.stop, MAX_SECONDS * 1000);
        })
        .catch(function () { setState('idle'); status('Permite el acceso al micrófono en tu navegador.'); });
    }

    function upload(blob, type) {
      if (blob.size < 3000) { setState('idle'); status('La grabación fue muy corta. Intenta de nuevo.'); return; }
      setState('transcribing');
      var form = new FormData();
      form.append('audio', blob, 'audio');
      form.append('mime', type);
      App.api('/api/transcribe', form)
        .then(function (data) {
          if (data.text) { write(baseText(), data.text); ctrl.added = true; }
          else status('No se entendió el audio. Intenta de nuevo.');
        })
        .catch(function (err) { status(err.message); })
        .then(function () { setState('idle'); });
    }

    ctrl.start = function () {
      if (ctrl.state !== 'idle') return;
      App.tts.stop();
      if (!SR) { startRecorder(); return; }
      if (settings.pref !== 'local') { startSpeech(false); return; }
      var ready = settings.local === 'unknown' ? checkLocal() : Promise.resolve();
      ready.then(function () { startSpeech(settings.local === 'available'); });
    };
    ctrl.stop = function () {
      clearTimeout(timer);
      if (rec) { try { rec.stop(); } catch (e) { /* ya detenido */ } }
      if (recorder && recorder.state === 'recording') recorder.stop();
    };
    ctrl.toggle = function () { if (ctrl.state === 'listening') ctrl.stop(); else ctrl.start(); };
    ctrl.reset = function () { ctrl.listened = 0; ctrl.added = false; startedAt = 0; };
    ctrl.elapsed = function () {
      return ctrl.listened + (ctrl.state === 'listening' && startedAt ? (Date.now() - startedAt) / 1000 : 0);
    };
    return ctrl;
  }

  window.Voice = { create: create };
})();
