from pathlib import Path
from reportlab.pdfgen import canvas
from processing_pipeline import ProcessingPipeline

def make_pdf(path):
 c=canvas.Canvas(str(path));c.setFont('Helvetica',10);c.drawString(50,790,'Servicio de Administracion Tributaria');c.drawString(50,770,'Numero de oficio: 500-01-2026-123');c.drawString(50,750,'R.F.C. ABC010101XX0');c.drawString(50,710,'Se solicita lo siguiente:');c.drawString(50,680,'1. Proporcione papel de trabajo en formato Excel y estados de cuenta.');c.drawString(50,640,'2. Aclare las diferencias identificadas en los CFDI del periodo.');c.drawString(50,100,'Notifiquese.');c.save()
def test_real_pdf_end_to_end(tmp_path):
 pdf=tmp_path/'requerimiento.pdf';make_pdf(pdf);stages=[];result=ProcessingPipeline(tmp_path/'work').run('task1',pdf,lambda s,p,m='':stages.append((s,p)));d=tmp_path/'work'/result['session_id'];assert result['points']==2 and (d/'workspace.json').exists() and (d/'pages'/'page-1.png').exists();assert stages[-1][0]=='finalizing'
def test_invalid_pdf_cleanup(tmp_path):
 p=tmp_path/'bad.pdf';p.write_text('not pdf');pipe=ProcessingPipeline(tmp_path/'work')
 import pytest
 with pytest.raises(ValueError):pipe.run('bad',p)
 assert not list((tmp_path/'work').iterdir())
