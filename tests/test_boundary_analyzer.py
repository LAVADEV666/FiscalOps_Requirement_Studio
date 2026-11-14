from types import SimpleNamespace

from boundary_analyzer import analyze_boundaries, deterministic_candidates


PAGES = [
    "1. Texto reproducido por la contribuyente.\n2) Otro numeral citado.\n"
    "En relación con lo anterior, proporcione Carpeta denominada Punto 1.\n"
    "a) Entregue el soporte.\n2 Continuando con la lectura del escrito reproducido.",
    "De acuerdo a sus manifestaciones, proporcione Carpeta denominada Punto\n"
    "2, con los ejemplos solicitados.\n3 Continuando con la lectura del escrito reproducido.",
    "Al respecto se solicita proporcione Carpeta denominada Punto 3.\n"
    "a) Explique el valor agregado.\n4 Continuando con la lectura del escrito reproducido.",
    "Respecto a lo anterior, solicite Carpeta denominada Punto 4.\n"
    "5 De la revisión efectuada a la declaración.",
    "Al respecto, se solicita proporcione carpeta denominada Punto\n"
    "5, que contenga lo siguiente.\n6 Continuando con la revisión del escrito.",
    "Por lo anterior, proporcione Carpeta denominada Punto 6.\n"
    "a) Presente el escrito.",
    "Continuación del soporte solicitado.",
    "Más soporte documental.",
    "Otra página del soporte documental.",
    "Notas: reglas generales.",
]


def test_deterministic_boundaries_ignore_numbered_quoted_text():
    result = deterministic_candidates(PAGES)
    assert [item["number"] for item in result["segments"]] == [1, 2, 3, 4, 5, 6]
    assert result["segments"][0]["text"].startswith("En relación con lo anterior")
    assert "2 Continuando" not in result["segments"][0]["text"]
    assert result["segments"][-1]["text"].startswith("Por lo anterior")
    assert "Notas: reglas generales." not in result["segments"][-1]["text"]


def test_ollama_boundaries_are_accepted_only_when_inside_safe_candidates():
    baseline = deterministic_candidates(PAGES)

    class FakeClient:
        config = SimpleNamespace(enabled=True, model="qwen3.5:4b")

        def status(self):
            return {"model_available": True, "model": self.config.model}

        def generate_json(self, prompt, *, system):
            return {"result": {"segments": [
                {
                    "number": item["number"],
                    "start_line_id": item["start_line_id"],
                    "end_line_id": item["end_line_id"],
                    "confidence": .95,
                    "reason": "La solicitud contiene el Punto y conserva sus incisos.",
                }
                for item in baseline["segments"]
            ]}}

    result = analyze_boundaries(PAGES, FakeClient())
    assert result["method"] == "ollama_validated_boundaries"
    assert result["model_status"] == "accepted"
    assert all(item["method"] == "ollama_validated_boundaries" for item in result["segments"])


def test_invalid_ollama_cut_falls_back_to_deterministic_boundaries():
    class FakeClient:
        config = SimpleNamespace(enabled=True, model="qwen3.5:4b")

        def status(self):
            return {"model_available": True, "model": self.config.model}

        def generate_json(self, prompt, *, system):
            return {"result": {"segments": [{
                "number": 1,
                "start_line_id": "P001L001",
                "end_line_id": "P001L001",
                "confidence": .99,
            }]}}

    result = analyze_boundaries(PAGES, FakeClient())
    assert result["method"] == "deterministic_request_anchors"
    assert result["model_status"] == "rejected_invalid_boundaries"
