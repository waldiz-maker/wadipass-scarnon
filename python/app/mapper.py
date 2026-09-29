from __future__ import annotations

import re
from collections import defaultdict
from .config import PRODUCT_CATALOG, PRODUCT_ORDER


def norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^0-9a-z가-힣]", "", s)
    return s

ALIASES = {
    "submitted_at": ["submitted_at", "received_at", "timestamp", "타임스탬프", "응답일시", "제출시각", "제출일시", "제출시간"],
    "response_id": ["response_id", "submission_id", "응답id", "응답아이디"],
    "respondent_key": ["respondent_key", "내부응답자키", "응답자키"],
    "panel_id": ["panel_id", "패널id", "패널아이디", "패널 ID"],
    "session_id": ["session_id", "세션id", "세션아이디"],
    "record_type": ["record_type", "레코드유형"],
    "event_type": ["event_type", "이벤트유형"],
    "product_id": ["product_id", "상품번호", "상품 번호", "제품id", "제품아이디", "프로젝트id"],
    "product_name": ["product_name", "상품명", "제품명", "프로젝트명"],
    "category": ["category", "카테고리", "제품카테고리"],
    "reference_price": ["reference_price", "펀딩가", "예정가격", "판매예정가", "예정판매가", "제품가격"],
    "age_group": ["age_group", "연령대", "연령"],
    "gender": ["gender", "성별"],
    "questionnaire_type": ["questionnaire_type", "설문유형", "설문 유형"],
    "q1": ["q1_response", "q1응답", "q1 펀딩 참여 여부", "q1"],
    "q2": ["q2_response", "q2응답", "q2 응답", "q2"],
    "q3": ["q3_response", "q3_purchase_intent", "q3응답", "q3 응답", "q3 펀딩 참여 의향", "q3펀딩참여의향", "펀딩 참여 의향", "구매의향", "q3"],
    "q4": ["q4_response", "q4응답", "q4 매력 요소", "q4매력요소", "q4"],
    "q5": ["q5_response", "q5응답", "q5 구매에 필요한 추가정보", "q5구매에필요한추가정보", "q5"],
    "q6": ["q6_response", "q6응답", "q6 구매를 망설이는 요소", "q6구매를망설이는요소", "q6"],
    "q7": ["q7_response", "q7응답", "q7 자유의견", "q7자유의견", "q7"],
}


def auto_map(headers: list[str]) -> dict[str, str | None]:
    normalized = {h: norm(h) for h in headers}
    result: dict[str, str | None] = {}
    used = set()
    for canon, aliases in ALIASES.items():
        alias_norms = [norm(a) for a in aliases]
        chosen = None
        for h, nh in normalized.items():
            if h in used: continue
            if nh in alias_norms:
                chosen = h; break
        if chosen is None:
            for an in sorted(alias_norms, key=len, reverse=True):
                if len(an) < 2: continue
                for h, nh in normalized.items():
                    if h in used: continue
                    if an in nh or (len(nh) >= 5 and nh in an):
                        chosen = h; break
                if chosen: break
        result[canon] = chosen
        if chosen: used.add(chosen)
    return result


def _fallback_value(raw: dict, canon: str):
    aliases = [norm(x) for x in ALIASES.get(canon, [])]
    # 1) exact normalized alias first
    for k, v in raw.items():
        if str(v or "").strip() and norm(k) in aliases:
            return v
    # 2) then a conservative partial match (avoid one-character matches)
    for alias in sorted(aliases, key=len, reverse=True):
        if len(alias) < 3:
            continue
        for k, v in raw.items():
            nk = norm(k)
            if str(v or "").strip() and (alias in nk or (len(nk) >= 5 and nk in alias)):
                return v
    return ""

def canonicalize_rows(rows: list[dict], mapping: dict[str, str | None]) -> list[dict]:
    out=[]
    for raw in rows:
        c={}
        for k,h in mapping.items():
            v = raw.get(h,"") if h else ""
            if not str(v or "").strip():
                v = _fallback_value(raw, k)
            c[k]=v
        c["_raw"]=raw
        out.append(c)
    return out


def split_multi(value) -> list[str]:
    if value is None: return []
    if isinstance(value,(list,tuple)): return [str(x).strip() for x in value if str(x).strip()]
    s=str(value).strip().strip("[]")
    if not s: return []
    parts=re.split(r"\s*(?:\||;|\n)\s*",s)
    if len(parts)==1 and "," in s:
        parts=re.split(r"\s*,\s*",s)
    return [p.strip(" '\"\t") for p in parts if p.strip(" '\"\t")]


def clean_product_id(value: str) -> str:
    s=str(value or "").strip()
    m=re.search(r"\d+",s)
    return m.group(0) if m else s


def group_projects(rows: list[dict]) -> dict[str,list[dict]]:
    groups={pid:[] for pid in PRODUCT_ORDER}
    for r in rows:
        pid=clean_product_id(r.get("product_id"))
        if pid in groups:
            r["product_id"]=pid
            groups[pid].append(r)
    return groups


def looks_like_survey(mapping: dict[str,str|None]) -> bool:
    return bool(mapping.get("product_id") and mapping.get("q3") and (mapping.get("q4") or mapping.get("q5") or mapping.get("q6")))
