# Revisión de seguridad y rendimiento

Fecha: 29 de octubre de 2026.
Base: proyecto chatbot_v5 con la nueva portada integrada.

## Resultado

Se detectaron y corrigieron fallos en los límites de uso, el bloqueo de acceso
y la validación de las peticiones. La revisión incluye lectura del código,
pruebas locales, análisis estático y consulta de vulnerabilidades de dependencias.
No constituye una prueba de penetración del servicio publicado.

## Hallazgos corregidos

| Prioridad | Hallazgo y evidencia | Corrección |
|---|---|---|
| Alta | `client_ip()` aceptaba el primer valor de `X-Forwarded-For` de cualquier cliente. La prueba local reprodujo la suplantación de IP para las cuotas de registro, recuperación e inicio de sesión. | Solo se aceptan cabeceras procedentes de `TRUSTED_PROXY_CIDRS`; la cadena se recorre desde la derecha hasta el primer salto no fiable. |
| Alta | Los contadores usaban `DatabaseCache.incr()`: la implementación de Django realiza lectura y escritura separadas, y vuelve a aplicar el vencimiento predeterminado de 300 segundos. Las cuotas diarias y el bloqueo de 15 minutos podían perder su duración. Un único proceso con cuatro hilos no elimina esa carrera. | Tabla `RateLimitCounter` con expiración fija, transacción, bloqueo de fila e incremento con `F()`. Limpieza amortizada de claves vencidas y claves almacenadas como hash. Migración `0009`. |
| Media | El bloqueo por cuenta trataba el nombre y el correo como identidades independientes. Tras bloquear el nombre, una petición desde otra IP con el correo aún podía autenticar. Reproducido por prueba de regresión. | Las dos formas de acceso comparten una clave basada en el identificador de usuario. |
| Alta | El formulario de acceso de Django Admin no pasaba por el bloqueo del formulario principal. | Un `AdminSite` propio aplica los mismos contadores al acceso administrativo; se comprueban el bloqueo y el acceso válido. |
| Media | Un JSON que contiene una lista, `null`, una cadena, un número como texto de respuesta, o un número de preguntas no numérico producía errores 500. | Validación del objeto, tipos, tamaño, profundidad, booleanos y números finitos; respuesta 400 sin llamar al proveedor. |
| Media | `DEBUG` se activaba por defecto y, sin clave configurada, había una clave de desarrollo constante. | `DEBUG=False` por defecto; la clave sigue siendo obligatoria en producción y se genera al vuelo solo en desarrollo. |
| Baja | Los rangos abiertos de paquetes no permitían reproducir exactamente la instalación revisada y todavía admitían Django 4.2. | Restricciones en `requirements.lock` para 45 paquetes de ejecución; mínimo Django 5.2.18 y Python 3.12. |
| Rendimiento | La lista de actividad de «Mi progreso» consultaba los mensajes de cada sesión de expresión por separado. | `Prefetch` filtrado. Una prueba comprueba que las consultas no crecen al pasar de una a seis sesiones recientes. |

También se ampliaron las exclusiones de Git para archivos `.env.*`, bases SQLite,
archivos auxiliares de SQLite y registros. `.env.example` continúa incluido.

## Validación

- Las 42 pruebas originales pasaron antes de modificar el proyecto.
- Se añadieron pruebas de regresión de los fallos descritos, aislamiento de
  reportes/ejercicios por propietario, vencimiento de cuotas y consultas de progreso.
- Resultado final: 55 pruebas locales satisfactorias con SQLite y Python 3.12.
- `makemigrations --check --dry-run`: sin cambios de modelos pendientes.
- `collectstatic` con configuración de producción: satisfactorio, incluido el CSS
  y JavaScript de la portada.
- `pip-audit`: 45 dependencias de ejecución, cero vulnerabilidades conocidas
  reportadas en la consulta del 29 de octubre de 2026. Esto describe las versiones
  fijadas, no otras instalaciones previas ni vulnerabilidades aún no publicadas.
