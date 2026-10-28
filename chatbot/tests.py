"""
Pruebas automáticas. Correr con:  python manage.py test chatbot
No llaman a ninguna API: el modelo de lenguaje se simula.
"""
import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from . import grammar, intents, interview, llm, prompts
from .models import Message, PracticeSession

START = {"context_summary": "Puesto de desarrollo web junior.", "question": "Preséntate.", "question_type": "Presentación"}


def evaluation(score=72, next_q="¿Qué es una API REST?", **extra):
    data = {"status": "answer", "message": "Buena base.", "score": score, "label": "Buena base",
            "feedback": {"good": ["Fuiste concreto"], "improve": ["Cierra con el resultado"], "example": "Desarrollé…"},
            "scores": {"claridad": 4, "estructura": 2, "seguridad": 4}, "fillers": ["este"],
            "next_question": next_q, "next_question_type": "Técnica"}
    data.update(extra)
    return data


class LLMTests(TestCase):
    def test_parse_json_tolerates_code_fences(self):
        self.assertEqual(llm.parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm.parse_json('Claro: {"a": 2} listo'), {"a": 2})

    @override_settings(LLM_CHAIN=["groq:primero", "gemini:segundo"], GROQ_API_KEY="x", GEMINI_API_KEY="y")
    def test_falls_back_to_next_model(self):
        def fail(*args):
            raise llm.RateLimited("sin cuota")

        with mock.patch.dict(llm.PROVIDERS, {"groq": (fail, "GROQ_API_KEY"),
                                             "gemini": (lambda *a: '{"ok": true}', "GEMINI_API_KEY")}):
            data, model = llm.complete_json("sys", [{"role": "user", "content": "hola"}])
        self.assertEqual((data, model), ({"ok": True}, "gemini:segundo"))

    @override_settings(LLM_CHAIN=["groq:a"], GROQ_API_KEY="")
    def test_error_when_no_key(self):
        with self.assertRaises(llm.LLMError):
            llm.complete_json("sys", [])


class IntentModelTests(TestCase):
    def setUp(self):
        if intents.get_classifier() is None:
            self.skipTest("Falta intent_model.json")

    def test_commands_and_content(self):
        self.assertEqual(intents.classify("cambiar a gramática").tag, "cambiar_gramatica")
        self.assertEqual(intents.classify("ya quiero mi calificación").tag, "terminar")
        self.assertIsNone(intents.classify("desarrollador web"))
        self.assertIsNone(intents.classify("Usé Django y PostgreSQL para el inventario de la tienda de mi tía"))


class LocateErrorsTests(TestCase):
    def test_finds_each_fragment_once_in_order(self):
        errors = [{"wrong": "mas"}, {"wrong": "se"}, {"wrong": "Mas"}]
        grammar.locate_errors("haiga mas tiempo, no se si mas", errors)
        self.assertEqual((errors[0]["start"], errors[0]["end"]), (6, 9))
        self.assertEqual(errors[1]["start"], 21)
        self.assertEqual(errors[2]["start"], 27)

    def test_missing_fragment_has_no_position(self):
        errors = [{"wrong": "inexistente"}]
        grammar.locate_errors("hola", errors)
        self.assertIsNone(errors[0]["start"])


