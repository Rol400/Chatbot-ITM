"""Límites con vencimiento fijo e incrementos atómicos en la base de datos."""
import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import RateLimitCounter


def _key(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def count(key):
    return (RateLimitCounter.objects.filter(pk=_key(key), expires_at__gt=timezone.now())
            .values_list('count', flat=True).first()) or 0


def clear(key):
    RateLimitCounter.objects.filter(pk=_key(key)).delete()


def hit(key, ttl):
    now = timezone.now()
    # Limpieza amortizada: también evita acumular claves de ventanas anteriores.
    if secrets.randbelow(256) == 0:
        RateLimitCounter.objects.filter(expires_at__lte=now).delete()
    with transaction.atomic():
        counter, _ = RateLimitCounter.objects.select_for_update().get_or_create(
            pk=_key(key), defaults={'expires_at': now + timedelta(seconds=ttl)})
        if counter.expires_at <= now:
            counter.count = 0
            counter.expires_at = now + timedelta(seconds=ttl)
            counter.save(update_fields=['count', 'expires_at'])
        RateLimitCounter.objects.filter(pk=counter.pk).update(count=F('count') + 1)
        counter.refresh_from_db(fields=['count'])
        return counter.count
