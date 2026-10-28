"""Red neuronal del modelo de intenciones (solo se usa al entrenar con PyTorch)."""
import torch.nn as nn


class NeuralNet(nn.Module):
    def __init__(self, input_size, hidden_size, num_classes):
        super().__init__()
        self.l1 = nn.Linear(input_size, hidden_size)
        self.l2 = nn.Linear(hidden_size, hidden_size)
        self.l3 = nn.Linear(hidden_size, num_classes)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.2)

    def forward(self, x):
        out = self.dropout(self.relu(self.l1(x)))
        out = self.dropout(self.relu(self.l2(out)))
        return self.l3(out)  # sin softmax: CrossEntropyLoss ya lo incluye
