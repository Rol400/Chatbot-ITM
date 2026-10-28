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


def transcribe(audio_bytes, filename, mime, prompt=""):
    """Transcribe audio en español con Whisper de Groq."""
    from groq import Groq

    if not settings.GROQ_API_KEY:
        raise LLMError("falta GROQ_API_KEY")
    client = Groq(api_key=settings.GROQ_API_KEY, timeout=60, max_retries=1)
    result = client.audio.transcriptions.create(
        model=settings.WHISPER_MODEL,
        file=(filename, audio_bytes, mime),
        language="es",
        temperature=0,
        prompt=prompt[:800],
        response_format="text",
    )
    return (result if isinstance(result, str) else result.text).strip()
