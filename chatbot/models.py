from django.contrib.auth.models import User
from django.db import models


class PracticeSession(models.Model):
    """Una sesión de práctica: una entrevista completa o un día de revisión de textos."""

    INTERVIEW = "interview"
    GRAMMAR = "grammar"
    MODES = [(INTERVIEW, "Entrevista"), (GRAMMAR, "Gramática")]

    LEVELS = [("practicante", "Practicante o residente"), ("junior", "Recién egresado"),
              ("experiencia", "Con experiencia")]
    TYPES = [("general", "General"), ("tecnica", "Técnica"), ("mixta", "Mixta")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="practice_sessions")
    mode = models.CharField(max_length=20, choices=MODES)

    # Preparación de la entrevista
    role = models.CharField("puesto", max_length=200, blank=True)
    level = models.CharField(max_length=20, choices=LEVELS, default="junior")
    interview_type = models.CharField(max_length=20, choices=TYPES, default="mixta")
    answer_mode = models.CharField(max_length=10, default="voice")
    job_description = models.TextField(blank=True)
    cv_text = models.TextField(blank=True)
    context_summary = models.TextField(blank=True)
    planned_questions = models.JSONField(default=list, blank=True)

    # Avance
    current_question = models.TextField(blank=True)
    current_question_type = models.CharField(max_length=40, blank=True)
    pending_question = models.TextField(blank=True)
    pending_question_type = models.CharField(max_length=40, blank=True)
    questions_asked = models.PositiveIntegerField(default=0)
    total_questions = models.PositiveIntegerField(default=8)
    finished = models.BooleanField(default=False)
    score = models.FloatField("calificación de 0 a 100", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.username} · {self.get_mode_display()} · {self.created_at:%Y-%m-%d %H:%M}"


class Message(models.Model):
    USER = "user"
    BOT = "bot"
    SENDERS = [(USER, "Usuario"), (BOT, "Asistente")]

    TEXT = "text"
    QUESTION = "question"        # pregunta de la entrevista
    FEEDBACK = "feedback"        # evaluación de una respuesta
    CORRECTION = "correction"    # revisión de un texto
    SUMMARY = "summary"          # calificación final
    NOTICE = "notice"            # avisos del sistema
    KINDS = [(TEXT, "Texto"), (QUESTION, "Pregunta"), (FEEDBACK, "Retroalimentación"),
             (CORRECTION, "Corrección"), (SUMMARY, "Resumen"), (NOTICE, "Aviso")]

    session = models.ForeignKey(PracticeSession, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=10, choices=SENDERS)
    kind = models.CharField(max_length=20, choices=KINDS, default=TEXT)
    text = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.sender}: {self.text[:60]}"
