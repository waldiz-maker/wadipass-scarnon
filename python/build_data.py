from __future__ import annotations
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))

# Never persist CI secrets to settings.json. app.config reads env variables first.
from app.sheets import refresh, snapshot, status
from app.insights import analyze_project
from app.market import get_market_data

PROJECT_KEY='11'  # SCARNON
OUT=ROOT/'data'
OUT.mkdir(parents=True,exist_ok=True)

def dump(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    result=refresh(force=True)
    if not result.get('ok'):
        raise RuntimeError('Google Sheet refresh failed: '+str(result.get('error') or result))
    snap=snapshot()
    projects=snap.get('projects') or {}
    rows=projects.get(PROJECT_KEY) or []
    if not rows:
        raise RuntimeError('SCARNON(project 11) survey rows were not found.')
    report=analyze_project(PROJECT_KEY, rows, snap.get('funding_rows',[]) if snap.get('funding_ok') else None)
    market=get_market_data(PROJECT_KEY, force=True)
    st=status()
    st.update({
        'ok': True,
        'build_mode':'github-actions-static',
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'refresh_seconds':900,
    })
    dump('scarnon.json',report)
    dump('market.json',market)
    dump('status.json',st)
    print(f'Built SCARNON report: {len(rows)} survey rows')
    print('Market connected:', bool(market.get('connected')))

if __name__=='__main__':
    main()
