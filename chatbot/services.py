"""
Lógica de la conversación: sesiones, memoria, comandos, llamadas al modelo
de lenguaje, comparación de textos corregidos y estadísticas de la sesión.
"""
import difflib
import logging
import random
import re
from collections import Counter

from django.conf import settings

from . import intents, llm, prompts
from .models import Message, PracticeSession

logger = logging.getLogger("chatbot")

HISTORY_LIMIT = 14       # mensajes que se mandan al modelo como memoria
SUMMARY_HISTORY_LIMIT = 60
MAX_INPUT_CHARS = 4000
VOICE_PREFIX = "[Dictado por voz] "

MODE_NAMES = {PracticeSession.INTERVIEW: "entrevista", PracticeSession.GRAMMAR: "gramática"}

INTRO = {
    PracticeSession.INTERVIEW: "Vamos a practicar una entrevista de trabajo. **¿Para qué puesto te quieres preparar?**",
    PracticeSession.GRAMMAR: "Escríbeme o díctame un texto y te digo qué corregir y por qué. "
                             "También puedes pedirme un ejercicio.",
}

HELP = {
    PracticeSession.INTERVIEW: (
        "Te hago preguntas como en una entrevista real y te doy retroalimentación de cada respuesta. "
        "Puedes responder escribiendo o con el micrófono, pedirme **una pista**, **un ejemplo** u **otra pregunta**, "
        "y al final pedir tu **calificación**."
    ),
    PracticeSession.GRAMMAR: (
        "Escribe o dicta cualquier texto y te muestro los errores tachados, la versión corregida y por qué. "
        "También puedes pedirme **un ejercicio** o que te **explique** una regla."
    ),
}

FAREWELLS = ["¡Hasta luego! Tu progreso queda guardado; cuando vuelvas seguimos.",
             "¡Nos vemos! Aquí estaré cuando quieras practicar otra vez."]
THANKS = ["¡Con gusto! ¿Seguimos?", "¡Para eso estoy! ¿Continuamos?"]

SERVICE_ERROR = ("No pude conectarme con el servicio de inteligencia artificial. "
                 "Intenta de nuevo en unos minutos.")


# --- Sesiones --------------------------------------------------------------

def start_session(user, mode):
    session = PracticeSession.objects.create(
        user=user, mode=mode, total_questions=settings.INTERVIEW_QUESTIONS)
    Message.objects.create(session=session, sender=Message.BOT, kind=Message.TEXT, text=INTRO[mode])
    return session


def get_active_session(request):
    session_id = request.session.get("practice_session_id")
    qs = PracticeSession.objects.filter(user=request.user)
    session = qs.filter(id=session_id).first() if session_id else None
    return session or qs.first()


def set_active_session(request, session):
    request.session["practice_session_id"] = session.id


# --- Serialización ---------------------------------------------------------

def serialize_message(message):
    from django.utils import timezone

    return {
        "id": message.id,
        "sender": message.sender,
        "kind": message.kind,
        "text": message.text,
        "data": message.data,
        "time": timezone.localtime(message.created_at).strftime("%H:%M"),
    }


def serialize_session(session):
    if session is None:
        return None
    return {
        "id": session.id,
        "mode": session.mode,
        "mode_name": MODE_NAMES[session.mode],
        "role": session.role,
        "questions_asked": session.questions_asked,
        "total_questions": session.total_questions,
        "finished": session.finished,
        "score": session.score,
    }


def message_to_plain(message):
    """Texto que el modelo ve como memoria de cada mensaje."""
    data = message.data or {}
    if message.sender == Message.USER:
        prefix = VOICE_PREFIX if data.get("source") == "voice" else ""
        return prefix + message.text
    parts = [message.text] if message.text else []
    if message.kind == Message.FEEDBACK and data.get("feedback"):
        fb = data["feedback"]
        parts.append("Bien: " + "; ".join(fb.get("good", [])))
        parts.append("Mejorar: " + "; ".join(fb.get("improve", [])))
    if message.kind == Message.CORRECTION:
        parts.append("Texto corregido: " + (data.get("corrected") or ""))
        errs = [f"{e['wrong']} → {e['right']}" for e in data.get("errors", [])]
        if errs:
            parts.append("Errores: " + "; ".join(errs))
    if message.kind == Message.SUMMARY:
        parts.append(f"Calificación final: {data.get('score')}")
    if data.get("next_question"):
        parts.append("Pregunta: " + data["next_question"])
    return "\n".join(parts)


