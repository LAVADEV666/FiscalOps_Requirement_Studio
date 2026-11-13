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
