from __future__ import annotations
import re
LIST_START=re.compile(r'^(?:[•✓▪]|[a-z][.)]|[ivx]{1,5}[.)])\s+',re.I)
LOWER=re.compile(r'^[a-záéíóúñ]')
END=re.compile(r'[.!?;:]$')
def normalize_extracted_text(text:str)->str:
 text=text.replace('\r','\n').replace('\uf0d8','').replace('\u00ad','')
 text=re.sub(r'(?m)^\s*([a-z])\.\s+',r'\1) ',text,flags=re.I)
 text=re.sub(r'(?m)^\s*([ivx]{1,5})\.\s+',r'\1. ',text,flags=re.I)
 text=re.sub(r'\s+([a-z]\))\s+(?=[A-ZÁÉÍÓÚÑ¿])',r'\n\1 ',text,flags=re.I)
 text=re.sub(r'\s+([•✓▪])\s+',r'\n\1 ',text)
 lines=[]
 for raw in text.splitlines():
  line=re.sub(r'[ \t]+',' ',raw).strip()
  if line:lines.append(line)
 out=[];current=''
 for line in lines:
  if LIST_START.match(line):
   if current:out.append(current)
   current=line
  elif not current:current=line
  elif current.endswith('-') and LOWER.match(line):current=current[:-1]+line
  elif not END.search(current) or LOWER.match(line):current+=' '+line
  else:out.append(current);current=line
 if current:out.append(current)
 return '\n\n'.join(re.sub(r'\s+',' ',item).strip() for item in out if item.strip())
def split_structured_lines(text: str):
    """Identify list styles without changing text already accepted in the workspace."""
    blocks = []
    for paragraph in re.split(r'\n[ \t]*\n', text.strip()):
        match = re.match(r'^([•✓▪]|[a-z][.)]|[ivx]{1,5}[.)])\s+(.+)$', paragraph, re.I | re.S)
        if not match:
            blocks.append({'kind': 'paragraph', 'marker': '', 'text': paragraph})
            continue
        marker, content = match.groups()
        kind = 'bullet' if marker in {'•', '✓', '▪', ''} else (
            'roman' if re.fullmatch(r'[ivx]{1,5}[.)]', marker, re.I) else 'subitem'
        )
        blocks.append({'kind': kind, 'marker': marker, 'text': content})
    return blocks

class FiscalOpsNormalizer:
    RFC_PATTERN=re.compile(r'^(?:[A-Z&Ñ]{3}\d{6}[A-Z0-9]{3}|[A-Z&Ñ]{4}\d{6}[A-Z0-9]{3})$')
    RFC_ALPHABET='0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ'
    THRESHOLD=.95
    @classmethod
    def normalize_rfc(cls,value):return re.sub(r'[^A-Z0-9&Ñ]','',str(value or '').upper())
    @classmethod
    def check_digit(cls,body):
        padded=body if len(body)==12 else ' '+body;values={c:i for i,c in enumerate(cls.RFC_ALPHABET)}
        if len(padded)!=12 or any(c not in values for c in padded):return ''
        digit=11-(sum(values[c]*(13-i) for i,c in enumerate(padded))%11)
        return '0' if digit==11 else 'A' if digit==10 else str(digit)
    @classmethod
    def validate_rfc(cls,value):
        rfc=cls.normalize_rfc(value)
        return bool(cls.RFC_PATTERN.fullmatch(rfc) and cls.check_digit(rfc[:-1])==rfc[-1])
    @classmethod
    def repair_rfc(cls,value):
        rfc=cls.normalize_rfc(value)
        if cls.validate_rfc(rfc):return rfc,False,True
        swaps={'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','B':'8','0':'O','1':'I','2':'Z','5':'S','8':'B'}
        for i,c in enumerate(rfc):
            if c in swaps:
                candidate=rfc[:i]+swaps[c]+rfc[i+1:]
                if cls.validate_rfc(candidate):return candidate,True,True
        return rfc,False,False
    @staticmethod
    def normalize_amount(value):
        raw=str(value or '').upper().translate(str.maketrans({'O':'0','Q':'0','I':'1','L':'1'}));raw=re.sub(r'[^0-9,.-]','',raw)
        try:return f'{float(raw.replace(",","")):,.2f}',True
        except Exception:return raw,False
    @classmethod
    def normalize_workspace(cls,data):
        fields=data.setdefault('metadata_validation',{}).setdefault('fields',{});alerts=[]
        if 'rfc' in fields:
            value,repaired,valid=cls.repair_rfc(fields['rfc'].get('value',''));confidence=min(float(fields['rfc'].get('confidence',0)),1.0 if valid else 0)
            fields['rfc'].update(value=value,valid=valid,repaired=repaired,confidence=confidence,requiere_revision_humana=(not valid or confidence<cls.THRESHOLD))
            if fields['rfc']['requiere_revision_humana']:alerts.append({'severity':'critical','code':'RFC_REVIEW','field':'rfc','message':'RFC inválido o confianza inferior a 95%.'})
        for key in ('amount','monto'):
            if key in fields:
                value,valid=cls.normalize_amount(fields[key].get('value',''));confidence=min(float(fields[key].get('confidence',0)),1.0 if valid else 0)
                fields[key].update(value=value,valid=valid,confidence=confidence,requiere_revision_humana=(not valid or confidence<cls.THRESHOLD))
                if fields[key]['requiere_revision_humana']:alerts.append({'severity':'critical','code':'AMOUNT_REVIEW','field':key,'message':'Monto inválido o confianza inferior a 95%.'})
        data['human_review']={'required':bool(alerts),'threshold':cls.THRESHOLD,'alerts':alerts};return data