def history_for_llm(session, limit=HISTORY_LIMIT):
    recent = list(session.messages.exclude(kind=Message.NOTICE).order_by("-created_at", "-id")[:limit])
    recent.reverse()
    return [{"role": "user" if m.sender == Message.USER else "assistant", "content": message_to_plain(m)}
            for m in recent]


# --- Limpieza de lo que devuelve el modelo ----------------------------------

def _str(value, limit=2000):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _str_list(value, limit=6):
    if not isinstance(value, list):
        return []
    return [s.strip()[:400] for s in value if isinstance(s, str) and s.strip()][:limit]


def _score(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, round(number, 1)))


def clean_interview(data):
    feedback = data.get("feedback")
    if isinstance(feedback, dict):
        feedback = {"good": _str_list(feedback.get("good"), 3), "improve": _str_list(feedback.get("improve"), 3),
                    "example": _str(feedback.get("example"), 600)}
        if not (feedback["good"] or feedback["improve"]):
            feedback = None
    else:
        feedback = None
    scores = data.get("scores")
    if isinstance(scores, dict) and feedback:
        scores = {k: _score(scores.get(k), 1, 5) for k in ("claridad", "estructura", "seguridad")}
        scores = {k: v for k, v in scores.items() if v is not None} or None
    else:
        scores = None
    return {
        "role": _str(data.get("role"), 200),
        "message": _str(data.get("message")) or "",
        "feedback": feedback,
        "scores": scores,
        "fillers": [f.lower() for f in _str_list(data.get("fillers"), 30)],
        "next_question": _str(data.get("next_question"), 600),
    }


def clean_grammar(data):
    errors = []
    for err in data.get("errors") or []:
        if isinstance(err, dict) and _str(err.get("wrong"), 300):
            errors.append({
                "type": _str(err.get("type"), 40) or "Gramática",
                "wrong": _str(err.get("wrong"), 300),
                "right": _str(err.get("right"), 300) or "",
                "explanation": _str(err.get("explanation"), 500) or "",
            })
    scores = data.get("scores")
    if isinstance(scores, dict):
        scores = {k: _score(scores.get(k), 0, 10) for k in ("ortografia", "gramatica", "claridad")}
        if all(v is None for v in scores.values()):
            scores = None
    else:
        scores = None
    return {
        "is_text": bool(data.get("is_text")),
        "message": _str(data.get("message")) or "",
        "corrected": _str(data.get("corrected"), MAX_INPUT_CHARS),
        "errors": errors[:15],
        "fillers": [f.lower() for f in _str_list(data.get("fillers"), 30)],
        "scores": scores,
        "tip": _str(data.get("tip"), 400),
    }


def clean_summary(data):
    return {
        "score": _score(data.get("score"), 0, 10),
        "summary": _str(data.get("summary"), 1000) or "",
        "strengths": _str_list(data.get("strengths"), 3),
        "improve": _str_list(data.get("improve"), 3),
    }


# --- Comparación de texto original vs corregido ----------------------------

TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
NO_SPACE_BEFORE = set(".,;:!?)]}…%")
NO_SPACE_AFTER = set("¿¡([{")


def _join(tokens):
    out = ""
    for tok in tokens:
        if out and tok[0] not in NO_SPACE_BEFORE and out[-1] not in NO_SPACE_AFTER:
            out += " "
        out += tok
    return out


def diff_segments(original, corrected):
    """
    Divide el texto en tramos iguales, borrados e insertados para dibujar la
    corrección con tachado. Cada tramo indica si lleva espacio antes.
    """
    a, b = TOKEN_RE.findall(original), TOKEN_RE.findall(corrected)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    segments = []

    def add(kind, tokens):
        if not tokens:
            return
        text = _join(tokens)
        prev = segments[-1]["text"] if segments else ""
        space = bool(segments) and text[0] not in NO_SPACE_BEFORE and prev[-1:] not in NO_SPACE_AFTER
        segments.append({"type": kind, "text": text, "space": space})

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            add("eq", a[i1:i2])
        else:
            add("del", a[i1:i2])
            add("ins", b[j1:j2])
    return segments


# --- Manejo de mensajes ----------------------------------------------------

def _bot(session, text, kind=Message.TEXT, data=None):
    return Message.objects.create(session=session, sender=Message.BOT, kind=kind, text=text, data=data or {})


