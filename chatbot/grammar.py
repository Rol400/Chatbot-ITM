"""Revisión de textos: calificación, errores ubicados en el texto y ejercicios."""
import logging
import random

from django.utils import timezone

from . import intents, llm, prompts
from .common import (MAX_INPUT_CHARS, VOICE_PREFIX, average, bot, clamp, clean_list, clean_str, intent_reply,
                     looks_like_assistant, score_label, serialize_message)
from .models import Message, PracticeSession

logger = logging.getLogger("chatbot")

ERROR_TYPES = ["Gramática", "Acentos", "Ortografía", "Puntuación", "Muletilla", "Estilo"]
REMINDER = ("Tu respuesta anterior se salió del papel de calificador. Vuelve a responder siguiendo las reglas: "
            "corrige el último mensaje del usuario como \"text\" o, si no se puede revisar, usa \"invalid\".")


class GrammarError(Exception):
    """Error que se le muestra al usuario tal cual."""


def today_session(user):
    """Las revisiones se agrupan en una sesión por día."""
    today = timezone.localdate()
    session = (PracticeSession.objects.filter(user=user, mode=PracticeSession.GRAMMAR, finished=False)
               .order_by("-created_at").first())
    if session and timezone.localdate(session.created_at) == today:
        return session
    return PracticeSession.objects.create(user=user, mode=PracticeSession.GRAMMAR)


def locate_errors(text, errors):
    """Agrega start/end a cada error buscando su fragmento en el texto, sin encimar."""
    used = []
    lowered = text.lower()
    cursor = 0
    for err in errors:
        fragment = err["wrong"]
        start = -1
        for haystack, needle in ((text, fragment), (lowered, fragment.lower())):
            for begin in (cursor, 0):
                pos = haystack.find(needle, begin)
                while pos != -1 and any(pos < e and pos + len(needle) > s for s, e in used):
                    pos = haystack.find(needle, pos + 1)
                if pos != -1:
                    start = pos
                    break
            if start != -1:
                break
        if start == -1:
            err["start"] = err["end"] = None
            continue
        err["start"], err["end"] = start, start + len(fragment)
        used.append((start, start + len(fragment)))
        cursor = start + len(fragment)
    return errors


def _clean(raw):
    status = raw.get("status") if raw.get("status") in ("text", "invalid") else "text"
    errors = []
    if status == "text":
        for err in raw.get("errors") or []:
            if isinstance(err, dict) and clean_str(err.get("wrong"), 120):
                kind = clean_str(err.get("type"), 40) or "Gramática"
                errors.append({"type": kind if kind in ERROR_TYPES else "Estilo",
                               "wrong": clean_str(err.get("wrong"), 120), "right": clean_str(err.get("right"), 200) or "",
                               "explanation": clean_str(err.get("explanation"), 400) or ""})
    scores = raw.get("scores") if status == "text" else None
    if isinstance(scores, dict):
        scores = {k: clamp(scores.get(k), 0, 10) for k in ("ortografia", "gramatica", "claridad")}
        if all(v is None for v in scores.values()):
            scores = None
    else:
        scores = None
    score = round(average(list(scores.values())) * 10) if scores and average(list(scores.values())) is not None else None
    return {
        "status": status,
        "message": clean_str(raw.get("message"), 500) or "",
        "corrected": clean_str(raw.get("corrected"), MAX_INPUT_CHARS) if status == "text" else None,
        "errors": errors[:20],
        "fillers": [f.lower() for f in clean_list(raw.get("fillers"), 30)] if status == "text" else [],
        "scores": scores,
        "score": score,
        "label": (clean_str(raw.get("label"), 40) or score_label(score)) if score is not None else None,
        "tip": clean_str(raw.get("tip"), 400) if status == "text" else None,
    }


def check(user, text, source="text"):
    text = (text or "").strip()[:MAX_INPUT_CHARS]
    if not text:
        raise GrammarError("Escribe o dicta un texto para revisarlo.")
    session = today_session(user)
    Message.objects.create(session=session, sender=Message.USER, text=text,
                           data={"source": "voice" if source == "voice" else "text"})

    intent = intents.classify(text)
    if intent and intent.tag not in ("terminar", "reiniciar"):
        reply = intent_reply(intent, "grammar")
        meta = {"source": "intent", "intent": intent.tag, "confidence": round(intent.confidence, 2)}
        msg = bot(session, reply["message"], Message.TEXT, meta)
        return {"status": "intent", "message": serialize_message(msg), "navigate": reply["navigate"]}

    conversation = [{"role": "user", "content": (VOICE_PREFIX if source == "voice" else "") + text}]
    raw, model = llm.complete_json(prompts.GRAMMAR_SYSTEM, conversation, temperature=0.2, max_tokens=1800)
    data = _clean(raw)
    if data["status"] == "invalid" and looks_like_assistant(data["message"], 400):
        conversation.append({"role": "user", "content": REMINDER})
        raw, model = llm.complete_json(prompts.GRAMMAR_SYSTEM, conversation, temperature=0.1, max_tokens=1800)
        data = _clean(raw)
    data["model"] = model
    data["original"] = text
    if data["status"] == "text":
        locate_errors(text, data["errors"])
        msg = bot(session, data.pop("message"), Message.CORRECTION, data)
    else:
        data["invalid"] = True
        msg = bot(session, data.pop("message"), Message.TEXT, data)
    return {"status": data["status"], "message": serialize_message(msg), "navigate": None}


def exercise():
    system = prompts.GRAMMAR_EXERCISE.format(topic=random.choice(prompts.EXERCISE_TOPICS))
    raw, _ = llm.complete_json(system, [{"role": "user", "content": "Dame un ejercicio."}],
                               temperature=0.9, max_tokens=700)
    text = clean_str(raw.get("text"), 1200)
    if not text:
        raise llm.LLMError("el modelo no devolvió el ejercicio")
    return {"text": text, "title": clean_str(raw.get("title"), 80) or "Ejercicio"}
