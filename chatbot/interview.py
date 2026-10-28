"""
Simulador de entrevista.

Flujo: preparación → pregunta → respuesta → retroalimentación → siguiente pregunta …
→ reporte final. La siguiente pregunta se genera junto con la evaluación y se
guarda como "pendiente", así "Siguiente pregunta" no gasta otra llamada a la API.
"""
import logging

from django.conf import settings

from . import intents, llm, prompts
from .common import (SERVICE_ERROR, VOICE_PREFIX, MAX_INPUT_CHARS, average, bot, clamp, clean_list,
                     clean_str, intent_reply, looks_like_assistant, score_label, serialize_message)
from .models import Message, PracticeSession

logger = logging.getLogger("chatbot")

MAX_CONTEXT_CHARS = 4000
ROLE_SUGGESTIONS = [
    "Desarrollador web", "Desarrollador de aplicaciones móviles", "Soporte técnico y mesa de ayuda",
    "Administrador de redes", "Analista de ciberseguridad", "Analista de datos", "Tester de software (QA)",
    "Ingeniero de sistemas embebidos e IoT", "Ingeniero en automatización industrial",
]


class InterviewError(Exception):
    """Error que se le muestra al usuario tal cual."""


# --- Utilidades -------------------------------------------------------------

def _header(session):
    return {
        "role": session.role,
        "level": prompts.LEVEL_TEXT.get(session.level, session.level),
        "interview_type": prompts.TYPE_TEXT.get(session.interview_type, session.interview_type),
        "context": session.context_summary or "sin datos adicionales",
    }


def _questions(session):
    return list(session.messages.filter(kind=Message.QUESTION).order_by("created_at", "id"))


def _previous_text(session, exclude_current=True):
    texts = [m.text for m in _questions(session)]
    if exclude_current and texts:
        texts = texts[:-1]
    return " | ".join(texts[-10:]) or "ninguna"


def _ask(session, question, question_type):
    session.questions_asked += 1
    session.current_question = question
    session.current_question_type = question_type or ""
    session.pending_question = ""
    session.pending_question_type = ""
    session.save()
    return bot(session, question, Message.QUESTION,
               {"question_number": session.questions_asked, "question_type": question_type or ""})


def _clean_question(raw):
    question = clean_str(raw.get("question"), 600)
    if not question:
        raise llm.LLMError("el modelo no devolvió una pregunta")
    return question, clean_str(raw.get("question_type"), 40) or "Pregunta"


# --- Iniciar ----------------------------------------------------------------

def start(user, *, role, level="junior", interview_type="mixta", total=8, answer_mode="voice",
          job_description="", cv_text="", planned=None, context_summary=""):
    role = (role or "").strip()[:200]
    if not role:
        raise InterviewError("Escribe el puesto para el que quieres practicar.")
    level = level if level in dict(PracticeSession.LEVELS) else "junior"
    interview_type = interview_type if interview_type in dict(PracticeSession.TYPES) else "mixta"
    planned = [q for q in (planned or []) if isinstance(q, str) and q.strip()][:10]
    total = len(planned) if planned else max(3, min(10, int(total or settings.INTERVIEW_QUESTIONS)))

    session = PracticeSession(
        user=user, mode=PracticeSession.INTERVIEW, role=role, level=level, interview_type=interview_type,
        answer_mode="text" if answer_mode == "text" else "voice", total_questions=total,
        job_description=job_description[:MAX_CONTEXT_CHARS], cv_text=cv_text[:MAX_CONTEXT_CHARS],
        context_summary=context_summary, planned_questions=planned)

    if planned:
        question, question_type = planned[0], "Repaso"
    else:
        system = prompts.INTERVIEW_START.format(
            **_header(session), job_description=session.job_description or "",
            cv_text=session.cv_text or "")
        raw, model = llm.complete_json(system, [{"role": "user", "content": "Empieza la entrevista."}],
                                       temperature=0.6, max_tokens=900)
        session.context_summary = clean_str(raw.get("context_summary"), 900) or ""
        question, question_type = _clean_question(raw)
    session.save()
    _ask(session, question, question_type)
    return session


