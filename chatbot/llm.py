"""
Acceso a los modelos de lenguaje.

Se prueban en el orden de settings.LLM_CHAIN (por ejemplo Groq gpt-oss-120b,
luego gpt-oss-20b y al final Gemini Flash-Lite). Si uno falla, se agota su
cuota o devuelve algo que no es JSON, se pasa al siguiente.
"""
import json
import logging
import re

import httpx
from django.conf import settings

logger = logging.getLogger("chatbot")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    """Ningún modelo de la cadena pudo responder."""


class RateLimited(Exception):
    """El proveedor rechazó la petición por cuota o límite de uso."""


def parse_json(text):
    """Extrae el primer objeto JSON de un texto (tolera ```json ... ```)."""
    if not text:
        raise ValueError("respuesta vacía")
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("la respuesta no contiene JSON")
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("el JSON no es un objeto")
    return data


def _groq_client():
    from groq import Groq

    return Groq(api_key=settings.GROQ_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=0)


def _call_groq(model, system, messages, temperature, max_tokens):
    import groq

    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if model.startswith("openai/gpt-oss"):
        # Razonamiento corto: respuestas más rápidas y menos tokens gastados.
        kwargs["reasoning_effort"] = "low"
        kwargs["include_reasoning"] = False
    try:
        response = _groq_client().chat.completions.create(**kwargs)
    except groq.RateLimitError as exc:
        raise RateLimited(str(exc)) from exc
    return response.choices[0].message.content


def _call_gemini(model, system, messages, temperature, max_tokens):
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        # Los modelos Gemini 3 trabajan mejor con su temperatura por defecto,
        # así que aquí solo se fija el formato y el largo.
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens},
    }
    response = httpx.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": settings.GEMINI_API_KEY},
        json=body,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        raise RateLimited(response.text[:300])
    response.raise_for_status()
    data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


PROVIDERS = {
    "groq": (_call_groq, "GROQ_API_KEY"),
    "gemini": (_call_gemini, "GEMINI_API_KEY"),
}


def complete_json(system, messages, temperature=0.4, max_tokens=1500):
    """
    Pide una respuesta en JSON y devuelve (dict, "proveedor:modelo").

    messages: lista de {"role": "user"|"assistant", "content": str}.
    """
    errors = []
    for entry in settings.LLM_CHAIN:
        provider, _, model = entry.partition(":")
        if provider not in PROVIDERS or not model:
            errors.append(f"{entry}: formato inválido")
            continue
        call, key_name = PROVIDERS[provider]
        if not getattr(settings, key_name, ""):
            errors.append(f"{entry}: falta {key_name}")
            continue
        try:
            text = call(model, system, messages, temperature, max_tokens)
            return parse_json(text), entry
        except RateLimited:
            errors.append(f"{entry}: sin cuota disponible")
            logger.warning("Cuota agotada en %s, probando el siguiente modelo", entry)
        except Exception as exc:  # noqa: BLE001 - cualquier falla pasa al siguiente modelo
            errors.append(f"{entry}: {type(exc).__name__}: {str(exc)[:200]}")
            logger.warning("Falló %s: %s", entry, exc)
    raise LLMError("; ".join(errors) or "LLM_CHAIN está vacía")


# Frases que Whisper "inventa" cuando el audio trae silencio o ruido: las aprendió de
# subtítulos de videos. Nadie las dice en una entrevista, así que se eliminan.
_HALLUCINATIONS = re.compile(
    r"[¡¿(\[]*\s*(?:"
    r"subt[ií]tul(?:os|ado)[^.!\n]*(?:amara\.org|comunidad|por\b[^.!\n]*)"
    r"|transcrip(?:ción|cion) (?:realizada )?por[^.!\n]*"
    r"|(?:muchas )?gracias por (?:ver|mirar)(?: el v[ií]deo| este v[ií]deo)?"
    r"|no olvides suscribirte[^.!\n]*|suscr[ií]bete(?: al canal)?[^.!\n]*"
    r"|dale (?:a )?like[^.!\n]*"
    r"|m[uú]sica(?: de fondo)?|♪+"
    r")\s*[.!)\]]*",
    re.IGNORECASE,
)

# Valores de referencia de Whisper para detectar segmentos que no son voz.
NO_SPEECH_PROB = 0.6
MIN_AVG_LOGPROB = -1.0
MAX_COMPRESSION_RATIO = 2.4   # más alto = texto repetido en bucle


def clean_transcript(text):
    """Quita frases inventadas y deja vacío si solo queda puntuación."""
    text = _HALLUCINATIONS.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if re.search(r"\w", text) else ""


def _transcript_text(result):
    """Arma el texto con los segmentos que sí parecen voz (respuesta verbose_json)."""
    if isinstance(result, str):
        return result
    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    segments = data.get("segments")
    if not segments:
        return data.get("text", "")
    kept = []
    for seg in segments:
        silent = (seg.get("no_speech_prob", 0) > NO_SPEECH_PROB
                  and seg.get("avg_logprob", 0) < MIN_AVG_LOGPROB)
        looping = seg.get("compression_ratio", 0) > MAX_COMPRESSION_RATIO
        if not silent and not looping:
            kept.append(seg.get("text", "").strip())
    return " ".join(kept)


def transcribe(audio_bytes, filename, mime, prompt=""):
    """Transcribe audio en español con Whisper de Groq.

    Prueba los modelos de settings.WHISPER_MODELS en orden: si uno no tiene cuota o
    el servicio falla, pasa al siguiente. Si todos están sin cuota lanza RateLimited.
    """
    import groq

    if not settings.GROQ_API_KEY:
        raise LLMError("falta GROQ_API_KEY")
    client = groq.Groq(api_key=settings.GROQ_API_KEY, timeout=30, max_retries=0)
    errors, all_limited = [], True
    for model in settings.WHISPER_MODELS:
        try:
            result = client.audio.transcriptions.create(
                model=model,
                file=(filename, audio_bytes, mime),
                language="es",
                temperature=0,
                prompt=prompt[:600],   # Whisper solo toma unos 224 tokens de contexto
                response_format="verbose_json",
            )
        except groq.RateLimitError as exc:
            errors.append(f"{model}: sin cuota")
            logger.warning("Cuota de audio agotada en %s: %s", model, exc)
            continue
        except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as exc:
            all_limited = False
            errors.append(f"{model}: {type(exc).__name__}")
            logger.warning("Falló la transcripción con %s: %s", model, exc)
            continue
        return clean_transcript(_transcript_text(result))
    if errors and all_limited:
        raise RateLimited("; ".join(errors))
    raise LLMError("; ".join(errors) or "WHISPER_MODELS está vacía")
