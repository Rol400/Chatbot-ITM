from django.db import migrations


def scale_scores(apps, schema_editor):
    """Las calificaciones pasaron de escala 0-10 a 0-100."""
    PracticeSession = apps.get_model("chatbot", "PracticeSession")
    for session in PracticeSession.objects.filter(score__isnull=False, score__lte=10):
        session.score = round(session.score * 10)
        session.save(update_fields=["score"])


class Migration(migrations.Migration):
    dependencies = [("chatbot", "0005_simulador")]
    operations = [migrations.RunPython(scale_scores, migrations.RunPython.noop)]
