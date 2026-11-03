"""Regras de metas e tendência; nenhuma regra declara vazamento ou pressão."""
from datetime import datetime,timedelta
from statistics import mean
from zoneinfo import ZoneInfo

def proposals(user_id, history, target, now, forecast=None, habits=None, zone="America/Sao_Paulo"):
    local=now.astimezone(ZoneInfo(zone));today=local.date();series={}
    for point in history:
        if point.window_finished_at>now: continue
        day=point.window_started_at.astimezone(ZoneInfo(zone)).date()
        series[day]=series.get(day,0)+float(point.consumption_liters)
    total=series.get(today);previous=[v for d,v in series.items() if today-timedelta(days=28)<=d<today]
    prefix=f"gluh:{user_id}:";period=today.isoformat();result=[];resolve=[]
    def emit(kind,severity,title,message,evidence,scope=period):
        result.append(dict(user_id=user_id,alert_type=kind,severity=severity,title=title,message=message,
            evidence=evidence,source="gluh",dedup_key=prefix+kind+":"+scope))
    if target is not None and target>0 and total is not None:
        key=prefix+"limite_ultrapassado:"+period
        if total>target: emit("limite_ultrapassado","high","Limite diário ultrapassado",
            f"O consumo registrado foi {total:.1f} L para uma meta de {target:.1f} L.",{"value":total,"target":target,"period":period,"unit":"L"})
        else: resolve.append(key)
        if local.hour>=18:
            fraction=(local.hour+local.minute/60)/24
            projected=total/fraction
            if total<=target and projected>target:
                emit("previsao_ultrapassagem_meta","medium","Possível ultrapassagem da meta",
                    "O ritmo registrado pode ultrapassar a meta diária; é uma estimativa.",
                    {"value":projected,"target":target,"pct":100*projected/target,"period":period,"cutoff":now.isoformat()})
            else: resolve.append(prefix+"previsao_ultrapassagem_meta:"+period)
    if total is not None and len(previous)>=7 and mean(previous)>0:
        baseline=mean(previous)
        if total>baseline*1.2: emit("consumo_acima_esperado","medium","Consumo registrado acima do esperado",
            "O total registrado já supera a média dos dias anteriores com medições.",
            {"value":total,"baseline":baseline,"pct":100*(total/baseline-1),"baseline_days":len(previous),"period":period})
        else: resolve.append(prefix+"consumo_acima_esperado:"+period)
    if forecast and forecast.get("status")=="ok":
        bill=(forecast.get("forecast") or {}).get("bill")
        if bill: emit("previsao_conta_disponivel","low","Previsão da conta disponível",
            "Há uma estimativa disponível; o valor final depende da cobrança da concessionária.",
            {"estimate":bill.get("estimated_value"),"base":bill.get("base"),"period":period[:7]},scope=period[:7])
    if habits and history:
        hours={}
        for point in history:
            hour=point.window_started_at.astimezone(ZoneInfo(zone)).hour
            hours[hour]=hours.get(hour,0)+point.consumption_liters
        peak=max(hours,key=hours.get)
        matching=[h for h in habits if str(h.get("start_time", ""))[:2].isdigit() and int(str(h["start_time"])[:2])==peak]
        if matching: emit("dica_personalizada","low","Confira os hábitos próximos do pico de consumo",
            "Há hábitos cadastrados próximos ao horário de maior consumo registrado. A coincidência não confirma a causa.",
            {"peak_hour":peak,"registered_habits":len(matching),"period":period})
    # O período anterior deixa de estar ativo; o histórico permanece consultável.
    yesterday=(today-timedelta(days=1)).isoformat()
    for kind in ["limite_ultrapassado","previsao_ultrapassagem_meta","consumo_acima_esperado","dica_personalizada"]:
        resolve.append(prefix+kind+":"+yesterday)
    return result,resolve
