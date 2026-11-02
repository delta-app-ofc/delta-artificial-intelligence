from datetime import datetime, timezone
from decimal import Decimal
from app.data.db_mongo import _to_point, _to_alert
from app.tools.forecast.calculations import estimate_next_bill
from app.tools.models import LastWaterBill

def test_pending_is_unknown_and_preserves_evidence():
    now=datetime.now(timezone.utc)
    point=_to_point(dict(user_id=7,device_id="dev",window_started_at=now,window_finished_at=now,
        consumption_liters=0,anomaly_detected=None,anomaly_reasons=["continuous_flow"],anomaly_evidence={"lpm":0.2}))
    assert point.anomaly_detected is None
    assert point.anomaly_evidence["lpm"]==0.2

def test_general_alert_has_no_device_but_keeps_source_and_message():
    alert=_to_alert(dict(user_id=7,alert_type="limite_ultrapassado",triggered_at=datetime.now(timezone.utc),
        source="gluh",message="Meta excedida",evidence={"value":120}))
    assert alert.device_id is None and alert.source=="gluh" and alert.evidence["value"]==120

def test_a_recorded_zero_never_uses_the_previous_bill():
    now=datetime.now(timezone.utc)
    point=_to_point(dict(user_id=7,device_id="dev",window_started_at=now,window_finished_at=now,consumption_liters=0))
    bill=LastWaterBill(7,now.date().replace(day=1),Decimal("120"),Decimal("20"))
    result=estimate_next_bill([point],bill,Decimal("5"),now.date())
    assert result.base=="history_projection" and result.estimated_value==0
    assert estimate_next_bill([point],bill,None,now.date()) is None
    assert estimate_next_bill([],bill,None,now.date()).base=="last_bill"
