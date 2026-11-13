import os,time
from maintenance import clean_sessions,verify_distribution

def test_cleanup_dry_run_and_delete(tmp_path):
 d=tmp_path/('a'*32);d.mkdir();(d/'x').write_text('123');old=time.time()-40*86400;os.utime(d,(old,old));r=clean_sessions(tmp_path,30,True);assert r['count']==1 and d.exists();r=clean_sessions(tmp_path,30,False);assert r['count']==1 and not d.exists()
def test_verify_distribution(tmp_path):
 (tmp_path/'ok.py').write_text('x=1');assert verify_distribution(tmp_path)['valid'];(tmp_path/'bad.py').write_text('x=');assert not verify_distribution(tmp_path)['valid']
