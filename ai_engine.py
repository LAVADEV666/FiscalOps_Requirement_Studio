from __future__ import annotations
import logging,re,threading
from pathlib import Path
from typing import Any
LOGGER=logging.getLogger('fiscalops.ai')
MODEL_ID='naver-clova-ix/donut-base-finetuned-docvqa'
class FiscalOpsAIEngine:
    QUESTIONS={
      'rfc':'¿Cuál es el RFC de la contribuyente?',
      'razon_social':'¿Cuál es la razón social de la contribuyente?',
      'tipo_requerimiento':'¿Qué tipo de requerimiento o acto administrativo es?',
      'fecha_oficio':'¿Cuál es la fecha del oficio?',
      'fecha_notificacion':'¿Cuál es la fecha de notificación?',
      'plazo':'¿Cuál es el plazo concedido para contestar?',
      'fundamentos_legales':'¿Qué artículos o fundamentos legales se citan?',
      'impuestos_montos_omitidos':'¿Qué impuesto, crédito, concepto o monto se requiere aclarar?'}
    def __init__(self,model_dir:Path|str|None=None,local_files_only:bool=True):
      self.model_dir=Path(model_dir) if model_dir else Path(__file__).resolve().parent/'models'/'donut-docvqa'
      self.source=str(self.model_dir if self.model_dir.exists() and any(self.model_dir.iterdir()) else MODEL_ID)
      self.local_files_only=local_files_only;self._processor=None;self._model=None;self._lock=threading.Lock()
      try:
       import torch
       self.torch=torch;self.device='cuda' if torch.cuda.is_available() else 'cpu'
      except Exception:self.torch=None;self.device='unavailable'
    def status(self)->dict[str,Any]:
      deps=True
      try:import transformers,torch
      except Exception:deps=False
      local=self.model_dir.exists() and any(self.model_dir.iterdir())
      return {'available':deps and local,'dependencies':deps,'model_local':local,'model_id':MODEL_ID,'device':self.device,'mode':'ai' if deps and local else 'deterministic_fallback'}
    def _load(self):
      if self._model is not None:return
      if not self.status()['available']:raise RuntimeError('IA opcional no instalada o modelo local ausente.')
      from transformers import DonutProcessor,VisionEncoderDecoderModel
      with self._lock:
       if self._model is not None:return
       self._processor=DonutProcessor.from_pretrained(str(self.model_dir),local_files_only=True)
       dtype=self.torch.float16 if self.device=='cuda' else self.torch.float32
       self._model=VisionEncoderDecoderModel.from_pretrained(str(self.model_dir),local_files_only=True,torch_dtype=dtype,low_cpu_mem_usage=True).to(self.device).eval()
    @staticmethod
    def _clean(value:str)->str:return re.sub(r'<[^>]+>|\s+',' ',value).strip(' :;,-')
    def _ask(self,image,question,page):
      self._load();prompt=f'<s_docvqa><s_question>{question}</s_question><s_answer>'
      inputs=self._processor(image,prompt,return_tensors='pt');ids=inputs.input_ids.to(self.device);pixels=inputs.pixel_values.to(self.device)
      with self._lock,self.torch.inference_mode():
       out=self._model.generate(input_ids=ids,pixel_values=pixels,max_new_tokens=192,num_beams=3,return_dict_in_generate=True,output_scores=True)
      value=self._clean(self._processor.batch_decode(out.sequences,skip_special_tokens=False)[0]);score=float(self.torch.exp(out.sequences_scores[0]).clamp(0,1).cpu()) if out.sequences_scores is not None else (.7 if value else 0)
      return {'value':value,'confidence':round(score,4),'source_page':page,'question':question}
    def analizar_documento(self,rutas:list[str|Path])->dict[str,Any]:
      from PIL import Image,ImageOps
      answers={key:[] for key in self.QUESTIONS}
      for page,path in enumerate(rutas,1):
       with Image.open(path) as raw:image=ImageOps.exif_transpose(raw).convert('RGB')
       image.thumbnail((2600,2600),Image.Resampling.LANCZOS)
       for key,question in self.QUESTIONS.items():answers[key].append(self._ask(image,question,page))
      def best(key):
       vals=[x for x in answers[key] if x['value']];return max(vals,key=lambda x:(x['confidence'],len(x['value']))) if vals else {'value':'','confidence':0,'source_page':1,'question':self.QUESTIONS[key]}
      return {'schema_version':'fiscalops.ai.v1','model_id':MODEL_ID,'device':self.device,'fields':{k:best(k) for k in ('rfc','razon_social','tipo_requerimiento','fecha_oficio','fecha_notificacion','plazo')},'fundamentos_legales':[x for x in answers['fundamentos_legales'] if x['value']],'impuestos_montos_omitidos':[{'concepto':x['value'],'monto':'','confidence':x['confidence'],'pagina':x['source_page']} for x in answers['impuestos_montos_omitidos'] if x['value']]}
