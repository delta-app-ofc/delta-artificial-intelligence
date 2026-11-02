"""Job diário por lotes. Sem LLM, sem push/e-mail; o histórico independe de notifications_enabled."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from time import monotonic
from app.data import db_mongo,db_postgres
from app.tools.forecast.tools import build_tools
from app.alerts.client import AlertsClient
from app.alerts.policy import proposals

def process_user(user_id,execute=False,now=None):
    now=now or datetime.now(timezone.utc)
    if not db_postgres.is_user_active(user_id): return {"skipped":1}
    kind=db_postgres.get_user_access_kind(user_id)
    if kind=="residential": history=db_mongo.get_consumption_history(user_id,29)
    elif kind=="organizational":
        ids=[p.property_id for p in db_postgres.get_user_organization_properties(user_id)]
        devices=db_postgres.get_authorized_device_ids(user_id,ids)
        history=db_mongo.get_consumption_history_by_devices(devices,29) if devices else []
    else: return {"skipped":1}
    tools={t.name:t for t in build_tools(user_id,now.astimezone(ZoneInfo('America/Sao_Paulo')).date(),kind)}
    forecast=tools["calculate_forecast"].invoke({})
    habits=db_postgres.get_user_habits(user_id) if kind=="residential" else []
    alerts,resolve=proposals(user_id,history,db_mongo.get_daily_liters_target(user_id),now,forecast,habits)
    created=0
    if execute:
        client=AlertsClient()
        for key in resolve: client.resolve(key)
        for payload in alerts:
            status,_=client.create(payload);created+=int(status==201)
    return {"proposed":len(alerts),"created":created,"skipped":0}

def run(user_ids=None,execute=False,workers=4):
    if workers<1 or workers>16: raise ValueError("workers deve ficar entre 1 e 16")
    if user_ids is None:
        user_ids=db_postgres.get_active_user_ids()
    ids=sorted(set(int(u) for u in user_ids if int(u)>0));start=monotonic()
    summary={"category":"alerts_job","processed":0,"failed":0,"created":0,"proposed":0,"skipped":0,"llm_calls":0,"llm_cost":0}
    # Lotes de 100 limitam memória e número de futures mesmo para milhares de usuários.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0,len(ids),100):
            futures=[pool.submit(process_user,u,execute) for u in ids[offset:offset+100]]
            for f in as_completed(futures):
                try:
                    result=f.result();summary["processed"]+=1
                    for key,value in result.items(): summary[key]+=value
                except Exception: summary["failed"]+=1
    summary["elapsed_ms"]=round((monotonic()-start)*1000)
    return summary
