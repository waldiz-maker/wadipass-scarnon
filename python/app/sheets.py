from __future__ import annotations

import csv, io, json, threading, time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
import requests

from .config import load_settings, derive_csv_urls, sheet_id, SAMPLE_PATH, PRODUCT_ORDER
from .mapper import auto_map, canonicalize_rows, group_projects, looks_like_survey

_lock=threading.RLock()
_state:dict[str,Any]={
    "ok":False,"last_attempt":None,"last_success":None,"source":None,"source_tab":None,"error":None,
    "headers":[],"mapping":{},"rows":[],"projects":{k:[] for k in PRODUCT_ORDER},"row_count":0,
    "funding_rows":[],"funding_ok":False,"funding_error":None,"funding_count":0,"refresh_seconds":10
}
_started=False; _stop=threading.Event()

def _now(): return datetime.now(timezone.utc).isoformat()

def _parse_csv(text:str):
    text=text.lstrip("\ufeff")
    reader=csv.DictReader(io.StringIO(text))
    headers=[h or "" for h in (reader.fieldnames or [])]
    rows=[]
    for row in reader:
        if not any(str(v or "").strip() for v in row.values()): continue
        rows.append({str(k or "").strip():("" if v is None else str(v).strip()) for k,v in row.items()})
    return headers,rows

def _fetch_csv(url:str):
    r=requests.get(url,timeout=15,headers={"User-Agent":"WADIPASS/13.0"}); r.raise_for_status()
    ctype=(r.headers.get("content-type") or "").lower(); text=r.text
    if "text/html" in ctype or text.lstrip().lower().startswith("<!doctype html"):
        raise RuntimeError("Google Sheet CSV를 읽지 못했습니다. 공유/게시 권한을 확인하세요.")
    return _parse_csv(text)

def _fetch_json(url:str):
    r=requests.get(url,timeout=15,headers={"User-Agent":"WADIPASS/13.0"}); r.raise_for_status(); data=r.json()
    rows=(data.get("rows") or data.get("data") or data.get("responses") or []) if isinstance(data,dict) else data
    if not isinstance(rows,list): raise RuntimeError("JSON 배열을 찾지 못했습니다.")
    clean=[x for x in rows if isinstance(x,dict)]
    headers=list(dict.fromkeys(str(k) for row in clean for k in row.keys()))
    return headers,[{str(k):"" if v is None else (json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)) for k,v in row.items()} for row in clean]

def _fetch_local(): return _parse_csv(SAMPLE_PATH.read_text(encoding="utf-8-sig"))

def _survey_only(rows:list[dict]):
    out=[]
    for r in rows:
        pid=str(r.get("product_id") or "").strip()
        if pid not in PRODUCT_ORDER:
            continue
        # Q3가 일시적으로 비어 있어도 다른 실제 설문 응답이 있으면 프로젝트 데이터에는 포함합니다.
        # 구매의향은 별도로 유효 응답 수를 표시해 0%로 오해하지 않게 합니다.
        survey_signal = any(str(r.get(k) or "").strip() for k in ("q1","q2","q3","q4","q5","q6","q7"))
        if not survey_signal:
            continue
        out.append(r)
    return out

def _fetch_funding_sheet(sheet_url:str):
    sid=sheet_id(sheet_url)
    if not sid: return [], False, "Google Sheet ID를 찾지 못했습니다."
    url=f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet={quote('funding_participation')}"
    try:
        _,rows=_fetch_csv(url)
        clean=[]
        for r in rows:
            pid=str(r.get("product_id") or r.get("상품 번호") or "").strip()
            if pid not in PRODUCT_ORDER: continue
            clean.append({
                "product_id":pid,
                "participant_key":str(r.get("participant_key") or r.get("respondent_key") or r.get("내부 응답자키") or "").strip(),
                "panel_id":str(r.get("panel_id") or "").strip(),
                "session_id":str(r.get("session_id") or "").strip(),
                "product_name":str(r.get("product_name") or "").strip(),
                "funding_intent":str(r.get("funding_intent") or "").strip(),
            })
        return clean, True, None
    except Exception as e:
        return [], False, str(e)

def refresh(force:bool=False)->dict:
    settings=load_settings(); minimum=max(10,int(settings.get("refresh_seconds",10)))
    with _lock:
        _state["refresh_seconds"]=minimum
        if not force and _state.get("last_attempt_epoch") and time.time()-_state["last_attempt_epoch"]<minimum: return status()
        _state["last_attempt"]=_now(); _state["last_attempt_epoch"]=time.time()
    candidates=[]; errors=[]
    if settings.get("demo_mode"): candidates.append(("LOCAL_DEMO","LOCAL_DEMO",""))
    endpoint=str(settings.get("data_endpoint") or "").strip()
    if endpoint: candidates.append(("CUSTOM_ENDPOINT","직접 엔드포인트",endpoint))
    sheet_url=str(settings.get("google_sheet_url") or "").strip()
    for tab,url in derive_csv_urls(sheet_url): candidates.append(("GOOGLE_SHEETS_CSV",tab,url))
    headers=[]; raw_rows=[]; source=None; source_tab=None; mapping={}
    for typ,tab,url in candidates:
        try:
            if typ=="LOCAL_DEMO": h,rr=_fetch_local()
            elif typ=="CUSTOM_ENDPOINT":
                try: h,rr=_fetch_json(url)
                except Exception: h,rr=_fetch_csv(url)
            else: h,rr=_fetch_csv(url)
            m=auto_map(h)
            if not looks_like_survey(m): raise RuntimeError("설문 분석 열(Q3~Q6/상품 번호)을 찾지 못해 이 탭은 건너뜁니다.")
            headers,raw_rows,mapping=h,rr,m; source=(typ if typ=="LOCAL_DEMO" else url); source_tab=tab; break
        except Exception as e: errors.append(f"{tab}: {e}")
    if source is None:
        with _lock:
            _state["ok"]=False; _state["error"]=" | ".join(errors) if errors else "데이터 소스를 찾지 못했습니다."
        return status()
    rows=_survey_only(canonicalize_rows(raw_rows,mapping)); projects=group_projects(rows)
    funding_rows=[]; funding_ok=False; funding_error=None
    if settings.get("demo_mode"):
        funding_error="데모 모드에서는 행동 데이터가 별도 제공되지 않습니다."
    else:
        funding_rows,funding_ok,funding_error=_fetch_funding_sheet(sheet_url)
    with _lock:
        _state.update({"ok":True,"last_success":_now(),"source":source,"source_tab":source_tab,"error":None,
                       "headers":headers,"mapping":mapping,"rows":rows,"projects":projects,"row_count":len(rows),
                       "funding_rows":funding_rows,"funding_ok":funding_ok,"funding_error":funding_error,"funding_count":len(funding_rows)})
    return status()

def snapshot()->dict:
    with _lock:
        return {**{k:v for k,v in _state.items() if k not in {"rows","projects","funding_rows","last_attempt_epoch"}},
                "rows":list(_state.get("rows",[])),"projects":{k:list(v) for k,v in _state.get("projects",{}).items()},
                "funding_rows":list(_state.get("funding_rows",[]))}

def status()->dict:
    with _lock: return {k:v for k,v in _state.items() if k not in {"rows","projects","funding_rows","last_attempt_epoch"}}

def _loop():
    while not _stop.is_set():
        try: refresh(force=True)
        except Exception: pass
        _stop.wait(max(10,int(load_settings().get("refresh_seconds",10))))

def start_background():
    global _started
    if _started:return
    _started=True; refresh(force=True)
    threading.Thread(target=_loop,name="wadipass-sheet-sync",daemon=True).start()
