from collections import Counter
import io
import json
import logging
import math
from ipaddress import ip_address, ip_network
from functools import wraps

from django.conf import settings
from django.contrib import auth
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import grammar, interview, limits, llm, practice, progress
from .common import MAX_INPUT_CHARS, SERVICE_ERROR, score_label, score_tone
from .models import PracticeSession

logger = logging.getLogger("chatbot")

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MIN_AUDIO_BYTES = 3000
MAX_CV_BYTES = 5 * 1024 * 1024


# --- Páginas públicas y cuentas --------------------------------------------

def home(request):
    return render(request, "index.html")


LOGIN_FAILS = 5            # intentos fallidos permitidos
LOGIN_LOCK_SECONDS = 15 * 60
SIGNUPS_PER_HOUR = 5


def client_ip(request):
    """Solo acepta cabeceras reenviadas desde proxies configurados como fiables."""
    try:
        peer = ip_address(request.META.get('REMOTE_ADDR', ''))
        trusted = [ip_network(cidr) for cidr in settings.TRUSTED_PROXY_CIDRS]
        if not any(peer in network for network in trusted):
            return str(peer)
        chain = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')
        for value in reversed(chain):
            if not any(peer in network for network in trusted):
                break
            peer = ip_address(value.strip())
        return str(peer)
    except ValueError:
        return request.META.get('REMOTE_ADDR', 'unknown')


def _hit(key, ttl):
    return limits.hit(key, ttl)


def _login_keys(request, username):
    resolved = _login_name(username)
    user_id = User.objects.filter(username__iexact=resolved).values_list('pk', flat=True).first()
    identity = f'id:{user_id}' if user_id else username.casefold()
    return [f"lf:ip:{client_ip(request)}", f"lf:user:{identity}"]


def _login_name(value):
    """Permite entrar con el usuario o con el correo de la cuenta."""
    if "@" not in value:
        return value
    for user in User.objects.filter(email__iexact=value).order_by("id"):
        if user.has_usable_password():
            return user.username
    return value


def login_view(request):
    if request.user.is_authenticated:
        return redirect("interview")
    error = None
    username = request.POST.get("username", "").strip()[:150]
    if request.method == "POST":
        keys = _login_keys(request, username)
        if any(limits.count(k) >= LOGIN_FAILS for k in keys):
            error = "Demasiados intentos. Espera 15 minutos e inténtalo de nuevo."
        else:
            user = auth.authenticate(request, username=_login_name(username), password=request.POST.get("password", ""))
            if user is not None:
                limits.clear(keys[1])
                auth.login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                next_url = request.POST.get("next") or request.GET.get("next")
                if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()},
                                                                require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect("interview")
            for k in keys:
                _hit(k, LOGIN_LOCK_SECONDS)
            error = "Usuario o contraseña incorrectos."
    return render(request, "login.html", {"error_message": error, "username": username,
                                          "google_enabled": settings.GOOGLE_LOGIN_ENABLED})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("interview")
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")
        if limits.count(f"su:{client_ip(request)}") >= SIGNUPS_PER_HOUR:
            error = "Se crearon muchas cuentas desde esta red. Inténtalo más tarde."
        elif not username:
            error = "Escribe un nombre de usuario."
        elif len(username) > 150 or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
            error = "El usuario solo puede tener letras, números, punto, guion y guion bajo."
        elif User.objects.filter(username__iexact=username).exists():
            error = "Ese nombre de usuario ya existe."
        elif not _valid_email(email):
            error = "Escribe un correo válido; lo usamos para que puedas recuperar tu contraseña."
        elif User.objects.filter(email__iexact=email).exists():
            error = "Ese correo ya tiene una cuenta. Inicia sesión, entra con Google o recupera tu contraseña."
        elif password1 != password2:
            error = "Las contraseñas no coinciden."
        else:
            try:
                validate_password(password1, User(username=username, email=email))
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                user = User.objects.create_user(username, email, password1)
                _hit(f"su:{client_ip(request)}", 3600)
                auth.login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                next_url = request.POST.get("next") or request.GET.get("next")
                if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()},
                                                                require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect("interview")
    return render(request, "register.html", {"error_message": error, "username": request.POST.get("username", ""),
                                             "email": request.POST.get("email", ""),
                                             "google_enabled": settings.GOOGLE_LOGIN_ENABLED})


