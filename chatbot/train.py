"""
Entrena el modelo propio de intenciones con PyTorch.

Uso (desde la carpeta donde está manage.py):
    pip install -r requirements-dev.txt
    python chatbot/train.py

Lee intents.json y genera chatbot/intent_model.json, que es lo que usa la
página. El servidor no necesita PyTorch: la predicción se hace con numpy.
"""
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from model import NeuralNet
from nltk_utils import bag_of_words, stem, tokenize

HERE = Path(__file__).resolve().parent
INTENTS_FILE = HERE.parent / "intents.json"
OUTPUT_FILE = HERE / "intent_model.json"

HIDDEN_SIZE = 32
EPOCHS = 400
BATCH_SIZE = 16
LEARNING_RATE = 0.005
SEED = 42

# Frases que no están en intents.json, para comprobar que el modelo generaliza.
CHECKS = [
    ("cambiame a entrevista por favor", "cambiar_entrevista"),
    ("quiero que revises mi ortografia", "cambiar_gramatica"),
    ("empecemos otra vez", "reiniciar"),
    ("ya quiero mi calificacion", "terminar"),
    ("hola buenas tardes", "saludo"),
    ("gracias de verdad", "agradecimiento"),
    ("nos vemos mañana", "despedida"),
    ("como uso esta pagina", "ayuda"),
    ("ingeniero en sistemas", "otro"),
    ("dame otra pista", "otro"),
    ("haiga muchos problemas", "otro"),
]


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    with open(INTENTS_FILE, encoding="utf-8") as f:
        intents = json.load(f)["intents"]

    tags = sorted({intent["tag"] for intent in intents})
    samples = [(tokenize(p), intent["tag"]) for intent in intents for p in intent["patterns"]]
    all_words = sorted({stem(w) for tokens, _ in samples for w in tokens})

    x = np.array([bag_of_words(tokens, all_words) for tokens, _ in samples], dtype=np.float32)
    y = np.array([tags.index(tag) for _, tag in samples], dtype=np.int64)
    print(f"{len(samples)} frases, {len(tags)} intenciones, {len(all_words)} palabras en el vocabulario")

    loader = DataLoader(TensorDataset(torch.from_numpy(x), torch.from_numpy(y)),
                        batch_size=BATCH_SIZE, shuffle=True)
    model = NeuralNet(len(all_words), HIDDEN_SIZE, len(tags))
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)

    for epoch in range(EPOCHS):
        model.train()
        for features, labels in loader:
            loss = criterion(model(features), labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        if (epoch + 1) % 100 == 0:
            print(f"Época {epoch + 1}/{EPOCHS}, pérdida: {loss.item():.4f}")

    model.eval()
    with torch.no_grad():
        accuracy = (model(torch.from_numpy(x)).argmax(1).numpy() == y).mean()
        print(f"Precisión con las frases de entrenamiento: {accuracy:.1%}")
        print("\nPrueba con frases nuevas:")
        hits = 0
        for sentence, expected in CHECKS:
            probs = torch.softmax(model(torch.from_numpy(bag_of_words(tokenize(sentence), all_words))), 0)
            best = int(probs.argmax())
            ok = tags[best] == expected
            hits += ok
            print(f"  {'OK' if ok else 'X '} {sentence!r} -> {tags[best]} ({probs[best]:.0%}), esperado {expected}")
        print(f"  {hits}/{len(CHECKS)} correctas")

    layers = [{"weight": layer.weight.detach().numpy().round(6).tolist(),
               "bias": layer.bias.detach().numpy().round(6).tolist()}
              for layer in (model.l1, model.l2, model.l3)]
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"all_words": all_words, "tags": tags, "hidden_size": HIDDEN_SIZE, "layers": layers}, f)
    print(f"\nModelo guardado en {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
