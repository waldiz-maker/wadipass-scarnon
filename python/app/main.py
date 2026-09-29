from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from .config import load_settings
from .sheets import start_background, refresh, snapshot, status
from .insights import analyze_project, admin_overview, maker_token, resolve_token
from .market import get_market_data

BASE=Path(__file__).resolve().parents[1]
WEB=BASE/"web"

app=FastAPI(title="WADIPASS V15.2 NAVER Market Intelligence",version="15.2",docs_url=None,redoc_url=None)

@app.on_event("startup")
def _startup():
    start_background()

@app.get("/")
def root():
    return RedirectResponse("/admin")

@app.get("/admin")
def admin_page():
    return FileResponse(WEB/"admin.html",media_type="text/html; charset=utf-8")

@app.get("/maker")
def maker_page():
    return FileResponse(WEB/"maker.html",media_type="text/html; charset=utf-8")


@app.get("/static/{name}")
def static_file(name: str):
    if name not in {"common.css","common.js","DESIGN_NOTES_KO.txt"}: raise HTTPException(404,"not found")
    media = "text/css; charset=utf-8" if name.endswith(".css") else "application/javascript; charset=utf-8"
    return FileResponse(WEB/name, media_type=media)

@app.get("/health")
def health():
    s=status(); settings=load_settings()
    return {"ok":True,"version":"15.2-pdf-readability-links","sheet_ok":s.get("ok"),"last_success":s.get("last_success"),"refresh_seconds":settings["refresh_seconds"],"target_sample_per_product":settings["target_sample_per_product"]}

@app.get("/api/status")
def api_status():
    return {**status(),"settings":{"refresh_seconds":load_settings()["refresh_seconds"],"target_sample_per_product":load_settings()["target_sample_per_product"]}}

@app.post("/api/refresh")
def api_refresh():
    return refresh(force=True)

@app.get("/api/admin/overview")
def api_overview():
    snap=snapshot()
    return {**admin_overview(snap.get("projects",{}), snap.get("funding_rows",[]) if snap.get("funding_ok") else None),"sync":{k:v for k,v in snap.items() if k not in {"rows","projects"}}}

@app.get("/api/admin/project/{project_key}")
def api_project(project_key:str):
    snap=snapshot(); projs=snap.get("projects",{})
    if project_key not in projs: raise HTTPException(404,"프로젝트를 찾을 수 없습니다.")
    return analyze_project(project_key,projs[project_key], snap.get("funding_rows",[]) if snap.get("funding_ok") else None)

@app.get("/api/admin/schema")
def api_schema():
    snap=snapshot()
    return {"headers":snap.get("headers",[]),"mapping":snap.get("mapping",{}),"row_count":snap.get("row_count",0),"source":snap.get("source"),"error":snap.get("error")}

@app.get("/api/admin/maker-link/{project_key}")
def api_maker_link(project_key:str):
    snap=snapshot(); projs=snap.get("projects",{})
    if project_key not in projs: raise HTTPException(404,"프로젝트를 찾을 수 없습니다.")
    token=maker_token(project_key)
    return {"project_key":project_key,"token":token,"path":f"/maker?token={token}"}

@app.get("/api/maker/project")
def api_maker_project(token:str):
    snap=snapshot(); projs=snap.get("projects",{})
    key=resolve_token(token,projs)
    if not key: raise HTTPException(403,"유효하지 않은 메이커 링크입니다.")
    data=analyze_project(key,projs[key], snap.get("funding_rows",[]) if snap.get("funding_ok") else None)
    # Maker receives aggregate only. No raw rows / source schema / other project names.
    return data

@app.get("/api/maker/market")
def api_maker_market(token:str, force:bool=False):
    snap=snapshot(); projs=snap.get("projects",{})
    key=resolve_token(token,projs)
    if not key: raise HTTPException(403,"유효하지 않은 메이커 링크입니다.")
    return get_market_data(key, force=force)
