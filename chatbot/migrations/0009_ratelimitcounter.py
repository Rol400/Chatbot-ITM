from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('chatbot', '0008_etiqueta_expresion')]
    operations = [migrations.CreateModel(
        name='RateLimitCounter',
        fields=[('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('count', models.PositiveIntegerField(default=0)),
                ('expires_at', models.DateTimeField(db_index=True))],
    )]