def _last_question(session):
    for msg in session.messages.filter(sender=Message.BOT).order_by("-created_at", "-id"):
        if msg.data.get("next_question"):
            return msg.data["next_question"]
    return None


def handle_message(session, text, source="text", action=None):
    """
    Procesa un mensaje del usuario. Devuelve un dict con:
      session  -> la sesión activa (puede ser una nueva)
      messages -> mensajes nuevos para dibujar
      reload   -> True si cambió la sesión y hay que redibujar todo
    """
    text = (text or "").strip()[:MAX_INPUT_CHARS]
    user_msg = Message.objects.create(session=session, sender=Message.USER, text=text,
                                      data={"source": "voice" if source == "voice" else "text"})
    new_messages = [user_msg]

    if action == "finish":
        new_messages += finish_session(session)
        return {"session": session, "messages": new_messages, "reload": False}

    intent = intents.classify(text) if source != "voice" or len(text.split()) <= 4 else None
    if intent:
        result = handle_intent(session, intent)
        if result.get("reload"):
            return result
        new_messages += result["messages"]
        return {"session": session, "messages": new_messages, "reload": False}

    if session.finished:
        new_messages.append(_bot(session, "Esta sesión ya terminó. Empieza una **nueva sesión** o cambia de modo "
                                          "para seguir practicando.", Message.NOTICE))
        return {"session": session, "messages": new_messages, "reload": False}

    try:
        if session.mode == PracticeSession.INTERVIEW:
            new_messages += interview_turn(session)
        else:
            new_messages += grammar_turn(session, text)
    except llm.LLMError as exc:
        logger.error("Sin respuesta de los modelos: %s", exc)
        new_messages.append(_bot(session, SERVICE_ERROR, Message.NOTICE, {"error": True}))
    return {"session": session, "messages": new_messages, "reload": False}


def handle_intent(session, intent):
    """Responde comandos detectados por el modelo propio, sin gastar llamadas a la API."""
    meta = {"source": "intent", "intent": intent.tag, "confidence": round(intent.confidence, 2)}
    tag = intent.tag
    targets = {"cambiar_entrevista": PracticeSession.INTERVIEW, "cambiar_gramatica": PracticeSession.GRAMMAR}

    if tag in targets:
        if targets[tag] == session.mode:
            return {"messages": [_bot(session, f"Ya estás en modo {MODE_NAMES[session.mode]}.", data=meta)]}
        return {"session": start_session(session.user, targets[tag]), "messages": [], "reload": True}
    if tag == "reiniciar":
        return {"session": start_session(session.user, session.mode), "messages": [], "reload": True}
    if tag == "terminar":
        return {"messages": finish_session(session)}
    if tag == "ayuda":
        return {"messages": [_bot(session, HELP[session.mode], data=meta)]}
    if tag == "despedida":
        return {"messages": [_bot(session, random.choice(FAREWELLS), data=meta)]}
    if tag == "agradecimiento":
        return {"messages": [_bot(session, random.choice(THANKS), data=meta)]}
    # saludo
    if session.mode == PracticeSession.INTERVIEW and session.role and not session.finished:
        question = _last_question(session)
        text = "¡Hola! Seguimos con la entrevista." + (f" La pregunta era: **{question}**" if question else "")
    elif session.mode == PracticeSession.INTERVIEW:
        text = "¡Hola! **¿Para qué puesto practicamos hoy?**"
    else:
        text = "¡Hola! Escríbeme o díctame un texto y lo revisamos juntos."
    return {"messages": [_bot(session, text, data=meta)]}


LIST_RE = re.compile(r"(^|\n)\s*(\d+[.)]|[-*•])\s+")


def _off_role(data):
    """True si el modelo respondió como asistente (texto largo o con listas) en vez de entrevistar."""
    if data["feedback"] or data["next_question"]:
        return False
    message = data["message"]
    return len(message) > 320 or bool(LIST_RE.search(message))


