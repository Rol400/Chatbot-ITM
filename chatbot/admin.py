from django.contrib import admin

from .models import Message, PracticeSession


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("sender", "kind", "text", "created_at")
    readonly_fields = ("created_at",)


@admin.register(PracticeSession)
class PracticeSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "mode", "role", "questions_asked", "finished", "score", "created_at")
    list_filter = ("mode", "finished")
    inlines = [MessageInline]
