/* Dictado por voz.
   Computadora: reconocimiento del navegador (en el dispositivo si el usuario lo eligió y
   está disponible) y, si falla, grabación + Whisper en el servidor.
   Celular: grabación + Whisper, porque el reconocimiento del navegador en Android repite
   palabras y llega con retraso (salvo que el español en el dispositivo esté instalado).
   La grabación se detiene sola tras unos segundos de silencio.
   El texto siempre se escribe en el campo para que la persona lo revise antes de enviar.
   opciones de create(): context (chat|interview|practice|grammar) y silenceMs (0 = sin corte). */
(function () {
  'use strict';

  var App = window.App;
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var MAX_SECONDS = 120;
  var BITRATE = 32000;        // voz en un canal: 32 kbps suena igual y pesa la mitad
  var SILENCE_MS = 2500;      // silencio tras hablar para detener solo
  var NO_SPEECH_MS = 8000;    // sin voz desde el inicio: se detiene sin gastar transcripción
  var IS_MOBILE = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints > 1 && /Macintosh/.test(navigator.userAgent));
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
    if (settings.pref === 'cloud') {
      note.textContent = IS_MOBILE
        ? 'En celular tu voz se graba y se transcribe en el servidor al terminar: es más preciso.'
        : 'Usa el reconocimiento del navegador. Si falla, el audio se transcribe en el servidor.';
      return;
    }
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

  /* ---------- Unión de resultados sin repetir ----------
     En celulares (sobre todo Chrome en Android) el modo continuo repite el texto ya
     reconocido en cada resultado nuevo: "hola" + "hola" o "hola" + "hola cómo estás".
     Si se concatenan tal cual sale "hola hola". Aquí se fusionan sin repetir. */
  function normSpeech(s) {
    return s.toLowerCase().replace(/[.,;:¿?¡!"]/g, '').replace(/\s+/g, ' ').trim();
  }
  function mergeSpeech(a, b) {
    var na = normSpeech(a), nb = normSpeech(b);
    if (!na) return b;
    if (!nb) return a;
    if (nb === na || nb.indexOf(na + ' ') === 0) return b;          // b ya trae todo lo de a
    if (na.indexOf(nb + ' ') === 0 || na.slice(-(nb.length + 1)) === ' ' + nb) return a; // b es repetido
    return a + ' ' + b;
  }
  function buildTranscript(results) {
    var text = '';
    for (var i = 0; i < results.length; i++) {
      var t = (results[i][0].transcript || '').trim();
      if (!t) continue;
      text = IS_MOBILE ? mergeSpeech(text, t) : (text ? text + ' ' + t : t);
    }
    return text;
  }

  /* ---------- Detección de silencio ----------
     El AudioContext se crea dentro del toque del usuario (si no, iOS lo deja suspendido).
     Si no queda activo, el vigilante no hace nada y la grabación funciona como antes. */
  var audioCtx = null;
  function primeAudio() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    try {
      if (!audioCtx) audioCtx = new Ctx();
      if (audioCtx.state === 'suspended') audioCtx.resume();
    } catch (e) { audioCtx = null; }
  }

  function watchSilence(stream, silenceMs, noSpeechMs, onStop) {
    var w = { active: false, spoke: false, stop: function () {} };
    if (!audioCtx || audioCtx.state !== 'running') return w;
    var source, analyser;
    try {
      source = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
    } catch (e) { return w; }
    var buf = new Float32Array(analyser.fftSize), floor = 0.008;
    var started = Date.now(), lastVoice = started, iv = null;
    w.active = true;
    w.stop = function () { clearInterval(iv); try { source.disconnect(); } catch (e) { /* ya desconectado */ } };
    iv = setInterval(function () {
      analyser.getFloatTimeDomainData(buf);
      var sum = 0;
      for (var i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      var rms = Math.sqrt(sum / buf.length), now = Date.now();
      // Umbral relativo al ruido de fondo, para que funcione en salón o en casa.
      if (rms > Math.max(0.015, floor * 3)) { w.spoke = true; lastVoice = now; }
      else floor = floor * 0.95 + rms * 0.05;
      if (w.spoke && silenceMs && now - lastVoice > silenceMs) { w.stop(); onStop(); }
      else if (!w.spoke && noSpeechMs && now - started > noSpeechMs) { w.stop(); onStop(); }
    }, 100);
    return w;
  }

  /* ---------- Controlador de dictado ----------
     opts: { textarea, onState(state), onStatus(text), context, silenceMs }
     estados: idle | listening | transcribing */
  function create(opts) {
    var ctrl = { state: 'idle', listened: 0, added: false };
    var rec = null, recorder = null, timer = null, silenceTimer = null, startedAt = 0, fallback = false;
    var starting = false, watcher = null;
    var silenceMs = typeof opts.silenceMs === 'number' ? opts.silenceMs : SILENCE_MS;
    var noSpeechMs = silenceMs ? NO_SPEECH_MS : 0;

    function setState(state) {
      starting = false;
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
        var text = buildTranscript(e.results);
        if (text) { heard = true; write(base, text); }
        // Sin resultados nuevos durante un rato = la persona dejó de hablar.
        clearTimeout(silenceTimer);
        if (silenceMs) silenceTimer = setTimeout(ctrl.stop, silenceMs + 500);
      };
      rec.onerror = function (e) {
        if (e.error === 'network' || e.error === 'service-not-allowed' || e.error === 'language-not-supported') fallback = true;
        else if (e.error === 'not-allowed') status('Permite el acceso al micrófono en tu navegador.');
        else if (e.error === 'no-speech') status('No escuché nada. Acércate al micrófono e intenta de nuevo.');
      };
      rec.onend = function () {
        clearTimeout(timer); clearTimeout(silenceTimer);
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
          recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: BITRATE } : { audioBitsPerSecond: BITRATE });
          recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
          recorder.onstop = function () {
            clearTimeout(timer);
            var w = watcher; watcher = null; w.stop();
            stream.getTracks().forEach(function (t) { t.stop(); });
            var type = recorder.mimeType || mime || 'audio/webm';
            recorder = null;
            // Si se midió el volumen y nunca hubo voz, no se manda: Whisper inventaría texto.
            if (w.active && !w.spoke) { setState('idle'); status('No escuché nada. Acércate al micrófono e intenta de nuevo.'); return; }
            upload(new Blob(chunks, { type: type }), type);
          };
          watcher = watchSilence(stream, silenceMs, noSpeechMs, function () { ctrl.stop(); });
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
      form.append('context', opts.context || 'chat');
      App.api('/api/transcribe', form)
        .then(function (data) {
          if (data.text) { write(baseText(), data.text); ctrl.added = true; }
          else status('No se entendió el audio. Intenta de nuevo.');
        })
        .catch(function (err) { status(err.message); })
        .then(function () { setState('idle'); });
    }

    ctrl.start = function () {
      if (ctrl.state !== 'idle' || starting) return;
      starting = true;
      App.tts.stop();
      primeAudio();   // dentro del toque del usuario
      if (!SR || (IS_MOBILE && settings.pref !== 'local')) { startRecorder(); return; }
      if (settings.pref !== 'local') { startSpeech(false); return; }
      var ready = settings.local === 'unknown' ? checkLocal() : Promise.resolve();
      ready.then(function () {
        if (settings.local === 'available') startSpeech(true);
        else if (IS_MOBILE) startRecorder();
        else startSpeech(false);
      });
    };
    ctrl.stop = function () {
      clearTimeout(timer); clearTimeout(silenceTimer);
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