- Bandit: las advertencias bajas restantes corresponden a `random.choice()` para
  frases/temas de ejercicios y a contraseñas ficticias en pruebas. No se usan para
  generar credenciales ni tokens. No se detectaron resultados de severidad media/alta.
- `check --deploy`: permanecen los avisos W005 y W021 relativos a HSTS en subdominios
  y precarga. Su activación requiere conocer el dominio y sus subdominios; no se
  habilitaron indiscriminadamente.
- La búsqueda de patrones comunes de secretos no encontró claves reales en los
  archivos del proyecto. No se revisó el historial del repositorio, que no fue proporcionado.

## Antes de desplegar esta copia

1. Instalar con `pip install -r requirements.txt` y ejecutar `python manage.py migrate`.
   En Render, `build.sh` ya ejecuta ambas operaciones. La migración añade una tabla;
   no modifica las sesiones existentes.
2. Configurar `TRUSTED_PROXY_CIDRS` según los proxies reales y comprobar las IP que
   llegan al servidor. Vacío usa la IP de conexión: detrás de un proxy puede agrupar
   a muchos usuarios bajo el mismo límite. No confiar en todas las redes.
3. Mantener `DEBUG=False`, `SECRET_KEY` propia, dominios correctos, HTTPS y secretos
   exclusivamente en variables de entorno. Revisar también los archivos que se hayan
   subido antes al repositorio: `.gitignore` no elimina secretos del historial.
4. Actualizar el Python 3.12.7 fijado en `render.yaml` a un parche compatible y mantenido
   disponible en Render. El instalador incluye asimismo Python 3.12.10 como respaldo;
   conviene actualizar el intérprete mediante el proveedor oficial.

## Riesgos y mejoras pendientes

- **Concurrencia de entrevistas:** dos pestañas o peticiones simultáneas pueden avanzar
  o evaluar la misma sesión a la vez. Los contadores de cuota ya son transaccionales,
  pero la entrevista todavía requiere serialización por sesión o idempotencia. Las
  operaciones de esta revisión no deben confundirse con una corrección de ese flujo.
- **Llamadas lentas al modelo:** tres proveedores con 40 segundos por intento, un
  posible reintento de evaluación y Whisper con reintentos pueden exceder los 120
  segundos de Gunicorn. Añadir un presupuesto global por petición o una cola de
  trabajos antes de soportar tráfico importante.
- **PDF no confiables:** limitar el CV a 5 MB y cuatro páginas no limita de forma
  estricta el trabajo de descompresión y análisis. Para apertura al público se
  recomienda aislar la extracción con límites de tiempo/memoria, o admitir solo texto.
- **Solicitudes concurrentes de registro:** la comprobación de disponibilidad y la
  creación de cuenta siguen siendo pasos separados; conviene resolver conflictos de
  integridad y unicidad de correo a nivel de esquema/formulario de registro.
- **Progreso e historial:** las estadísticas aún cargan el conjunto de mensajes del
  periodo y el estado de entrevista lee su historial. Si crece el uso, medir y después
  agregar paginación, agregados e índices según los planes de consulta reales.
- **Modelo de lenguaje:** los filtros de formato y de papel reducen errores, pero
  no garantizan resistencia a todas las instrucciones maliciosas ni la exactitud
  de las calificaciones. Ninguna salida debe conceder permisos o ejecutar código.

No se probaron el proxy de Render, PostgreSQL bajo concurrencia, el micrófono,
Google OAuth, Brevo ni las API reales de Groq/Gemini. No se enviaron correos,
se publicaron cambios ni se usaron credenciales del usuario.

## Referencias técnicas

- Django, atomicidad de contadores de caché: https://code.djangoproject.com/ticket/23326
- Django, vencimiento en `DatabaseCache.incr()`: https://code.djangoproject.com/ticket/36610
- MDN, confianza y recorrido de `X-Forwarded-For`: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Forwarded-For
- Django, lista de despliegue: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

El documento académico Word no forma parte de los cambios de esta revisión.
