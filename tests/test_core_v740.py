from core import metadata
from text_normalizer import FiscalOpsNormalizer
from word_builder import field_value, replace_tokens

def test_valid_rfc_normalization():
    assert FiscalOpsNormalizer.normalize_rfc(" abc 010101 xx0 ")=="ABC010101XX0"

def test_amount():
    assert FiscalOpsNormalizer.normalize_amount("$1,234.5")==("1,234.50",True)

def test_metadata_tokens():
    data={"metadata_validation":{"fields":{"rfc":{"value":"ABC010101XX0"},"taxpayer_name":{"value":"EMPRESA DEMO"}}}}
    assert replace_tokens("[RAZÓN SOCIAL] RFC [RFC]",data)=="EMPRESA DEMO RFC ABC010101XX0"
    assert field_value(data,"office","[OFICIO]")=="[OFICIO]"

def test_ocr_metadata_tolerates_label_spacing_without_rewriting_document_text():
    fields = metadata("RFC ABC010101XX0\nNUMERO DE OFICIO500-01-2026-001\nIMPORTE $10,000.00")["fields"]
    assert fields["rfc"]["value"] == "ABC010101XX0"
    assert fields["office"]["value"] == "500-01-2026-001"
    assert fields["amount"]["value"] == "$10,000.00"
    legacy_fields = metadata("R.F.C. ABC010101XX0\nNúmero de oficio: 500-01-2026-123")["fields"]
    assert legacy_fields["rfc"]["value"] == "ABC010101XX0"