def _valid_email(value):
    try:
        validate_email(value)
    except ValidationError:
        return False
    return True


@login_required
@require_POST
def change_email(request):
    """Agrega o cambia el correo de una cuenta con contraseña (pide la contraseña actual)."""
    user = request.user
    email = request.POST.get("email", "").strip()
    if not user.has_usable_password():
        messages = "Tu cuenta entra con Google; el correo es el de Google."
    elif not user.check_password(request.POST.get("password", "")):
        messages = "La contraseña no es correcta."
    elif not _valid_email(email):
        messages = "Escribe un correo válido."
    elif User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        messages = "Ese correo ya lo usa otra cuenta."
    else:
        user.email = email
        user.save(update_fields=["email"])
        messages = "Listo: guardamos tu correo."
    request.session["account_notice"] = messages
    return redirect(request.POST.get("back") if url_has_allowed_host_and_scheme(
        request.POST.get("back", ""), {request.get_host()}) else "interview")


# --- Recuperar contraseña ---------------------------------------------------

RESETS_PER_HOUR = 5


class ResetRequestView(auth_views.PasswordResetView):
    template_name = "auth/reset_request.html"
    email_template_name = "auth/reset_email.txt"
    html_email_template_name = "auth/reset_email.html"
    subject_template_name = "auth/reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        key = f"pr:{client_ip(self.request)}"
        if limits.count(key) >= RESETS_PER_HOUR:
            form.add_error(None, "Pediste muchos enlaces. Espera una hora e inténtalo de nuevo.")
            return self.form_invalid(form)
        _hit(key, 3600)
        try:
            return super().form_valid(form)
        except Exception:  # el servicio de correo falló
            logger.exception("No se pudo enviar el correo de recuperación")
            form.add_error(None, "No pudimos enviar el correo en este momento. Inténtalo en unos minutos.")
            return self.form_invalid(form)


class ResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "auth/reset_sent.html"


class ResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "auth/reset_confirm.html"
    post_reset_login = True
    post_reset_login_backend = "django.contrib.auth.backends.ModelBackend"
    success_url = reverse_lazy("interview")


@login_required
@require_POST
def delete_account(request):
    """Borra la cuenta y todas sus sesiones, mensajes y vínculos con Google."""
    if request.POST.get("confirm", "").strip().upper() != "ELIMINAR":
        return redirect("progress")
    user = request.user
    auth.logout(request)
    user.delete()
    return redirect("home")


@require_POST
def logout_view(request):
    auth.logout(request)
    return redirect("login")


# --- Páginas de la aplicación ----------------------------------------------

def _active_interview(user):
    return PracticeSession.objects.filter(user=user, mode=PracticeSession.INTERVIEW, finished=False,
                                          questions_asked__gt=0).order_by("-updated_at").first()


@login_required
def interview_page(request):
    session = None if request.GET.get("nueva") else _active_interview(request.user)
    return render(request, "interview.html", {
        "state": interview.state(session),
        "roles": interview.ROLE_SUGGESTIONS,
        "levels": PracticeSession.LEVELS,
    })


