"""Plan de práctica de la sección de expresión.

Después de revisar un texto, cada criterio con resultado bajo activa un ejercicio
basado en técnicas con respaldo en estudios publicados (ver EVIDENCE).
"""
import re
import unicodedata
from datetime import timedelta

from django.utils import timezone

from . import llm, prompts
from .common import clean_str
from .models import Message, SpellingWord

LOW_SCORE = 6               # 0 a 10: este valor o menos activa el ejercicio
FILLERS_PER_100 = 3         # muletillas por cada 100 palabras que activan el ejercicio
LONG_SENTENCE = 35          # palabras: una oración más larga afecta la claridad
SUMMARY_LIMIT = 25          # palabras máximas en «dilo en una sola oración»

EXERCISES = {
    "muletillas": {
        "criterion": "Muletillas", "title": "Encuéntralas y cámbialas por una pausa", "minutes": 4,
        "summary": "Primero las marcas tú en tu propio texto; luego hablas un minuto haciendo una pausa en silencio donde ibas a decir una.",
        "why": "Entrenamiento de conciencia y respuesta alterna (una pausa en silencio): en estudios con universitarios que hablaban en público, las muletillas bajaron en todos los participantes.",
        "own": "Grábate dos minutos explicando tu proyecto, escúchate y cuenta cada muletilla. Repítelo cada semana y compara el número.",
    },
    "ortografia": {
        "criterion": "Ortografía y acentos", "title": "Mira, cubre, escribe y compara", "minutes": 3,
        "summary": "Con las palabras que escribiste mal: las ves, se tapan, las escribes de memoria y se comparan. Vuelven en días espaciados.",
        "why": "«Cover, copy, compare» es una técnica establecida para ortografía; recordar de memoria y espaciar los repasos fija mejor lo aprendido que repetir muchas veces el mismo día.",
        "own": "Repasa tus palabras en los días que te toca, aunque sea un minuto: espaciar los repasos funciona mejor que estudiar todo de golpe.",
    },
    "gramatica": {
        "criterion": "Gramática", "title": "Corrige tu mismo error en oraciones nuevas", "minutes": 3,
        "summary": "Oraciones nuevas con el mismo patrón de tus errores. Al responder ves la regla al instante.",
        "why": "La corrección escrita de los errores propios mejora la precisión gramatical, según metaanálisis de decenas de estudios.",
        "own": "Cuando te corrijan algo, escribe tú la versión correcta en lugar de solo leerla.",
    },
    "puntuacion": {
        "criterion": "Puntuación", "title": "Une las oraciones", "minutes": 3,
        "summary": "Juntas oraciones cortas en una sola con el conector y la puntuación correctos.",
        "why": "Combinar oraciones mejora la calidad de la escritura; en cambio, las lecciones de gramática aisladas no la mejoran.",
        "own": "Toma un párrafo tuyo con oraciones muy cortas y únelas con conectores como «sin embargo», «por lo tanto» o «aunque».",
    },
    "claridad": {
        "criterion": "Claridad", "title": "Dilo en una sola oración", "minutes": 4,
        "summary": f"Resumes tu idea principal en {SUMMARY_LIMIT} palabras o menos y la comparas con una versión modelo.",
        "why": "Resumir y estudiar textos modelo están entre las prácticas con mayor efecto para escribir mejor.",
        "own": "Antes de una exposición o un correo importante, escribe tu idea principal en una sola oración. Si no cabe, todavía no está clara.",
    },
}

EVIDENCE = [
    "Montes, Heinicke y Geierman (2019). Awareness training reduces college students' speech disfluencies in public speaking. Journal of Applied Behavior Analysis, 52(3), 746-755.",
    "Pawlik et al. (2020). Reducing speech disfluencies during public speaking using brief habit reversal. Journal of Applied Behavior Analysis.",
    "Spieler y Miltenberger (2017). Using awareness training to decrease nervous habits during public speaking. Journal of Applied Behavior Analysis, 50, 38-47.",
    "Cepeda et al. (2006). Distributed practice in verbal recall tasks: a review and quantitative synthesis. Psychological Bulletin, 132(3), 354-380.",
    "Roediger y Karpicke (2006). Test-enhanced learning. Psychological Science, 17(3), 249-255.",
    "Graham y Perin (2007). Writing Next. Alliance for Excellent Education.",
    "Metaanálisis de 35 estudios sobre corrección escrita y precisión gramatical (NIE, Singapur, 2020).",
]


