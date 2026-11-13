import json

from paddle_ocr_engine.human_review import CorrectionsStore


def test_corrections_are_append_only_and_feed_dictionary(tmp_path):
 store=CorrectionsStore(tmp_path)
 store.record({'original_text':'R.F.C OABC','corrected_text':'R.F.C 0ABC','action':'correct'})
 store.record({'original_text':'R.F.C OABC','corrected_text':'R.F.C 0ABC','action':'correct'})
 lines=store.log_path.read_text(encoding='utf-8').splitlines()
 dictionary=json.loads(store.dictionary_path.read_text(encoding='utf-8'))
 assert len(lines)==2
 assert next(iter(dictionary['pairs'].values()))['count']==2
