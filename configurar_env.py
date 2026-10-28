"""
Crea o actualiza el archivo .env con tus llaves.
Lo ejecuta instalar.bat, pero también puedes correrlo solo:  python configurar_env.py
"""
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def get_value(text, key):
    match = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def set_value(text, key, value):
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, re.MULTILINE):
        return re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.MULTILINE)
    return text.rstrip("\n") + "\n" + line + "\n"


def ask(prompt):
    try:
        return input(prompt).strip().strip('"').strip("'")
    except EOFError:
        return ""


def main():
    text = read(ENV_FILE) or read(EXAMPLE_FILE)

    if not get_value(text, "SECRET_KEY"):
        text = set_value(text, "SECRET_KEY", secrets.token_urlsafe(50))

    print()
    groq = get_value(text, "GROQ_API_KEY")
    change = True
    if groq:
        change = ask("Ya hay una llave de Groq guardada. ¿Quieres cambiarla? (s/N): ").lower() in ("s", "si", "sí")
    if change:
        print("Crea tu llave en https://console.groq.com/keys (botón 'Create API Key') y pégala aquí.")
        while True:
            groq = ask("Llave de Groq: ")
            if groq:
                break
            print("La llave de Groq es necesaria para que el chat funcione.")
        if not groq.startswith("gsk_"):
            print("Aviso: las llaves de Groq suelen empezar con 'gsk_'. Revisa que la hayas copiado completa.")
        text = set_value(text, "GROQ_API_KEY", groq)

    if not get_value(text, "GEMINI_API_KEY"):
        print()
        print("Opcional: llave de Gemini como respaldo (https://aistudio.google.com/apikey).")
        gemini = ask("Llave de Gemini (deja vacío y presiona Enter para omitir): ")
        if gemini:
            text = set_value(text, "GEMINI_API_KEY", gemini)

    ENV_FILE.write_text(text, encoding="utf-8")
    print()
    print("Listo: tus llaves quedaron guardadas en el archivo .env")


if __name__ == "__main__":
    main()
