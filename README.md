# Práctica de entrevistas y español

Página en Django para practicar entrevistas de trabajo y corregir la escritura en español, por texto o por voz.

## Pantallas

- **Inicio** (`/`): presentación, con los logos del Instituto Tecnológico de Mérida y de Ingeniería en Sistemas Computacionales.
- **Entrevista** (`/entrevista`): preparación (puesto, nivel, tipo, número de preguntas, vacante y CV opcionales) y luego el simulador: una pregunta a la vez, respuesta por voz o texto, retroalimentación con puntaje de 0 a 100, "Responder de nuevo", "Otra pregunta" y "Siguiente pregunta".
- **Reporte** (`/reporte/<id>`): calificación final, punto débil, fortalezas, cada pregunta con tu respuesta y su mejora, "Practicar las 2 más bajas" y descarga en PDF (imprimir).
- **Expresión** (`/gramatica`): editor donde los errores se subrayan por tipo; al tocarlos se ve la regla y se aplica la corrección. Después de revisar aparece **Tu plan de práctica** con ejercicios para cada criterio bajo:
  - Muletillas: encontrarlas en tu texto y hablar un minuto con pausas en silencio.
  - Ortografía y acentos: mira, cubre, escribe y compara, con repasos mañana, en 3 y en 7 días.
  - Gramática, puntuación y claridad: oraciones nuevas con tu mismo error, unir oraciones y resumir en una oración.
  Cada ejercicio muestra en qué estudios se basa (`chatbot/practice.py`).
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

Usa Python 3.12 o superior. Las dependencias de ejecución se fijan mediante
`requirements.lock`, que `requirements.txt` aplica como restricciones.

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

## Cambios de la revisión de seguridad

Antes de arrancar una instalación existente, ejecuta `python manage.py migrate`:
la migración `0009` crea los contadores persistentes de intentos y cuotas.
No depende de la caché para conservar su vencimiento o incrementar sus valores.

`DEBUG` queda desactivado si no se configura; para desarrollo local copia
`.env.example`, donde está activado. En producción configura una `SECRET_KEY`
propia y conserva `DEBUG=False`.

`TRUSTED_PROXY_CIDRS` acepta las IP o redes de los proxies de tu despliegue.
Vacío, ignora `X-Forwarded-For` y usa la IP de conexión. Detrás de Render u otro
proxy, identifica y configura las redes fiables antes de abrir el servicio:
de lo contrario varios usuarios podrían compartir el límite de una misma IP.
No uses `0.0.0.0/0` ni `::/0`. Confirma que el proxy agrega o reemplaza correctamente
las cabeceras y que el servidor no admite acceso directo fuera de ese proxy.

Consulta `AUDITORIA.md` para los resultados, las limitaciones y los pendientes.

## Cambiar de modelo

Todo se configura en `.env`, sin tocar código:

```
LLM_CHAIN=groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite
WHISPER_MODEL=whisper-large-v3-turbo
```

Revisa de vez en cuando https://console.groq.com/docs/deprecations para saber si Groq va a retirar algún modelo.

## Publicar en línea (GitHub + Render + Neon)

1. **Neon** (https://neon.tech): crea un proyecto, región *US East*. Copia la *connection string* (`postgresql://...?sslmode=require`).
2. **GitHub**: sube el proyecto a un repositorio privado (sin `.env` ni `db.sqlite3`).
3. **Render** (https://render.com): *New → Blueprint*, elige el repositorio. Render lee `render.yaml` y te pide:
   - `DATABASE_URL`: la de Neon.
   - `GROQ_API_KEY` (y `GEMINI_API_KEY` si tienes).
   `SECRET_KEY` se genera sola. Cada `push` a GitHub vuelve a publicar la página.
4. **Que no se duerma**: en https://cron-job.org crea una tarea que visite `https://TU-APP.onrender.com/salud` cada 10 minutos.
   Usa solo un servicio gratis en Render: las 750 horas al mes alcanzan para uno encendido todo el mes.
5. Para crear un administrador: en Render, pestaña *Shell*, `python manage.py createsuperuser` (en el plan gratis puede no estar; entonces ejecútalo en tu laptop con `DATABASE_URL` de Neon en tu `.env`).

## Iniciar sesión con Google

1. https://console.cloud.google.com → crea un proyecto.
2. *APIs y servicios → Pantalla de consentimiento de OAuth*: tipo **Externo**, nombre de la app, tu correo. Permisos: solo `email` y `profile`. Publica la app (con esos permisos no pide verificación).
3. *Credenciales → Crear credenciales → ID de cliente de OAuth* → **Aplicación web**.
   - Orígenes autorizados: `https://TU-APP.onrender.com` y `http://localhost:8000`
   - URI de redireccionamiento: `https://TU-APP.onrender.com/cuentas/google/login/callback/` y `http://localhost:8000/cuentas/google/login/callback/`
4. Copia el ID y el secreto en `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` (Render y `.env`). Sin ellas, el botón no aparece.

## Seguridad

- Contraseñas con Argon2 (las viejas se actualizan al iniciar sesión); mínimo 10 caracteres. Con Google no se guarda contraseña ni tokens.
- 5 intentos fallidos bloquean 15 minutos (por usuario y por red); máximo 5 cuentas nuevas por hora desde la misma red.
- HTTPS obligatorio, HSTS, cookies seguras, sin iframes, CSRF en todos los formularios.
- El CV subido solo se usa para el resumen; no se guarda.
- Cada usuario puede borrar su cuenta y todos sus datos desde su menú.
- Pon `ADMIN_URL` con una dirección difícil de adivinar.
- Neon: la conexión va cifrada (`sslmode=require`). La contraseña solo vive en Render y en tu `.env`. Si sospechas algo, en Neon *Roles → Reset password* y actualiza `DATABASE_URL`.

## Recuperar contraseña (Brevo)

Render gratis bloquea el correo por SMTP, así que se envía con la API de Brevo (gratis, sin tarjeta).

1. Crea una cuenta en https://www.brevo.com.
2. *Senders, Domains & Dedicated IPs → Senders → Add a sender*: tu correo (puede ser Gmail) y confirma el mensaje que te llega.
3. *SMTP & API → API Keys → Generate a new API key*.
4. En Render (y en tu `.env` si quieres probar en la laptop): `BREVO_API_KEY`, `EMAIL_FROM` (el remitente verificado) y `EMAIL_FROM_NAME`.

Sin `BREVO_API_KEY`, el correo se imprime en la consola (útil para probar). El enlace vence en 1 hora y se pueden pedir 5 por hora desde la misma red.

## Antes de publicar

- `DEBUG=False`, `ALLOWED_HOSTS` con tu dominio y `CSRF_TRUSTED_ORIGINS` con `https://tu-dominio`.
- `python manage.py collectstatic`.
- El micrófono del navegador requiere HTTPS (en `localhost` funciona sin él).
- No subas `.env` ni `db.sqlite3` a GitHub (ya están en `.gitignore`).