def words(text):
    return re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", text or "")


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", text or "") if s.strip()]


def fold(text):
    """Minúsculas y sin espacios repetidos (conserva acentos)."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def tokens(text, keep_punctuation=True):
    pattern = r"[\wáéíóúüñ]+|[^\w\s]" if keep_punctuation else r"[\wáéíóúüñ]+"
    return re.findall(pattern, fold(text))


def same_sentence(answer, expected, keep_punctuation=False):
    a, b = tokens(answer, keep_punctuation), tokens(expected, keep_punctuation)
    if not keep_punctuation:
        return a == b
    return [t for t in a if t not in "¿¡"] == [t for t in b if t not in "¿¡"]


def filler_counts(data):
    """Muletillas que detectó el modelo en la revisión: {muletilla: veces}."""
    found = {}
    items = list(data.get("fillers") or [])
    items += [e.get("wrong", "") for e in (data.get("errors") or []) if e.get("type") == "Muletilla"]
    for item in items:
        key = fold(item).strip("¿?¡!.,;: ")
        if key:
            found[key] = found.get(key, 0) + 1
    return found


def detect_fillers(text):
    """Pide al modelo las muletillas de un dictado (para el minuto de práctica)."""
    raw, _ = llm.complete_json(prompts.PRACTICE_FILLERS, [{"role": "user", "content": text[:4000]}],
                               temperature=0, max_tokens=400)
    return [fold(f) for f in (raw.get("fillers") or []) if isinstance(f, str) and f.strip()][:60]


def per_100(count, total_words):
    return round(count * 100 / total_words, 1) if total_words else 0.0


def spelling_errors(data):
    out = []
    for err in data.get("errors") or []:
        right = (err.get("right") or "").strip(" .,;:")
        if err.get("type") in ("Ortografía", "Acentos") and right and len(right.split()) <= 3 and len(right) <= 60:
            out.append({"word": right, "wrong": err.get("wrong", ""), "explanation": err.get("explanation", "")})
    return out


def build_plan(data):
    """Elige los ejercicios según los criterios bajos de una revisión."""
    scores = data.get("scores") or {}
    errors = data.get("errors") or []
    text = data.get("original") or ""
    by_type = {}
    for err in errors:
        by_type[err.get("type")] = by_type.get(err.get("type"), 0) + 1
    total_words = len(words(text))
    plan = []

    filler_count = sum(filler_counts(data).values())
    rate = per_100(filler_count, total_words)
    if filler_count >= 2 and rate >= FILLERS_PER_100:
        plan.append(("muletillas", min(10, 10 - rate)))
    if spelling_errors(data):
        plan.append(("ortografia", scores.get("ortografia") if scores.get("ortografia") is not None else 6))
    if (scores.get("gramatica") is not None and scores["gramatica"] <= LOW_SCORE) or by_type.get("Gramática", 0) >= 2:
        plan.append(("gramatica", scores.get("gramatica") if scores.get("gramatica") is not None else 6))
    if by_type.get("Puntuación", 0) >= 2:
        plan.append(("puntuacion", 6))
    longest = max((len(words(s)) for s in sentences(text)), default=0)
    if (scores.get("claridad") is not None and scores["claridad"] <= LOW_SCORE) or longest > LONG_SENTENCE:
        plan.append(("claridad", scores.get("claridad") if scores.get("claridad") is not None else 6))

    plan.sort(key=lambda item: item[1])
    return [dict(kind=kind, **{k: v for k, v in EXERCISES[kind].items() if k in ("criterion", "title", "minutes", "summary", "why")})
            for kind, _ in plan]


def save_spelling_words(user, data):
    today = timezone.localdate()
    for item in spelling_errors(data):
        SpellingWord.objects.update_or_create(
            user=user, word=item["word"].lower(),
            defaults={"wrong": item["wrong"][:60], "explanation": item["explanation"][:400], "stage": 0,
                      "due": today, "learned": False})


def due_words(user, message_data=None, limit=8):
    today = timezone.localdate()
    chosen = []
    if message_data:
        mine = {i["word"].lower() for i in spelling_errors(message_data)}
        chosen += list(SpellingWord.objects.filter(user=user, word__in=mine, learned=False))
    seen = {w.id for w in chosen}
    for w in SpellingWord.objects.filter(user=user, learned=False, due__lte=today):
        if w.id not in seen and len(chosen) < limit:
            chosen.append(w)
    return chosen[:limit]


def review_word(user, word_id, correct):
    word = SpellingWord.objects.get(user=user, pk=word_id)
    today = timezone.localdate()
    if correct:
        if word.stage >= len(SpellingWord.INTERVALS):
            word.learned = True
        else:
            word.due = today + timedelta(days=SpellingWord.INTERVALS[word.stage])
            word.stage += 1
    else:
        word.stage = 0
        word.due = today + timedelta(days=1)
    word.save()
    return word


def schedule(user):
    today = timezone.localdate()
    pending = SpellingWord.objects.filter(user=user, learned=False)
    return {
        "today": pending.filter(due__lte=today).count(),
        "tomorrow": pending.filter(due=today + timedelta(days=1)).count(),
        "later": pending.filter(due__gt=today + timedelta(days=1)).count(),
        "learned": SpellingWord.objects.filter(user=user, learned=True).count(),
    }


def word_json(word):
    return {"id": word.id, "word": word.word, "wrong": word.wrong, "explanation": word.explanation, "stage": word.stage}


# --- Ejercicios generados por el modelo (se guardan para no repetir llamadas) ---

def _errors_of(data, kinds):
    return [e for e in (data.get("errors") or []) if e.get("type") in kinds][:5]


def generate(message, kind):
    data = message.data or {}
    stored = (data.get("practice") or {}).get(kind)
    if stored:
        return stored
    if kind == "gramatica":
        errs = _errors_of(data, ("Gramática",)) or _errors_of(data, ("Estilo",))
        system = prompts.PRACTICE_GRAMMAR.format(errors=_format_errors(errs))
        raw, _ = llm.complete_json(system, [{"role": "user", "content": "Genera el ejercicio."}], temperature=0.5, max_tokens=1200)
        items = [{"sentence": clean_str(i.get("sentence"), 300), "answer": clean_str(i.get("answer"), 300),
                  "rule": clean_str(i.get("rule"), 300) or ""}
                 for i in (raw.get("items") or []) if isinstance(i, dict)]
        result = {"items": [i for i in items if i["sentence"] and i["answer"]][:5]}
    elif kind == "puntuacion":
        errs = _errors_of(data, ("Puntuación",))
        system = prompts.PRACTICE_PUNCTUATION.format(errors=_format_errors(errs))
        raw, _ = llm.complete_json(system, [{"role": "user", "content": "Genera el ejercicio."}], temperature=0.5, max_tokens=1200)
        items = []
        for i in raw.get("items") or []:
            if not isinstance(i, dict):
                continue
            parts = [clean_str(p, 200) for p in (i.get("parts") or []) if clean_str(p, 200)][:3]
            answer = clean_str(i.get("answer"), 400)
            if len(parts) >= 2 and answer:
                items.append({"parts": parts, "connector": clean_str(i.get("connector"), 40) or "",
                              "answer": answer, "rule": clean_str(i.get("rule"), 300) or ""})
        result = {"items": items[:4]}
    elif kind == "claridad":
        source = max(sentences(data.get("original") or ""), key=lambda s: len(words(s)), default="")
        system = prompts.PRACTICE_CLARITY.format(text=data.get("original") or "", limit=SUMMARY_LIMIT)
        raw, _ = llm.complete_json(system, [{"role": "user", "content": "Genera el ejercicio."}], temperature=0.4, max_tokens=700)
        model_text = clean_str(raw.get("model"), 400)
        if model_text and len(words(model_text)) > SUMMARY_LIMIT:
            model_text = " ".join(model_text.split()[:SUMMARY_LIMIT]).rstrip(",;") + "."
        result = {"source": data.get("original") or source, "model": model_text or "", "tip": clean_str(raw.get("tip"), 300) or ""}
    else:
        raise ValueError(kind)
    if (kind in ("gramatica", "puntuacion") and not result["items"]) or (kind == "claridad" and not result["model"]):
        raise llm.LLMError("el modelo no devolvió el ejercicio")
    data.setdefault("practice", {})[kind] = result
    message.data = data
    message.save(update_fields=["data"])
    return result


def _format_errors(errs):
    if not errs:
        return "(sin errores registrados: usa errores comunes del español escrito profesional)"
    return "\n".join(f"- «{e.get('wrong')}» → «{e.get('right')}»: {e.get('explanation')}" for e in errs)


def correction_message(user, message_id):
    return (Message.objects.select_related("session")
            .get(pk=message_id, kind=Message.CORRECTION, session__user=user))