def interview_turn(session):
    asked, total = session.questions_asked, session.total_questions
    if not session.role or asked == 0:
        instruction = prompts.INTERVIEW_AWAITING_ROLE
    elif asked >= total:
        instruction = prompts.INTERVIEW_LAST_ANSWER.format(current=asked, total=total)
    else:
        instruction = prompts.INTERVIEW_ANSWERING.format(current=asked, following=asked + 1)
    current = _last_question(session) if session.role and asked else None
    system = prompts.INTERVIEW_SYSTEM.format(role=session.role or "todavía no definido",
                                             asked=asked, total=total, instruction=instruction,
                                             current_question=current or "ninguna todavía")
    history = history_for_llm(session)
    raw, model = llm.complete_json(system, history, temperature=0.5)
    data = clean_interview(raw)
    if current and _off_role(data):
        # El modelo dejó de entrevistar (dio una guía larga en vez de evaluar): se le pide otra vez.
        logger.info("Respuesta fuera de papel en la entrevista %s; reintentando", session.id)
        retry = history + [{"role": "user", "content": prompts.INTERVIEW_REMINDER}]
        raw, model = llm.complete_json(system, retry, temperature=0.3)
        data = clean_interview(raw)
    data["model"] = model

    if not session.role and data["role"]:
        session.role = data["role"]
    last_phase = asked >= total
    if data["next_question"] and not last_phase:
        session.questions_asked += 1
        data["question_number"] = session.questions_asked
    else:
        data["next_question"] = None
    session.save()

    kind = Message.FEEDBACK if data["feedback"] else Message.TEXT
    messages = [_bot(session, data.pop("message"), kind, data)]
    if last_phase and data["feedback"]:
        messages += finish_session(session)
    return messages


def grammar_turn(session, text):
    raw, model = llm.complete_json(prompts.GRAMMAR_SYSTEM, history_for_llm(session), temperature=0.2)
    data = clean_grammar(raw)
    data["model"] = model
    if data["is_text"] and data["corrected"]:
        data["original"] = text
        data["segments"] = diff_segments(text, data["corrected"])
        kind = Message.CORRECTION
    else:
        kind = Message.TEXT
    return [_bot(session, data.pop("message"), kind, data)]


def finish_session(session):
    if not session.messages.filter(sender=Message.USER).exclude(text="").exists():
        return [_bot(session, "Todavía no hay nada que calificar. ¡Empecemos!", Message.NOTICE)]
    role_part = f" para el puesto de {session.role}" if session.role else ""
    system = prompts.SUMMARY_SYSTEM.format(persona=prompts.PERSONAS[session.mode],
                                           mode_name=MODE_NAMES[session.mode], role_part=role_part)
    try:
        raw, model = llm.complete_json(system, history_for_llm(session, SUMMARY_HISTORY_LIMIT), temperature=0.3)
    except llm.LLMError as exc:
        logger.error("No se pudo generar el resumen: %s", exc)
        return [_bot(session, SERVICE_ERROR, Message.NOTICE, {"error": True})]
    data = clean_summary(raw)
    data["model"] = model
    session.finished = True
    session.score = data["score"]
    session.save()
    return [_bot(session, data["summary"], Message.SUMMARY, data)]


# --- Estadísticas para el panel lateral ------------------------------------

def _avg(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 1) if values else None


def session_stats(session):
    if session is None:
        return None
    bot_msgs = list(session.messages.filter(sender=Message.BOT))
    fillers = Counter()
    for m in bot_msgs:
        fillers.update(m.data.get("fillers", []))
    stats = {"fillers": [{"word": w, "count": c} for w, c in fillers.most_common(6)],
             "score": session.score, "finished": session.finished}

    if session.mode == PracticeSession.INTERVIEW:
        scored = [m.data["scores"] for m in bot_msgs if m.kind == Message.FEEDBACK and m.data.get("scores")]
        stats.update({
            "answers": sum(1 for m in bot_msgs if m.kind == Message.FEEDBACK),
            "metrics": [{"label": label, "value": _avg([s.get(key) for s in scored]), "max": 5}
                        for key, label in (("claridad", "Claridad"), ("estructura", "Estructura"),
                                           ("seguridad", "Seguridad"))],
        })
    else:
        corrections = [m.data for m in bot_msgs if m.kind == Message.CORRECTION]
        scores = [c.get("scores") or {} for c in corrections]
        metrics = [{"label": label, "value": _avg([s.get(key) for s in scores]), "max": 10}
                   for key, label in (("ortografia", "Ortografía"), ("gramatica", "Gramática"),
                                      ("claridad", "Claridad"))]
        errors = Counter()
        for c in corrections:
            for e in c.get("errors", []):
                errors[(e["wrong"].lower(), e["right"])] += 1
        stats.update({
            "texts": len(corrections),
            "metrics": metrics,
            "average": _avg([m["value"] for m in metrics]),
            "errors": [{"wrong": w, "right": r, "count": n} for (w, r), n in errors.most_common(5)],
        })
    return stats