# --- Responder --------------------------------------------------------------

def _clean_evaluation(raw):
    status = raw.get("status") if raw.get("status") in ("answer", "request", "invalid") else None
    feedback = raw.get("feedback") if status != "invalid" else None
    if isinstance(feedback, dict):
        feedback = {"good": clean_list(feedback.get("good"), 3), "improve": clean_list(feedback.get("improve"), 3),
                    "example": clean_str(feedback.get("example"), 600)}
        if not (feedback["good"] or feedback["improve"]):
            feedback = None
    else:
        feedback = None
    if status is None:
        status = "answer" if feedback else "request"
    if status != "answer":
        feedback = None
    score = clamp(raw.get("score"), 0, 100, 0) if feedback else None
    scores = raw.get("scores") if feedback else None
    if isinstance(scores, dict):
        scores = {k: clamp(scores.get(k), 1, 5) for k in ("claridad", "estructura", "seguridad")}
        scores = {k: v for k, v in scores.items() if v is not None} or None
    else:
        scores = None
    if feedback and score is None and scores:
        score = round(average(list(scores.values())) / 5 * 100)
    return {
        "status": status,
        "message": clean_str(raw.get("message"), 600) or "",
        "score": score,
        "label": (clean_str(raw.get("label"), 40) or score_label(score)) if feedback else None,
        "feedback": feedback,
        "scores": scores,
        "fillers": [f.lower() for f in clean_list(raw.get("fillers"), 30)] if feedback else [],
        "next_question": clean_str(raw.get("next_question"), 600) if feedback else None,
        "next_question_type": clean_str(raw.get("next_question_type"), 40),
    }


def _off_role(data):
    return not data["feedback"] and looks_like_assistant(data["message"], 320)


def answer(session, text, source="text", duration=None):
    """
    Evalúa la respuesta a la pregunta actual.
    Devuelve {"kind": answer|request|invalid|intent, "message": {...}, "navigate", "action"}.
    """
    if session.finished:
        raise InterviewError("Esta entrevista ya terminó. Empieza una nueva para seguir practicando.")
    text = (text or "").strip()[:MAX_INPUT_CHARS]
    if not text:
        raise InterviewError("Escribe o dicta tu respuesta.")
    duration = clamp(duration, 0, 3600)
    number = session.questions_asked
    Message.objects.create(session=session, sender=Message.USER, text=text,
                           data={"source": "voice" if source == "voice" else "text", "duration": duration,
                                 "question_number": number})

    intent = intents.classify(text) if len(text.split()) <= 4 or source != "voice" else None
    if intent:
        reply = intent_reply(intent, "interview")
        meta = {"source": "intent", "intent": intent.tag, "confidence": round(intent.confidence, 2),
                "question_number": number}
        msg = bot(session, reply["message"], Message.TEXT, meta)
        return {"kind": "intent", "message": serialize_message(msg),
                "navigate": reply["navigate"], "action": reply["action"]}

    is_last = number >= session.total_questions or (
        session.planned_questions and number >= len(session.planned_questions))
    next_rule = prompts.NO_NEXT_RULE if is_last else prompts.NEXT_RULE.format(
        following=number + 1, total=session.total_questions)
    system = prompts.INTERVIEW_EVALUATE.format(
        **_header(session), number=number, total=session.total_questions,
        question_type=session.current_question_type or "Pregunta", question=session.current_question,
        previous=_previous_text(session), next_rule=next_rule)
    content = (VOICE_PREFIX if source == "voice" else "") + text
    conversation = [{"role": "user", "content": content}]
    raw, model = llm.complete_json(system, conversation, temperature=0.5, max_tokens=1400)
    data = _clean_evaluation(raw)
    if _off_role(data):
        logger.info("Respuesta fuera de papel en la entrevista %s; reintentando", session.id)
        conversation.append({"role": "user", "content": prompts.INTERVIEW_REMINDER})
        raw, model = llm.complete_json(system, conversation, temperature=0.3, max_tokens=1400)
        data = _clean_evaluation(raw)

    message_text = data.pop("message")
    data.update({"model": model, "question_number": number, "duration": duration})
    if data["status"] == "answer":
        words = len(text.split())
        data["words"] = words
        if source == "voice" and duration and duration >= 5:
            data["wpm"] = round(words / duration * 60)
        if data["next_question"] and not is_last and not session.planned_questions:
            session.pending_question = data["next_question"]
            session.pending_question_type = data["next_question_type"] or ""
            session.save()
        msg = bot(session, message_text, Message.FEEDBACK, data)
    else:
        data["invalid"] = data["status"] == "invalid"
        msg = bot(session, message_text, Message.TEXT, data)
    return {"kind": data["status"], "message": serialize_message(msg), "navigate": None, "action": None}