@override_settings(MESSAGES_PER_MINUTE=100, MESSAGES_PER_DAY=1000)
class ApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana", "ana@example.com", "clave-segura-123")
        self.client = Client()
        self.client.login(username="ana", password="clave-segura-123")
        patcher = mock.patch.object(intents, "classify", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, url, body=None):
        return self.client.post(url, json.dumps(body or {}), content_type="application/json")

    def start_interview(self, total=5):
        with mock.patch.object(llm, "complete_json", return_value=(START, "t")):
            response = self.client.post("/api/entrevista/iniciar", {"role": "Desarrollador web", "level": "junior",
                                                                     "interview_type": "tecnica", "total": total})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class PageTests(ApiTestCase):
    def test_public_and_private_pages(self):
        self.assertEqual(Client().get("/").status_code, 200)
        self.assertEqual(Client().get("/entrevista").status_code, 302)
        for url in ("/entrevista", "/gramatica", "/progreso", "/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertRedirects(self.client.get("/chatbot"), "/entrevista")

    def test_api_requires_login_and_csrf(self):
        self.assertEqual(Client().post("/api/entrevista/responder", "{}", content_type="application/json").status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.login(username="ana", password="clave-segura-123")
        self.assertEqual(client.post("/api/gramatica/revisar", "{}", content_type="application/json").status_code, 403)

    @override_settings(MESSAGES_PER_MINUTE=1)
    def test_rate_limit(self):
        with mock.patch.object(llm, "complete_json", return_value=({"text": "Hubieron fallas.", "title": "Reporte"}, "t")):
            self.assertEqual(self.post("/api/gramatica/ejercicio").status_code, 200)
            self.assertEqual(self.post("/api/gramatica/ejercicio").status_code, 429)

    def test_service_error_is_friendly(self):
        with mock.patch.object(llm, "complete_json", side_effect=llm.LLMError("todo falló")):
            response = self.post("/api/gramatica/revisar", {"text": "hola mundo de prueba"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("inteligencia artificial", response.json()["error"])


class InterviewTests(ApiTestCase):
    def test_start_uses_setup_and_cv(self):
        cv = SimpleUploadedFile("cv.txt", "Proyecto de residencia: app de inventario con Django".encode(), "text/plain")
        with mock.patch.object(llm, "complete_json", return_value=(START, "t")) as fake:
            data = self.client.post("/api/entrevista/iniciar", {"role": "Desarrollador web", "level": "practicante",
                                                                "interview_type": "tecnica", "total": 5, "cv": cv,
                                                                "job_description": "Buscamos Django"}).json()
        system = fake.call_args.args[0]
        self.assertIn("app de inventario con Django", system)
        self.assertIn("Buscamos Django", system)
        self.assertIn("practicante", system)
        self.assertEqual(data["phase"], "question")
        self.assertEqual(data["question"]["text"], "Preséntate.")
        self.assertEqual(data["session"]["total_questions"], 5)

    def test_start_requires_role(self):
        response = self.client.post("/api/entrevista/iniciar", {"role": "  "})
        self.assertEqual(response.status_code, 400)

    def test_answer_then_next_uses_pending_question_without_api(self):
        self.start_interview()
        with mock.patch.object(llm, "complete_json", return_value=(evaluation(), "t")) as fake:
            data = self.post("/api/entrevista/responder", {"text": "Pues este, soy desarrollador", "source": "voice",
                                                           "duration": 30}).json()
        self.assertIn("Preséntate.", fake.call_args.args[0])
        self.assertEqual(data["kind"], "answer")
        self.assertEqual(data["state"]["phase"], "feedback")
        fb = data["state"]["feedback"]["data"]
        self.assertEqual((fb["score"], fb["wpm"], fb["question_number"]), (72, 8, 1))
        self.assertEqual(data["state"]["answer"], "Pues este, soy desarrollador")

        with mock.patch.object(llm, "complete_json") as fake:
            data = self.post("/api/entrevista/siguiente").json()
        fake.assert_not_called()
        self.assertEqual(data["state"]["question"]["text"], "¿Qué es una API REST?")
        self.assertEqual(data["state"]["session"]["questions_asked"], 2)

    def test_retry_keeps_same_question(self):
        self.start_interview()
        with mock.patch.object(llm, "complete_json", side_effect=[(evaluation(50), "t"), (evaluation(80), "t")]):
            self.post("/api/entrevista/responder", {"text": "respuesta corta"})
            data = self.post("/api/entrevista/responder", {"text": "respuesta mejor y completa"}).json()
        self.assertEqual(data["state"]["session"]["questions_asked"], 1)
        self.assertEqual(data["state"]["feedback"]["data"]["score"], 80)

    def test_nonsense_and_requests_do_not_advance(self):
        self.start_interview()
        invalid = {"status": "invalid", "message": "Eso no responde la pregunta.", "score": 90,
                   "feedback": {"good": ["x"]}, "next_question": "¿Otra?"}
        with mock.patch.object(llm, "complete_json", return_value=(invalid, "t")):
            data = self.post("/api/entrevista/responder", {"text": "asdfgh"}).json()
        self.assertEqual(data["kind"], "invalid")
        self.assertEqual(data["state"]["phase"], "question")
        self.assertTrue(data["state"]["interviewer"]["data"]["invalid"])
        self.assertEqual(PracticeSession.objects.get().pending_question, "")

    def test_model_leaving_role_is_retried(self):
        self.start_interview()
        assistant = {"status": "request", "message": "Claro, aquí tienes una guía:\n1. Reproduce\n2. Lee el log"}
        with mock.patch.object(llm, "complete_json", side_effect=[(assistant, "t"), (evaluation(), "t")]) as fake:
            data = self.post("/api/entrevista/responder", {"text": "google y chatgpt"}).json()
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(fake.call_args_list[1].args[1][-1]["content"], prompts.INTERVIEW_REMINDER)
        self.assertEqual(data["kind"], "answer")

    def test_other_question_replaces_without_advancing(self):
        self.start_interview()
        with mock.patch.object(llm, "complete_json", return_value=({"question": "¿Por qué tecnología?",
                                                                    "question_type": "Motivación"}, "t")):
            data = self.post("/api/entrevista/otra").json()
        self.assertEqual(data["state"]["question"]["text"], "¿Por qué tecnología?")
        self.assertEqual(data["state"]["session"]["questions_asked"], 1)

    def test_full_interview_report_progress_and_practice(self):
        self.start_interview(total=3)
        answers = [evaluation(60), evaluation(90, "¿Pregunta 3?"), evaluation(40, None)]
        summary = {"score": 68, "label": "Buena base", "summary": "Vas bien.", "strengths": ["Claridad"],
                   "improve": ["Estructura"]}
        with mock.patch.object(llm, "complete_json", side_effect=[(a, "t") for a in answers] + [(summary, "t")]):
            for i in range(3):
                data = self.post("/api/entrevista/responder", {"text": f"respuesta {i}"}).json()
                if i < 2:
                    self.post("/api/entrevista/siguiente")
            self.assertTrue(data["state"]["is_last"])
            result = self.post("/api/entrevista/siguiente").json()
        session = PracticeSession.objects.get(mode="interview")
        self.assertEqual(result["navigate"], f"/reporte/{session.id}")
        self.assertTrue(session.finished)
        self.assertEqual(session.score, 68)

        page = self.client.get(result["navigate"])
        self.assertContains(page, "Buena base")
        self.assertContains(page, "respuesta 2")
        self.assertContains(page, "Practicar las 2 más bajas")
        progress = self.client.get("/progreso")
        self.assertContains(progress, "Promedio en entrevistas")
        self.assertContains(progress, f"/reporte/{session.id}")

        with mock.patch.object(llm, "complete_json") as fake:
            data = self.post(f"/api/entrevista/{session.id}/practicar").json()
        fake.assert_not_called()
        practice = PracticeSession.objects.filter(mode="interview", finished=False).get()
        self.assertEqual(practice.total_questions, 2)
        self.assertEqual(practice.current_question, "¿Pregunta 3?")
        self.assertEqual(data["navigate"], "/entrevista")

    def test_finish_requires_an_answer(self):
        self.start_interview()
        self.assertEqual(self.post("/api/entrevista/terminar").status_code, 400)

    def test_intent_finish_from_answer_box(self):
        self.start_interview()
        summary = {"score": 50, "summary": "Corta.", "strengths": [], "improve": []}
        with mock.patch.object(llm, "complete_json", side_effect=[(evaluation(), "t"), (summary, "t")]):
            self.post("/api/entrevista/responder", {"text": "respuesta"})
            with mock.patch.object(intents, "classify", return_value=intents.Intent("terminar", 0.98)):
                data = self.post("/api/entrevista/responder", {"text": "ya terminé"}).json()
        self.assertTrue(data["navigate"].startswith("/reporte/"))

    def test_transcribe(self):
        self.assertEqual(self.client.post("/api/transcribe").status_code, 400)
        tiny = SimpleUploadedFile("a.webm", b"x" * 100, content_type="audio/webm")
        self.assertEqual(self.client.post("/api/transcribe", {"audio": tiny}).json(), {"text": ""})
        audio = SimpleUploadedFile("a.webm", b"x" * 5000, content_type="audio/webm")
        with mock.patch.object(llm, "transcribe", return_value="hola mundo"):
            self.assertEqual(self.client.post("/api/transcribe", {"audio": audio}).json(), {"text": "hola mundo"})


class GrammarTests(ApiTestCase):
    def test_check_locates_errors_and_scores(self):
        reply = {"status": "text", "message": "Casi.", "corrected": "Ojalá haya más tiempo.",
                 "errors": [{"type": "Gramática", "wrong": "haiga", "right": "haya", "explanation": "Forma correcta."},
                            {"type": "Acentos", "wrong": "mas", "right": "más", "explanation": "Lleva tilde."}],
                 "fillers": [], "scores": {"ortografia": 6, "gramatica": 6, "claridad": 9}, "label": "Casi listo"}
        with mock.patch.object(llm, "complete_json", return_value=(reply, "t")):
            data = self.post("/api/gramatica/revisar", {"text": "Ojalá haiga mas tiempo."}).json()
        d = data["message"]["data"]
        self.assertEqual(data["status"], "text")
        self.assertEqual(d["score"], 70)
        self.assertEqual((d["errors"][0]["start"], d["errors"][0]["end"]), (6, 11))
        self.assertEqual(d["original"], "Ojalá haiga mas tiempo.")

    def test_nonsense_is_not_graded(self):
        with mock.patch.object(llm, "complete_json", return_value=({"status": "invalid", "message": "No se puede revisar.",
                                                                    "scores": {"gramatica": 10}}, "t")):
            data = self.post("/api/gramatica/revisar", {"text": "qwerty !!!"}).json()
        self.assertEqual(data["status"], "invalid")
        self.assertIsNone(data["message"]["data"]["scores"])

    def test_greeting_is_answered_by_own_model(self):
        with mock.patch.object(intents, "classify", return_value=intents.Intent("saludo", 0.99)), \
                mock.patch.object(llm, "complete_json") as fake:
            data = self.post("/api/gramatica/revisar", {"text": "hola"}).json()
        fake.assert_not_called()
        self.assertEqual(data["status"], "intent")
        self.assertEqual(data["message"]["data"]["source"], "intent")

    def test_exercise(self):
        with mock.patch.object(llm, "complete_json", return_value=({"text": "Hubieron fallas.", "title": "Reporte"}, "t")):
            self.assertEqual(self.post("/api/gramatica/ejercicio").json(), {"text": "Hubieron fallas.", "title": "Reporte"})
