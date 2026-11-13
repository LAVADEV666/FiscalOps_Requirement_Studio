import numpy as np
from PIL import Image
from ocr_engine import OCREngine
from paddle_ocr_engine.preprocessor import estimate_skew
from paddle_ocr_engine.numerals import detect_numerals,normalize_numeral
from paddle_ocr_engine.schema import confidence01,polygon_bbox

def test_skew_blank():assert estimate_skew(np.full((200,300),255,np.uint8))==0.0
def test_contract_normalizes_confidence_and_bbox():
 assert confidence01(87)==.87
 assert confidence01(.94)==.94
 assert polygon_bbox([[10,20],[80,18],[82,40],[9,42]])==[9.0,18.0,82.0,42.0]

def test_hierarchical_numerals_and_limited_ocr_repair():
 assert normalize_numeral('I.O1')=='1.1'
 blocks=[{'block_id':'b1','text':'1.2. Proporcione papeles de trabajo','confidence':.96,'bbox':[20,100,500,130]}]
 result=detect_numerals(blocks,1000)
 assert result[0]['numeral']=='1.2' and result[0]['level']==1

class FakePaddle:
 def __init__(self):self.calls=0
 def ocr(self,*args,**kwargs):
  self.calls+=1
  return [[[[[10,20],[80,20],[80,40],[10,40]],('1. Proporcione información',.95)]]]

def configured_engine(tmp_path,monkeypatch):
 p=tmp_path/'p.png';Image.new('RGB',(600,900),'white').save(p)
 e=OCREngine(tmp_path/'cache');inner=e._engine;fake=FakePaddle();inner._ocr=fake
 monkeypatch.setattr(inner,'is_usable',lambda:True)
 monkeypatch.setattr(inner._layout,'analyze',lambda path:{'regions':[],'tables':[]})
 monkeypatch.setattr('paddle_ocr_engine.engine.build_variants',lambda path:([{'profile':'original','image':path,'skew':0,'width':600,'height':900}],{'label':'alta'}))
 return p,e,fake

def test_cache_and_confidence(tmp_path,monkeypatch):
 p,e,fake=configured_engine(tmp_path,monkeypatch);a=e.run(p);b=e.run(p)
 assert a['confidence']==.95 and b['cached'] is True and a['numerals'][0]['numeral']=='1'

def test_force_bypasses_cache(tmp_path,monkeypatch):
 p,e,fake=configured_engine(tmp_path,monkeypatch);e.run(p);first=fake.calls;e.run(p,force=True);assert fake.calls>first


def test_retry_keeps_more_complete_reading_and_original_coordinates(tmp_path, monkeypatch):
    path, engine, fake = configured_engine(tmp_path, monkeypatch)
    translated = np.array([[1., 0., -5.], [0., 1., -10.]])
    variants = [
        {"profile": "original", "image": "original", "skew": 0, "width": 600, "height": 900},
        {"profile": "balanced", "image": "balanced", "skew": 3, "width": 600, "height": 900, "inverse": translated},
        {"profile": "aggressive", "image": "aggressive", "skew": 3, "width": 600, "height": 900, "inverse": translated},
    ]
    monkeypatch.setattr("paddle_ocr_engine.engine.build_variants", lambda _: (variants, {"label": "media"}))

    def recognize(profile, **kwargs):
        if profile == "aggressive":
            raise RuntimeError("Error simulado del perfil")
        lines = [[[[10, 20], [80, 20], [80, 40], [10, 40]], ("1. Importe", .97)]]
        if profile == "balanced":
            lines.append([[[15, 50], [190, 50], [190, 65], [15, 65]], ("Segunda línea con el importe completo de 12500.00", .86)])
        return [lines]

    monkeypatch.setattr(fake, "ocr", recognize)
    result = engine.read_region(path)
    assert result["preprocessing_profile"] == "balanced"
    assert "12500.00" in result["text"]
    assert result["text_blocks"][1]["bbox"] == [10, 40, 185, 55]
