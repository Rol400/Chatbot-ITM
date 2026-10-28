from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login", views.login_view, name="login"),
    path("register", views.register_view, name="register"),
    path("logout", views.logout_view, name="logout"),
    path("entrevista", views.interview_page, name="interview"),
    path("reporte/<int:session_id>", views.report_page, name="report"),
    path("gramatica", views.grammar_page, name="grammar"),
    path("progreso", views.progress_page, name="progress"),
    path("chatbot", views.legacy_chatbot, name="chatbot"),

    path("api/entrevista/iniciar", views.api_interview_start, name="api_interview_start"),
    path("api/entrevista/responder", views.api_interview_answer, name="api_interview_answer"),
    path("api/entrevista/siguiente", views.api_interview_next, name="api_interview_next"),
    path("api/entrevista/otra", views.api_interview_other, name="api_interview_other"),
    path("api/entrevista/terminar", views.api_interview_finish, name="api_interview_finish"),
    path("api/entrevista/<int:session_id>/practicar", views.api_interview_practice, name="api_interview_practice"),
    path("api/gramatica/revisar", views.api_grammar_check, name="api_grammar_check"),
    path("api/gramatica/ejercicio", views.api_grammar_exercise, name="api_grammar_exercise"),
    path("api/transcribe", views.api_transcribe, name="api_transcribe"),
]
