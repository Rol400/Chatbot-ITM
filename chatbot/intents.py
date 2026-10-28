"""
Modelo propio de intenciones (inferencia).

La red se entrena con PyTorch en train.py y se exporta a intent_model.json.
Aquí se ejecuta con numpy, así que el servidor no necesita PyTorch.

Solo se usa con mensajes cortos: decide si el usuario está dando un comando
(cambiar de modo, reiniciar, terminar, saludar...) o si el mensaje es contenido
que debe ir al modelo de lenguaje (una respuesta de entrevista, un texto a corregir).
"""
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .nltk_utils import bag_of_words, tokenize

logger = logging.getLogger("chatbot")

MODEL_PATH = Path(__file__).resolve().parent / "intent_model.json"
MAX_WORDS = 8            # mensajes más largos se consideran contenido
MIN_CONFIDENCE = 0.80    # por debajo de esto no se actúa
CONTENT_TAG = "otro"


@dataclass
class Intent:
    tag: str
    confidence: float


class IntentClassifier:
    def __init__(self, path=MODEL_PATH):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.vocabulary = data["all_words"]
        self.tags = data["tags"]
        self.layers = [(np.array(layer["weight"], dtype=np.float32), np.array(layer["bias"], dtype=np.float32))
                       for layer in data["layers"]]

    def probabilities(self, text):
        x = bag_of_words(tokenize(text), self.vocabulary)
        for i, (weight, bias) in enumerate(self.layers):
            x = weight @ x + bias
            if i < len(self.layers) - 1:
                x = np.maximum(x, 0)  # ReLU
        exp = np.exp(x - x.max())
        return exp / exp.sum()

    def predict(self, text):
        probs = self.probabilities(text)
        best = int(np.argmax(probs))
        return Intent(self.tags[best], float(probs[best]))

    def classify(self, text):
        """Devuelve un Intent si el mensaje es claramente un comando, si no None."""
        tokens = tokenize(text)
        if not tokens or len(tokens) > MAX_WORDS:
            return None
        if not bag_of_words(tokens, self.vocabulary).any():
            return None  # ninguna palabra conocida
        intent = self.predict(text)
        if intent.tag == CONTENT_TAG or intent.confidence < MIN_CONFIDENCE:
            return None
        return intent


@lru_cache(maxsize=1)
def get_classifier():
    try:
        return IntentClassifier()
    except FileNotFoundError:
        logger.warning("No existe %s; corre python chatbot/train.py", MODEL_PATH.name)
        return None


def classify(text):
    classifier = get_classifier()
    return classifier.classify(text) if classifier else None
