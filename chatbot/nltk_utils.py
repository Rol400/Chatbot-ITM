"""
Preprocesamiento de texto en español para el modelo de intenciones.

Se usa igual al entrenar (train.py) y al predecir (intents.py), así que
cualquier cambio aquí obliga a reentrenar el modelo.
"""
import re
import unicodedata

import numpy as np
from nltk.stem.snowball import SnowballStemmer

_stemmer = SnowballStemmer("spanish")


def normalize(text):
    """Minúsculas y sin acentos: 'Gramática' -> 'gramatica'."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def tokenize(sentence):
    """Separa en palabras: '¿Cómo funciona?' -> ['como', 'funciona']."""
    return re.findall(r"[a-z0-9]+", normalize(sentence))


def stem(word):
    """Raíz de la palabra: 'corrigiendo', 'corregir' -> 'corrig'."""
    return _stemmer.stem(word)


def bag_of_words(tokens, vocabulary):
    """
    Vector de 0 y 1 con una posición por palabra del vocabulario.
    tokens: palabras ya tokenizadas (sin raíz).
    vocabulary: lista de raíces conocidas.
    """
    stems = {stem(t) for t in tokens}
    return np.array([1.0 if w in stems else 0.0 for w in vocabulary], dtype=np.float32)
