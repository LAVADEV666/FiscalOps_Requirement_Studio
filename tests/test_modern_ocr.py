import numpy as np

from config import ocr_dpi_for_page
from paddle_ocr_engine.modern import ModernLayoutAnalyzer, ModernOCR, detection_limit_side_len


def test_detection_limit_is_local_and_bounded(monkeypatch):
    monkeypatch.setenv("FISCALOPS_OCR_DET_LIMIT_SIDE_LEN", "99999")
    assert detection_limit_side_len() == 4096
    monkeypatch.setenv("FISCALOPS_OCR_DET_LIMIT_SIDE_LEN", "not-a-number")
    assert detection_limit_side_len() == 2048


def test_ocr_render_keeps_standard_pages_high_resolution_and_caps_oversized_pages():
    assert ocr_dpi_for_page(612, 792) == 400
    assert ocr_dpi_for_page(1200, 1200) < 400


def test_modern_predictions_keep_text_confidence_and_polygon_contract():
    class Predict:
        def predict(self, image):
            yield {"rec_polys": np.array([[[5, 10], [100, 10], [100, 30], [5, 30]]]),
                   "rec_texts": ["1. Importe 12500.00"], "rec_scores": np.array([.97])}

    adapter = ModernOCR.__new__(ModernOCR)
    adapter.engine = Predict()
    lines = adapter.ocr(None)
    assert lines == [[[[[5, 10], [100, 10], [100, 30], [5, 30]], ("1. Importe 12500.00", .97)]]]


def test_modern_layout_keeps_table_and_figure_source_coordinates(tmp_path):
    from PIL import Image

    image = tmp_path / "page.png"
    Image.new("RGB", (300, 400), "white").save(image)

    class Predict:
        def predict(self, image, **kwargs):
            yield {"boxes": [
                {"label": "table", "coordinate": [10, 20, 200, 150], "score": .94},
                {"label": "image", "coordinate": [30, 220, 180, 350], "score": .91},
            ]}

    layout = ModernLayoutAnalyzer(tmp_path)
    layout.engine = Predict()
    result = layout.analyze(image)
    assert result["size"] == [300, 400]
    assert result["tables"][0]["bbox"] == [10, 20, 200, 150]
    assert result["regions"][1]["type"] == "figure"