@login_required
def report_page(request, session_id):
    session = get_object_or_404(PracticeSession, id=session_id, user=request.user, mode=PracticeSession.INTERVIEW)
    if not session.finished:
        return redirect("interview")
    data = interview.report(session)
    for row in data["rows"]:
        row["tone"] = score_tone(row["score"])
    data["label"] = (data["summary"] or {}).get("label") or score_label(session.score)
    data["degrees"] = round((session.score or 0) * 3.6)
    data["lowest_json"] = data["lowest"]
    # Criterios como barras de 1 a 5; el más bajo se marca para que sea lo único en magenta
    names = {"claridad": "Claridad", "estructura": "Estructura", "seguridad": "Confianza al hablar"}
    helps = {"claridad": "Se entiende a la primera", "estructura": "Situación, acción y resultado",
             "seguridad": "Suenas convencido, sin titubeos"}
    data["criteria"] = [{"key": k, "label": names[k], "help": helps[k], "value": v, "pct": round((v or 0) * 20),
                         "weak": k == data["weakest"] and v is not None and v < 4}
                        for k, v in data["metrics"].items()]
    counts = Counter(f.lower() for r in data["rows"] for f in r["fillers"])
    data["filler_list"] = counts.most_common(4)
    total = data["total_seconds"]
    data["time_text"] = None if not total else ("menos de 1 min" if total < 60 else f"{round(total / 60)} min")
    for row in data["rows"]:
        row["pct"] = round(row["score"] or 0)
    # Las 2 preguntas que se practicarán (las más bajas) y la que se abre primero (la más baja)
    ranked = sorted((r for r in data["rows"] if r["score"] is not None), key=lambda r: r["score"])
    for r in ranked[:len(data["lowest"])]:
        r["practice"] = True
    if ranked:
        ranked[0]["open"] = True
    elif data["rows"]:
        data["rows"][0]["open"] = True
    data["practice_titles"] = [r["question"] for r in ranked[:len(data["lowest"])]]
    previous = (PracticeSession.objects
                .filter(user=request.user, mode=PracticeSession.INTERVIEW, finished=True,
                        score__isnull=False, created_at__lt=session.created_at)
                .order_by("-created_at").first())
    data["previous_score"] = round(previous.score) if previous else None
    return render(request, "report.html", data)


@login_required
def grammar_page(request):
    return render(request, "grammar.html")


@login_required
def practice_page(request, kind, message_id):
    if kind not in practice.EXERCISES:
        raise Http404
    try:
        message = practice.correction_message(request.user, message_id)
    except Exception:
        raise Http404
    data = message.data or {}
    text = data.get("original") or ""
    total_words = len(practice.words(text))
    filler_map = practice.filler_counts(data)
    filler_count = sum(filler_map.values())
    payload = {
        "kind": kind, "message_id": message.id, "original": text, "source": data.get("source", "text"),
        "fillers": sorted(filler_map.keys(), key=len, reverse=True),
        "before": {"count": filler_count, "words": total_words, "rate": practice.per_100(filler_count, total_words),
                   "map": filler_map},
        "summary_limit": practice.SUMMARY_LIMIT,
    }
    if kind == "ortografia":
        payload["words"] = [practice.word_json(w) for w in practice.due_words(request.user, data)]
        payload["schedule"] = practice.schedule(request.user)
    return render(request, "practice.html", {"kind": kind, "exercise": practice.EXERCISES[kind],
                                             "evidence": practice.EVIDENCE, "payload": payload,
                                             "plan": data.get("plan") or []})


@login_required
def progress_page(request):
    return render(request, "progress.html", progress.build(request.user))


# --- API -------------------------------------------------------------------

