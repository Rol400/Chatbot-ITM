"""Datos de la página «Mi progreso»."""
from collections import Counter
from datetime import timedelta

from django.utils import timezone

from .common import average, local_time, score_tone
from .models import Message, PracticeSession

PERIOD_DAYS = 30
METRIC_NAMES = {"claridad": "claridad", "estructura": "estructura", "seguridad": "seguridad"}
SUGGESTIONS = {
    "claridad": "Entrevista general de 5 preguntas: responde con frases cortas y una idea principal por respuesta.",
    "estructura": "Entrevista general de 5 preguntas: cuenta la situación, lo que hiciste y el resultado.",
    "seguridad": "Entrevista mixta de 5 preguntas por voz: practica responder sin titubear.",
}


def _messages(user, since=None, until=None):
    qs = Message.objects.filter(session__user=user, sender=Message.BOT)
    if since:
        qs = qs.filter(created_at__gte=since)
    if until:
        qs = qs.filter(created_at__lt=until)
    return qs


def _period_stats(user, since, until=None):
    sessions = PracticeSession.objects.filter(user=user, created_at__gte=since)
    if until:
        sessions = sessions.filter(created_at__lt=until)
    interviews = [s.score for s in sessions.filter(mode=PracticeSession.INTERVIEW, finished=True) if s.score is not None]
    msgs = list(_messages(user, since, until).filter(kind__in=[Message.FEEDBACK, Message.CORRECTION]))
    feedback = [m for m in msgs if m.kind == Message.FEEDBACK]
    corrections = [m for m in msgs if m.kind == Message.CORRECTION]
    fillers = sum(len(m.data.get("fillers", [])) for m in feedback)
    return {
        "sessions": sessions.count(),
        "interview_avg": average(interviews, 0),
        "grammar_avg": average([m.data.get("score") for m in corrections], 0),
        "fillers_per_answer": round(fillers / len(feedback), 1) if feedback else None,
        "feedback": feedback,
        "corrections": corrections,
    }


def _trend(current, previous):
    if current is None or previous is None:
        return None
    return round(current - previous, 1)


def build(user):
    now = timezone.now()
    since = now - timedelta(days=PERIOD_DAYS)
    current = _period_stats(user, since)
    previous = _period_stats(user, since - timedelta(days=PERIOD_DAYS), since)

    finished = list(PracticeSession.objects.filter(user=user, mode=PracticeSession.INTERVIEW, finished=True,
                                                   score__isnull=False).order_by("-created_at")[:8])
    finished.reverse()
    bars = [{"value": round(s.score), "date": local_time(s.created_at, "%d/%m"), "height": max(6, round(s.score * 1.2)),
             "last": i == len(finished) - 1, "id": s.id} for i, s in enumerate(finished)]

    recent = []
    for s in PracticeSession.objects.filter(user=user).order_by("-created_at")[:8]:
        if s.mode == PracticeSession.INTERVIEW:
            if not s.questions_asked:
                continue
            detail = f"{s.role} · {s.get_interview_type_display().lower()} · {s.questions_asked} de {s.total_questions} preguntas"
            score = round(s.score) if s.score is not None else None
            url = f"/reporte/{s.id}" if s.finished else "/entrevista"
        else:
            corrections = [m.data.get("score") for m in s.messages.filter(kind=Message.CORRECTION)]
            if not corrections:
                continue
            detail = "1 texto revisado" if len(corrections) == 1 else f"{len(corrections)} textos revisados"
            score = average(corrections, 0)
            url = "/gramatica"
        recent.append({"date": local_time(s.created_at, "%d/%m"), "mode": s.mode, "detail": detail,
                       "score": score, "tone": score_tone(score), "url": url,
                       "status": "" if s.finished or s.mode == PracticeSession.GRAMMAR else "En curso"})

    errors = Counter()
    for m in current["corrections"]:
        for e in m.data.get("errors", []):
            errors[(e.get("wrong", "").lower(), e.get("right", ""))] += 1
    fillers = Counter()
    for m in current["feedback"] + current["corrections"]:
        fillers.update(m.data.get("fillers", []))

    metric_avgs = {k: average([(m.data.get("scores") or {}).get(k) for m in current["feedback"]])
                   for k in METRIC_NAMES}
    weakest = min((k for k, v in metric_avgs.items() if v is not None), key=lambda k: metric_avgs[k], default=None)

    return {
        "tiles": {
            "sessions": current["sessions"],
            "interview_avg": current["interview_avg"],
            "interview_trend": _trend(current["interview_avg"], previous["interview_avg"]),
            "grammar_avg": current["grammar_avg"],
            "grammar_trend": _trend(current["grammar_avg"], previous["grammar_avg"]),
            "fillers": current["fillers_per_answer"],
            "fillers_trend": _trend(current["fillers_per_answer"], previous["fillers_per_answer"]),
        },
        "bars": bars,
        "recent": recent[:6],
        "errors": [{"wrong": w, "right": r, "count": n} for (w, r), n in errors.most_common(5)],
        "fillers": [{"word": w, "count": n} for w, n in fillers.most_common(6)],
        "weakest": weakest,
        "suggestion": SUGGESTIONS.get(weakest) if weakest else
        "Entrevista mixta de 5 preguntas para conocer tu nivel.",
        "metric_avgs": metric_avgs,
        "empty": current["sessions"] == 0 and not bars,
    }