# --- Siguiente, otra pregunta y terminar -------------------------------------

def _generate_question(session, number, extra=""):
    system = prompts.INTERVIEW_NEW_QUESTION.format(
        **_header(session), previous=_previous_text(session, exclude_current=False), number=number,
        total=session.total_questions, extra=extra)
    raw, _ = llm.complete_json(system, [{"role": "user", "content": "Siguiente pregunta."}],
                               temperature=0.7, max_tokens=700)
    return _clean_question(raw)


def next_question(session):
    if session.finished:
        raise InterviewError("Esta entrevista ya terminó.")
    if session.questions_asked >= session.total_questions:
        return {"finished": True, "summary": finish(session)}
    number = session.questions_asked + 1
    if session.planned_questions and number <= len(session.planned_questions):
        question, question_type = session.planned_questions[number - 1], "Repaso"
    elif session.pending_question:
        question, question_type = session.pending_question, session.pending_question_type
    else:
        question, question_type = _generate_question(session, number)
    msg = _ask(session, question, question_type)
    return {"finished": False, "question": serialize_message(msg)}


def other_question(session):
    """Cambia la pregunta actual por otra, sin avanzar el conteo."""
    if session.finished:
        raise InterviewError("Esta entrevista ya terminó.")
    question, question_type = _generate_question(
        session, session.questions_asked,
        extra=f"El candidato pidió cambiar esta pregunta: «{session.current_question}». Haz una distinta.")
    session.questions_asked -= 1
    msg = _ask(session, question, question_type)
    msg.data["replaced"] = True
    msg.save(update_fields=["data"])
    return serialize_message(msg)


def latest_feedback_by_question(session):
    """{número de pregunta: (pregunta, respuesta, retroalimentación)} con el último intento de cada una."""
    questions, answers, feedback = {}, {}, {}
    for m in session.messages.all():
        number = m.data.get("question_number")
        if not number:
            continue
        if m.kind == Message.QUESTION:
            questions[number] = m
        elif m.sender == Message.USER:
            answers[number] = m
        elif m.kind == Message.FEEDBACK:
            feedback[number] = (m, answers.get(number))
    return {n: (questions.get(n), feedback[n][1], feedback[n][0]) for n in sorted(feedback)}


def finish(session):
    answered = latest_feedback_by_question(session)
    if not answered:
        raise InterviewError("Responde al menos una pregunta antes de terminar.")
    lines = []
    for n, (q, ans, fb) in answered.items():
        lines.append(f"Pregunta {n}: {q.text if q else ''}\nRespuesta: {ans.text if ans else ''}\n"
                     f"Calificación: {fb.data.get('score')} ({fb.data.get('label')})")
    invalid = session.messages.filter(sender=Message.BOT, kind=Message.TEXT, data__invalid=True).count()
    if invalid:
        lines.append(f"Mensajes sin sentido o fuera de tema durante la entrevista: {invalid}")
    system = prompts.INTERVIEW_SUMMARY.format(**_header(session))
    raw, model = llm.complete_json(system, [{"role": "user", "content": "\n\n".join(lines)}],
                                   temperature=0.3, max_tokens=1000)
    score = clamp(raw.get("score"), 0, 100, 0)
    if score is None:
        score = round(average([fb.data.get("score") for _, _, fb in answered.values()]) or 0)
    data = {"score": score, "label": clean_str(raw.get("label"), 40) or score_label(score),
            "summary": clean_str(raw.get("summary"), 1000) or "", "strengths": clean_list(raw.get("strengths"), 3),
            "improve": clean_list(raw.get("improve"), 3), "model": model}
    session.finished = True
    session.score = score
    session.save()
    return serialize_message(bot(session, data["summary"], Message.SUMMARY, data))