def api_view(view):
    """Pide sesión iniciada, convierte errores conocidos en JSON y cuida la cuota gratuita."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Tu sesión expiró. Vuelve a iniciar sesión."}, status=401)
        if request.method != "POST":
            return JsonResponse({"error": "Método no permitido."}, status=405)
        limit_message = rate_limited(request.user)
        if limit_message:
            return JsonResponse({"error": limit_message}, status=429)
        try:
            return view(request, *args, **kwargs)
        except InvalidPayload as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        except (interview.InterviewError, grammar.GrammarError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except llm.LLMError as exc:
            logger.error("Sin respuesta de los modelos: %s", exc)
            return JsonResponse({"error": SERVICE_ERROR}, status=503)
    return wrapper


def rate_limited(user):
    now = timezone.now()
    checks = [(f"rl:{user.id}:m:{now:%Y%m%d%H%M}", settings.MESSAGES_PER_MINUTE, 60,
               "Vas muy rápido. Espera un minuto y vuelve a intentar."),
              (f"rl:{user.id}:d:{now:%Y%m%d}", settings.MESSAGES_PER_DAY, 86400,
               "Llegaste al límite de hoy. Vuelve mañana para seguir practicando.")]
    for key, limit, ttl, message in checks:
        count = limits.hit(key, ttl)
        if count > limit:
            return message
    return None


class InvalidPayload(Exception):
    pass


def _body(request):
    try:
        if len(request.body) > 64 * 1024:
            raise InvalidPayload('El JSON supera el tamaño permitido.')
        def reject_constant(value):
            raise ValueError(value)
        body = json.loads(request.body.decode('utf-8') or '{}', parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise InvalidPayload('Envía un objeto JSON válido.')
    if not isinstance(body, dict):
        raise InvalidPayload('Envía un objeto JSON válido.')
    for key in ('text', 'source', 'kind'):
        if key in body and not isinstance(body[key], str):
            raise InvalidPayload(f'El campo {key} debe ser texto.')
    if len(body.get('text', '')) > MAX_INPUT_CHARS:
        raise InvalidPayload(f'El texto supera los {MAX_INPUT_CHARS} caracteres permitidos.')
    for key in ('id', 'message_id'):
        if key in body and (type(body[key]) is not int or body[key] < 1):
            raise InvalidPayload(f'El campo {key} debe ser un entero positivo.')
    if 'correct' in body and type(body['correct']) is not bool:
        raise InvalidPayload('El campo correct debe ser verdadero o falso.')
    duration = body.get('duration')
    if duration is not None:
        try:
            valid_duration = type(duration) in (int, float) and math.isfinite(duration)
        except OverflowError:
            valid_duration = False
        if not valid_duration:
            raise InvalidPayload('La duración debe ser un número finito.')
    return body


def _user_interview(request):
    session = _active_interview(request.user)
    if session is None:
        raise interview.InterviewError("No hay una entrevista en curso. Empieza una nueva.")
    return session


def extract_cv(upload):
    if upload is None:
        return ""
    if upload.size > MAX_CV_BYTES:
        raise interview.InterviewError("El CV pesa más de 5 MB.")
    name = upload.name.lower()
    data = upload.read()
    if name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")
    if not name.endswith(".pdf"):
        raise interview.InterviewError("Sube tu CV en PDF o en TXT.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:4]).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo leer el CV: %s", exc)
        raise interview.InterviewError("No pude leer ese PDF. Prueba con otro archivo o pega tu experiencia en la vacante.")


@api_view
def api_interview_start(request):
    post = request.POST
    session = interview.start(
        request.user, role=post.get("role", ""), level=post.get("level", "junior"),
        interview_type=post.get("interview_type", "mixta"), total=post.get("total", 8),
        answer_mode=post.get("answer_mode", "voice"), job_description=post.get("job_description", ""),
        cv_text=extract_cv(request.FILES.get("cv")))
    return JsonResponse(interview.state(session))


@api_view
def api_interview_answer(request):
    body = _body(request)
    session = _user_interview(request)
    result = interview.answer(session, body.get("text", ""), source=body.get("source", "text"),
                              duration=body.get("duration"))
    if result.get("action") == "finish":
        interview.finish(session)
        result["navigate"] = f"/reporte/{session.id}"
    session.refresh_from_db()
    return JsonResponse({**result, "state": interview.state(session)})


@api_view
def api_interview_next(request):
    session = _user_interview(request)
    result = interview.next_question(session)
    if result["finished"]:
        return JsonResponse({"navigate": f"/reporte/{session.id}"})
    return JsonResponse({"state": interview.state(session)})


@api_view
def api_interview_other(request):
    session = _user_interview(request)
    interview.other_question(session)
    return JsonResponse({"state": interview.state(session)})


@api_view
def api_interview_finish(request):
    session = _user_interview(request)
    interview.finish(session)
    return JsonResponse({"navigate": f"/reporte/{session.id}"})


@api_view
def api_interview_practice(request, session_id):
    source = PracticeSession.objects.filter(id=session_id, user=request.user, mode=PracticeSession.INTERVIEW).first()
    if source is None:
        raise Http404
    questions = interview.report(source)["lowest"]
    if not questions:
        raise interview.InterviewError("Esa entrevista no tiene preguntas respondidas.")
    interview.practice_lowest(request.user, source, questions)
    return JsonResponse({"navigate": "/entrevista"})


@api_view
def api_grammar_check(request):
    body = _body(request)
    return JsonResponse(grammar.check(request.user, body.get("text", ""), source=body.get("source", "text")))


@api_view
def api_practice_generate(request):
    body = _body(request)
    kind = body.get("kind")
    if kind not in ("gramatica", "puntuacion", "claridad"):
        return JsonResponse({"error": "Ejercicio no válido."}, status=400)
    try:
        message = practice.correction_message(request.user, int(body.get("message_id") or 0))
    except Exception:
        return JsonResponse({"error": "No encontramos esa revisión."}, status=404)
    return JsonResponse(practice.generate(message, kind))


@api_view
def api_count_fillers(request):
    text = (_body(request).get("text") or "").strip()
    if not text:
        return JsonResponse({"fillers": [], "count": 0, "words": 0})
    fillers = practice.detect_fillers(text)
    return JsonResponse({"fillers": fillers, "count": len(fillers), "words": len(practice.words(text))})


@login_required
@require_POST
def api_spelling_review(request):
    """Marca un repaso de ortografía. No cuenta contra el límite de mensajes: no usa la API."""
    try:
        body = _body(request)
    except InvalidPayload as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    try:
        word = practice.review_word(request.user, int(body.get("id") or 0), bool(body.get("correct")))
    except Exception:
        return JsonResponse({"error": "No encontramos esa palabra."}, status=404)
    return JsonResponse({"word": practice.word_json(word), "learned": word.learned,
                         "due": word.due.isoformat(), "schedule": practice.schedule(request.user)})


@api_view
def api_grammar_exercise(request):
    return JsonResponse(grammar.exercise())


@api_view
def api_transcribe(request):
    audio = request.FILES.get("audio")
    if audio is None:
        return JsonResponse({"error": "No se recibió audio."}, status=400)
    if audio.size > MAX_AUDIO_BYTES:
        return JsonResponse({"error": "La grabación es demasiado larga."}, status=400)
    if audio.size < MIN_AUDIO_BYTES:
        return JsonResponse({"text": ""})  # demasiado corta: Whisper tiende a inventar texto
    mime = (request.POST.get("mime") or audio.content_type or "audio/webm").split(";")[0]
    ext = {"audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(mime, "webm")
    session = _active_interview(request.user)
    context = "Conversación en español de México. " + (
        f"Entrevista de trabajo para {session.role}." if session else "Práctica de expresión oral.")
    try:
        text = llm.transcribe(audio.read(), f"audio.{ext}", mime, prompt=context)
    except Exception as exc:  # noqa: BLE001
        logger.error("Falló la transcripción: %s", exc)
        return JsonResponse({"error": "No pude transcribir el audio. Intenta de nuevo o escribe tu respuesta."},
                            status=502)
    return JsonResponse({"text": text})


def health(request):
    """Ruta ligera para el servicio que mantiene despierta la página (no toca la base)."""
    from django.http import HttpResponse
    return HttpResponse("ok", content_type="text/plain")
