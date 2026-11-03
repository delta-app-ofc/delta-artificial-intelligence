from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from app.alerts.policy import proposals

def point(now, liters):
    return SimpleNamespace(window_started_at=now-timedelta(minutes=5),window_finished_at=now,consumption_liters=liters)

def test_zero_is_data_and_absence_does_not_trigger_limit():
    now=datetime(2026,11,2,22,tzinfo=timezone.utc)
    assert proposals(7,[],100,now)[0]==[]
    alerts,resolve=proposals(7,[point(now,0)],100,now)
    assert alerts==[]
    assert "gluh:7:limite_ultrapassado:2026-11-02" in resolve

def test_threshold_and_idempotency_key_and_no_leak_types():
    now=datetime(2026,11,2,22,tzinfo=timezone.utc)
    alerts,_=proposals(7,[point(now,101)],100,now)
    assert len(alerts)==1
    assert alerts[0]["alert_type"]=="limite_ultrapassado"
    assert alerts[0]["source"]=="gluh"
    assert alerts[0]["dedup_key"]=="gluh:7:limite_ultrapassado:2026-11-02"
    assert alerts[0]["evidence"]["value"]==101
    assert all(a["alert_type"]!="limite_ultrapassado" for a in proposals(7,[point(now,100)],100,now)[0])

def test_expected_consumption_requires_seven_measured_days():
    now=datetime(2026,11,2,22,tzinfo=timezone.utc)
    history=[point(now-timedelta(days=i),10) for i in range(1,8)]+[point(now,13)]
    alerts,_=proposals(7,history,None,now)
    assert alerts[0]["alert_type"]=="consumo_acima_esperado"
    assert alerts[0]["evidence"]["baseline_days"]==7
    assert proposals(7,history[1:],None,now)[0]==[]

def test_job_isolates_user_failure(monkeypatch):
    from app.alerts import job
    def process(user_id,*args):
        if user_id==2:raise RuntimeError("offline")
        return {"created":0,"proposed":1,"skipped":0}
    monkeypatch.setattr(job,"process_user",process)
    result=job.run([1,2,3],workers=2)
    assert result["processed"]==2 and result["failed"]==1
    assert result["llm_calls"]==0 and result["proposed"]==2
