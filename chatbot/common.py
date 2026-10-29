"""Utilidades compartidas por la entrevista, la gramática y el progreso."""
import random
import re
import math

from django.utils import timezone

from .models import Message

SERVICE_ERROR = "No pude conectarme con el servicio de inteligencia artificial. Intenta de nuevo en unos minutos."
VOICE_PREFIX = "[Dictado por voz] "
MAX_INPUT_CHARS = 4000
LIST_RE = re.compile(r"(^|\n)\s*(\d+[.)]|[-*•])\s+")


def clean_str(value, limit=2000):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def clean_list(value, limit=6):
    if not isinstance(value, list):
        return []
    return [s.strip()[:400] for s in value if isinstance(s, str) and s.strip()][:limit]


def clamp(value, low, high, digits=1):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    number = max(low, min(high, number))
    return round(number) if digits == 0 else round(number, digits)


def average(values, digits=1):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    result = sum(values) / len(values)
    return round(result) if digits == 0 else round(result, digits)


def looks_like_assistant(message, limit):
    """True si el texto parece una respuesta de asistente (muy largo o con listas)."""
    return len(message) > limit or bool(LIST_RE.search(message))


def score_label(score):
    if score is None:
        return ""
    if score >= 90:
        return "Excelente"
    if score >= 75:
        return "Respuesta sólida"
    if score >= 60:
        return "Buena base"
    if score >= 40:
        return "Necesita trabajo"
    return "Muy débil"


def score_tone(score):
    """Nombre de color para pintar un puntaje: good, mid o low."""
    if score is None:
        return "mid"
    return "good" if score >= 75 else "mid" if score >= 60 else "low"


def bot(session, text, kind=Message.TEXT, data=None):
    return Message.objects.create(session=session, sender=Message.BOT, kind=kind, text=text, data=data or {})


def local_time(dt, fmt="%H:%M"):
    return timezone.localtime(dt).strftime(fmt)


def serialize_message(message):
    return {"id": message.id, "sender": message.sender, "kind": message.kind, "text": message.text,
            "data": message.data, "time": local_time(message.created_at)}


# --- Respuestas del modelo propio de intenciones (sin API) ------------------

FAREWELLS = ["¡Hasta luego! Tu progreso queda guardado.", "¡Nos vemos! Aquí estaré cuando quieras practicar."]
THANKS = ["¡Con gusto! Sigamos.", "¡Para eso estoy! Continuemos."]
HELP = {
    "interview": "Responde la pregunta en voz alta o escribiendo y presiona «Enviar respuesta». "
                 "Puedes pedir una pista, saltar la pregunta o terminar cuando quieras.",
    "grammar": "Escribe o dicta un texto y presiona «Revisar texto». Los errores se marcan en el texto; "
               "tócalos para ver la regla y aplicar la corrección.",
}


def intent_reply(intent, page):
    """
    Respuesta a un comando detectado por el modelo propio.
    Devuelve {"message": str, "navigate": url|None, "action": str|None}.
    """
    tag = intent.tag
    reply = {"message": "", "navigate": None, "action": None}
    if tag == "cambiar_gramatica" and page != "grammar":
        reply.update(message="Vamos a la sección Expresión.", navigate="/gramatica")
    elif tag == "cambiar_entrevista" and page != "interview":
        reply.update(message="Vamos a la entrevista.", navigate="/entrevista")
    elif tag in ("cambiar_gramatica", "cambiar_entrevista"):
        reply["message"] = "Ya estás en este modo."
    elif tag == "reiniciar":
        reply.update(message="Empecemos de nuevo.",
                     navigate="/entrevista?nueva=1" if page == "interview" else "/gramatica")
    elif tag == "terminar":
        reply.update(message="Terminemos aquí.", action="finish")
    elif tag == "ayuda":
        reply["message"] = HELP[page]
    elif tag == "despedida":
        reply["message"] = random.choice(FAREWELLS)
    elif tag == "agradecimiento":
        reply["message"] = random.choice(THANKS)
    else:  # saludo
        reply["message"] = ("¡Hola! Cuando estés listo, responde la pregunta." if page == "interview"
                            else "¡Hola! Escribe un texto y lo reviso.")
    return reply
