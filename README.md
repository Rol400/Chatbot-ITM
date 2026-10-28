# Práctica de entrevistas y español

Página en Django para practicar entrevistas de trabajo y corregir la escritura en español, por texto o por voz.

## Pantallas

- **Inicio** (`/`): presentación, con los logos del Instituto Tecnológico de Mérida y de Ingeniería en Sistemas Computacionales.
- **Entrevista** (`/entrevista`): preparación (puesto, nivel, tipo, número de preguntas, vacante y CV opcionales) y luego el simulador: una pregunta a la vez, respuesta por voz o texto, retroalimentación con puntaje de 0 a 100, "Responder de nuevo", "Otra pregunta" y "Siguiente pregunta".
- **Reporte** (`/reporte/<id>`): calificación final, punto débil, fortalezas, cada pregunta con tu respuesta y su mejora, "Practicar las 2 más bajas" y descarga en PDF (imprimir).
- **Gramática** (`/gramatica`): editor donde los errores se subrayan por tipo; al tocarlos se ve la regla y se aplica la corrección. Incluye ejercicios de escritura profesional.
- **Mi progreso** (`/progreso`): promedios con tendencia, gráfica de entrevistas, sesiones recientes, errores y muletillas más repetidos.

## Cómo funciona

| Parte | Qué hace | Archivo |
|---|---|---|
| Modelo propio de intenciones | Red neuronal entrenada con `intents.json`. Detecta comandos cortos (cambiar de modo, reiniciar, terminar, saludar, despedirse, agradecer, pedir ayuda) y los responde sin usar la API. | `chatbot/train.py`, `chatbot/intents.py` |
| Modelo de lenguaje | Genera las preguntas, evalúa respuestas, corrige textos y hace el resumen final, siempre en JSON. Usa Groq `openai/gpt-oss-120b`; si falla o se acaba la cuota pasa a `openai/gpt-oss-20b` y luego a Gemini Flash-Lite. | `chatbot/llm.py`, `chatbot/prompts.py` |
| Entrevista | La siguiente pregunta se genera junto con la evaluación y se guarda, así "Siguiente pregunta" no gasta otra llamada. Detecta respuestas sin sentido y vuelve a pedir la evaluación si el modelo se sale del papel de entrevistador. | `chatbot/interview.py` |
| Gramática y progreso | Ubica cada error en el texto original, calcula el puntaje y arma las estadísticas. | `chatbot/grammar.py`, `chatbot/progress.py` |
| Voz | Dictado del navegador (opcionalmente en el dispositivo, Chrome 139+). Si falla, graba el audio y lo transcribe Whisper `large-v3-turbo` en Groq. Las preguntas se leen en voz alta con la voz del navegador. | `static/ui/voice.js`, `static/ui/common.js` |

## Instalación rápida (Windows, doble clic)

1. Descomprime el proyecto (clic derecho → *Extraer todo*).
2. Haz doble clic en **`instalar.bat`**. Instala Python si no lo tienes, los paquetes y la base de datos, y te pide tu llave de Groq.
3. Los siguientes días abre la página con **`iniciar.bat`**. Para apagarla, cierra la ventana negra.

Si Windows muestra "Windows protegió tu PC", elige *Más información* → *Ejecutar de todas formas*.

## Instalación manual (Windows)

Desde la carpeta donde está `manage.py`:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Abre `.env` y llena:

- `SECRET_KEY`: genera una con `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `GROQ_API_KEY`: en https://console.groq.com/keys
- `GEMINI_API_KEY` (respaldo, opcional): en https://aistudio.google.com/apikey

Luego:

```bat
python manage.py migrate
python manage.py runserver
```

Abre http://127.0.0.1:8000

> `migrate` reemplaza la tabla vieja `Chat` por las nuevas `PracticeSession` y `Message`. Las cuentas de usuario se conservan; los mensajes viejos no.

## Reentrenar el modelo de intenciones

1. Edita `intents.json`. Agrega frases a la intención que quieras; si algo se detecta como comando cuando no debería, agrégalo a `otro`.
2. Entrena:

```bat
pip install -r requirements-dev.txt
python chatbot\train.py
```

El script muestra la precisión y prueba frases nuevas. Genera `chatbot/intent_model.json`, que es lo único que necesita la página: en el servidor la predicción se hace con numpy, sin PyTorch.

Reglas de uso del modelo: solo actúa con mensajes de 8 palabras o menos y cuando su confianza es de al menos 80 %. Los valores están en `chatbot/intents.py`.

## Pruebas

```bat
python manage.py test chatbot
```

No llaman a ninguna API: el modelo de lenguaje se simula.

## Cambiar de modelo

Todo se configura en `.env`, sin tocar código:

```
LLM_CHAIN=groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite
WHISPER_MODEL=whisper-large-v3-turbo
```

Revisa de vez en cuando https://console.groq.com/docs/deprecations para saber si Groq va a retirar algún modelo.

## Antes de publicar

- `DEBUG=False`, `ALLOWED_HOSTS` con tu dominio y `CSRF_TRUSTED_ORIGINS` con `https://tu-dominio`.
- `python manage.py collectstatic`.
- El micrófono del navegador requiere HTTPS (en `localhost` funciona sin él).
- No subas `.env` ni `db.sqlite3` a GitHub (ya están en `.gitignore`).