# --- Estado y reporte -------------------------------------------------------

def serialize_session(session):
    return {
        "id": session.id, "role": session.role, "level": session.get_level_display(),
        "interview_type": session.get_interview_type_display(), "answer_mode": session.answer_mode,
        "questions_asked": session.questions_asked, "total_questions": session.total_questions,
        "finished": session.finished, "score": session.score,
    }


def state(session):
    """Lo que necesita la pantalla de sesión para dibujarse (al cargar o después de recargar)."""
    if session is None:
        return None
    messages = list(session.messages.all())
    question_msg = next((m for m in reversed(messages) if m.kind == Message.QUESTION), None)
    after = messages[messages.index(question_msg) + 1:] if question_msg else []
    feedback = next((m for m in reversed(after) if m.kind == Message.FEEDBACK), None)
    interviewer = next((m for m in reversed(after) if m.sender == Message.BOT and m.kind == Message.TEXT), None)
    if interviewer and feedback and interviewer.created_at < feedback.created_at:
        interviewer = None
    answer_msg = None
    if feedback:
        before = messages[:messages.index(feedback)]
        answer_msg = next((m for m in reversed(before) if m.sender == Message.USER), None)
    return {
        "answer": answer_msg.text if answer_msg else "",
        "session": serialize_session(session),
        "phase": "finished" if session.finished else "feedback" if feedback else "question",
        "question": serialize_message(question_msg) if question_msg else None,
        "feedback": serialize_message(feedback) if feedback else None,
        "interviewer": serialize_message(interviewer) if interviewer else None,
        "is_last": session.questions_asked >= session.total_questions,
    }


def report(session):
    answered = latest_feedback_by_question(session)
    summary = session.messages.filter(kind=Message.SUMMARY).last()
    rows = []
    for n, (q, ans, fb) in answered.items():
        d = fb.data
        rows.append({
            "number": n, "question": q.text if q else "", "question_type": q.data.get("question_type") if q else "",
            "answer": ans.text if ans else "", "duration": d.get("duration"), "score": d.get("score"),
            "label": d.get("label"), "improve": (d.get("feedback") or {}).get("improve", [])[:1],
            "good": (d.get("feedback") or {}).get("good", [])[:2],
            "example": (d.get("feedback") or {}).get("example"), "fillers": d.get("fillers", []),
            "wpm": d.get("wpm"),
        })
    metrics = {}
    for key in ("claridad", "estructura", "seguridad"):
        metrics[key] = average([(fb.data.get("scores") or {}).get(key) for _, _, fb in answered.values()])
    durations = [r["duration"] for r in rows if r["duration"]]
    return {
        "session": session,
        "summary": summary.data if summary else None,
        "rows": rows,
        "metrics": metrics,
        "weakest": min((k for k in metrics if metrics[k] is not None), key=lambda k: metrics[k], default=None),
        "fillers_total": sum(len(r["fillers"]) for r in rows),
        "total_seconds": round(sum(durations)) if durations else None,
        "lowest": [r["question"] for r in sorted(rows, key=lambda r: r["score"] if r["score"] is not None else 101)[:2]],
    }


def practice_lowest(user, source_session, questions):
    """Nueva entrevista solo con las preguntas indicadas (por ejemplo, las de menor calificación)."""
    return start(user, role=source_session.role, level=source_session.level,
                 interview_type=source_session.interview_type, answer_mode=source_session.answer_mode,
                 planned=questions, context_summary=source_session.context_summary)


__all__ = ["start", "answer", "next_question", "other_question", "finish", "state", "report",
           "practice_lowest", "InterviewError", "ROLE_SUGGESTIONS", "SERVICE_ERROR"]
