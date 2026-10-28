import io
import json
import logging
from functools import wraps

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import grammar, interview, llm, progress
from .common import SERVICE_ERROR, score_label, score_tone
from .models import PracticeSession

logger = logging.getLogger("chatbot")

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MIN_AUDIO_BYTES = 3000
MAX_CV_BYTES = 5 * 1024 * 1024


# --- Páginas públicas y cuentas --------------------------------------------

def home(request):
    return render(request, "index.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("interview")
    error = None
    if request.method == "POST":
        user = auth.authenticate(request, username=request.POST.get("username", "").strip(),
                                 password=request.POST.get("password", ""))
        if user is not None:
            auth.login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
                return redirect(next_url)
            return redirect("interview")
        error = "Usuario o contraseña incorrectos."
    return render(request, "login.html", {"error_message": error, "username": request.POST.get("username", "")})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("interview")
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")
        if not username:
            error = "Escribe un nombre de usuario."
        elif User.objects.filter(username__iexact=username).exists():
            error = "Ese nombre de usuario ya existe."
        elif password1 != password2:
            error = "Las contraseñas no coinciden."
        else:
            try:
                validate_password(password1, User(username=username, email=email))
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                user = User.objects.create_user(username, email, password1)
                auth.login(request, user)
                return redirect("interview")
    return render(request, "register.html", {"error_message": error, "username": request.POST.get("username", ""),
                                             "email": request.POST.get("email", "")})


@require_POST
def logout_view(request):
    auth.logout(request)
    return redirect("login")


def legacy_chatbot(request):
    return redirect("interview")


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
    return render(request, "report.html", data)


@login_required
def grammar_page(request):
    return render(request, "grammar.html")


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
        cache.add(key, 0, ttl)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, ttl)
            count = 1
        if count > limit:
            return message
    return None


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


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
