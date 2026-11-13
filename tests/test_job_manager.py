import time
from job_manager import JobManager,JobCancelled

def wait(m,jid):
 for _ in range(100):
  s=m.read(jid)
  if s['status'] in {'completed','failed','cancelled'}:return s
  time.sleep(.01)
 return m.read(jid)
def test_background_progress(tmp_path):
 m=JobManager(tmp_path);j=m.create();
 def work(jid):m.checkpoint(jid,'ocr',50);return {'ok':True}
 m.run(j['job_id'],work);s=wait(m,j['job_id']);assert s['status']=='completed' and s['progress']==100
def test_safe_cancel(tmp_path):
 m=JobManager(tmp_path);j=m.create();m.cancel(j['job_id'])
 def work(jid):m.checkpoint(jid,'scan',20)
 m.run(j['job_id'],work);assert wait(m,j['job_id'])['status']=='cancelled'
def test_failure_recorded(tmp_path):
 m=JobManager(tmp_path);j=m.create();m.run(j['job_id'],lambda jid:1/0);s=wait(m,j['job_id']);assert s['status']=='failed' and s['error']['type']=='ZeroDivisionError'
def test_recover_interrupted(tmp_path):
 m=JobManager(tmp_path);j=m.create();m.update(j['job_id'],status='running');assert j['job_id'] in JobManager(tmp_path).recover_interrupted();assert m.read(j['job_id'])['status']=='interrupted'
