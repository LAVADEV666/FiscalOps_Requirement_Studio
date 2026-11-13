from pathlib import Path
import os
import pytest
from core import extract
PDF=Path(os.environ.get("FISCALOPS_REAL_TEST_PDF",""))
@pytest.mark.skipif(not PDF.is_file(),reason="PDF real no disponible en distribución limpia")
def test_covasa_real_pdf():
 data=extract(PDF)
 assert data["pages"]==16
 assert [p["number"] for p in data["points"]]==[1,2,3,4,5,6]
 assert data["metadata_validation"]["fields"]["rfc"]["value"]=="ISM010110IS8"
 assert data["metadata_validation"]["fields"]["office"]["value"]=="500-72-01-01-04-2026-17744"
