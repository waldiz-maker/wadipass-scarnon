from __future__ import annotations

import hashlib, hmac, math, re
from collections import Counter, defaultdict
from statistics import mean
from .config import load_settings, PRODUCT_CATALOG, PRODUCT_ORDER
from .mapper import split_multi


TARGET_RANK_MIN_BASE = 30  # 주요 타깃 순위는 집단별 유효응답 30명 이상부터 반영

def _pct(n,d): return round(100*n/d,1) if d else 0.0

def _safe_num(v):
    try:
        s=re.sub(r"[^0-9.-]","",str(v or "")); x=float(s); return x if math.isfinite(x) else None
    except Exception:return None

def _intent(v):
    """Legacy 1~5 parser. Kept only for older data compatibility."""
    s=str(v or "").strip()
    if not s:
        return None
    m=re.search(r"(?<!\d)([1-5])(?!\d)",s)
    if m:
        return int(m.group(1))
    circ={"①":1,"②":2,"③":3,"④":4,"⑤":5}
    for ch,n in circ.items():
        if ch in s:
            return n
    lut=[
        ("전혀 참여하고 싶지",1),("전혀 참여하지 않",1),("참여 의향이 낮",2),
        ("보통",3),("참여 의향 높",4),("참여해보고 싶",4),("매우 참여",5),
        ("펀딩에 참여하겠다",5),("참여하겠다",5),("yes",5),
        ("펀딩에 참여하지 않겠다",1),("참여하지 않겠다",1),("no",1),
    ]
    low=s.lower()
    for k,n in lut:
        if k in low:
            return n
    return None


def _interest(v):
    """Current survey Q1: 펀딩 참여 여부 (참여하겠다 / 참여하지 않겠다)."""
    s=str(v or "").strip().lower()
    if not s:
        return None
    # negative first because '참여하지 않겠다' contains '참여하겠다' partially in some loose matches
    neg=("참여하지 않겠다","참여하지않겠다","참여 안","참여안","no","아니오")
    if any(k in s for k in neg):
        return False
    pos=("펀딩에 참여하겠다","참여하겠다","참여 하겠다","yes","예")
    if any(k in s for k in pos):
        return True
    # old 1~5 values are accepted as fallback: 4~5=interest, 1~2=no, 3=unknown
    score=_intent(v)
    if score is not None:
        if score>=4: return True
        if score<=2: return False
    return None


def _interest_dist(rows):
    yes=no=0
    for r in rows:
        v=_interest(r.get("q1"))
        if v is True: yes+=1
        elif v is False: no+=1
    valid=yes+no
    return [
        {"label":"참여하겠다","count":yes,"share":_pct(yes,valid)},
        {"label":"참여하지 않겠다","count":no,"share":_pct(no,valid)},
    ], valid, yes, no

def _row_key(r): return str(r.get("respondent_key") or r.get("response_id") or r.get("session_id") or r.get("panel_id") or "").strip()

def _dedup(rows):
    seen={}; loose=[]
    for i,r in enumerate(rows):
        k=_row_key(r)
        if k:seen[k]=(i,r)
        else:loose.append((i,r))
    vals=loose+list(seen.values()); vals.sort(key=lambda x:x[0]); return [r for _,r in vals]

def _stage(n,target):
    """Final-sample mode: data collection is closed; target/progress stages are no longer user-facing."""
    return {
        "code":"FINAL_SAMPLE",
        "label":"최종 표본",
        "note":"데이터 수집이 종료된 최종 표본을 기준으로 분석합니다. 표본이 적은 하위 집단은 참고값으로 표시합니다.",
        "progress":100.0,
        "confidence":"최종",
    }

def _count(rows,field):
    c=Counter(str(r.get(field) or "").strip() for r in rows); c.pop("",None); return c

def _is_hidden_gender(v):
    """성별 시각화에서 무응답/응답거부 계열 값은 제외합니다."""
    s=str(v or "").strip()
    if not s:
        return True
    compact=re.sub(r"\s+","",s).lower()
    exact={
        "응답하지않음","응답안함","미응답","무응답","선택안함","선택하지않음",
        "응답거부","답변하지않음","답변안함","미선택","없음","-","nan","none","null"
    }
    return compact in exact or "응답하지않" in compact or "선택하지않" in compact or "답변하지않" in compact

def _gender_counter(rows):
    c=Counter()
    for r in rows:
        v=str(r.get("gender") or "").strip()
        if not _is_hidden_gender(v):
            c[v]+=1
    return c

def _gender_valid_n(rows):
    return sum(_gender_counter(rows).values())

def _multi(rows,field):
    c=Counter()
    for r in rows:
        for x in set(split_multi(r.get(field))): c[x]+=1
    return c

def _top_respondent(counter,nresp,limit=8): return [{"label":k,"count":v,"share":_pct(v,nresp)} for k,v in counter.most_common(limit)]
def _single_top(counter,nresp,limit=8): return _top_respondent(counter,nresp,limit)

def _intent_dist(rows):
    dist, valid, yes, no = _interest_dist(rows)
    # keep second return value list-like for older callers; booleans are enough for counts
    flags=[True]*yes+[False]*no
    return dist, flags

def _cost_selected(r):
    vals=split_multi(r.get("q6")); kws=("가격","비용","유지비","교체비","추가 구매")
    return any(any(k in x for k in kws) for x in vals)

def _text_topics(rows):
    groups={"가격·비용":["가격","비싸","비용","유지비"],"성능·품질":["성능","품질","내구","센서","타격","소음"],"사용감·적합성":["그립","무게","크기","적합","사용감","손목"],"신뢰·안전":["안전","신뢰","성분","인증","걱정"],"관리·세척":["세척","관리","필터","캡슐","교체"],"디자인·휴대":["디자인","휴대","예쁘","색상"]}
    texts=[_clean_comment(r.get("q7")) for r in rows]
    texts=[t for t in texts if t]
    out=[]
    for label,kws in groups.items():
        ex=[t for t in texts if any(k in t for k in kws)]
        if ex: out.append({"label":label,"count":len(ex),"share":_pct(len(ex),len(texts)),"examples":ex[:3]})
    out.sort(key=lambda x:x["count"],reverse=True)
    return {"n":len(texts),"topics":out}

def _clean_comment(text):
    s=str(text or "").strip()
    if not s:
        return ""
    # 메이커 화면에 자유의견을 노출하되, 실수로 적힌 연락처·이메일은 마스킹합니다.
    s=re.sub(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[연락처 숨김]", s)
    s=re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[이메일 숨김]", s)
    return s

def _is_substantive_comment(text):
    """대표 코멘트에는 '네/없음/좋아요' 같은 단답을 제외합니다.
    모든 원문은 voice_of_customer에 그대로 남고, 이 필터는 요약 카드 선별에만 사용합니다.
    """
    s=_clean_comment(text)
    if not s:
        return False
    compact=re.sub(r"[\s.!?~ㅋㅋㅎㅠㅜ]+", "", s).lower()
    trivial={
        "네","예","넵","아니요","아뇨","없음","없어요","없습니다","딱히없음","딱히없어요",
        "모름","모르겠음","모르겠어요","잘모르겠음","좋아요","좋습니다","좋음","괜찮아요",
        "괜찮습니다","괜찮음","보통","그냥그래요","그냥그럼","x","xx","무","패스"
    }
    if compact in trivial:
        return False
    specific=(
        "가격","비싸","비용","성능","품질","내구","소재","그립","무게","밸런스","규격","크기",
        "사용","불편","소음","센서","트래킹","배터리","호환","휴대","디자인","색상","후기","영상",
        "비교","차이","차별","신뢰","안전","성분","인증","세척","필터","캡슐","교체","관리","AS",
        "타격","스윙","구매","필요","부담","걱정","궁금","확인","원해","좋겠","아쉽","때문"
    )
    if len(s)>=12:
        return True
    return len(s)>=6 and any(k.lower() in s.lower() for k in specific)


def _comment_score(text):
    s=_clean_comment(text)
    if not _is_substantive_comment(s):
        return -1
    kws=(
        "가격","비용","성능","품질","내구","소재","그립","무게","밸런스","규격","사용","불편","소음",
        "배터리","호환","후기","영상","비교","차별","신뢰","안전","세척","필터","교체","관리","구매",
        "필요","부담","걱정","궁금","좋겠","아쉽","때문"
    )
    score=min(len(s),120)/5
    score+=sum(5 for k in kws if k in s)
    if any(x in s for x in ("왜","때문","하지만","다만","그래서","이면","하면","했으면","좋겠")):
        score+=8
    if len(s)>=25:
        score+=8
    return score


def _comments(rows, limit=6):
    # 대표 코멘트는 최신순 단순 추출이 아니라 구체성·설명력을 우선합니다.
    # 단답은 대표 코멘트에서 제외하지만 '모든 자유의견'에는 그대로 보존됩니다.
    candidates=[]; seen=set()
    for order,r in enumerate(reversed(rows)):
        t=_clean_comment(r.get("q7"))
        if not t or t in seen or not _is_substantive_comment(t):
            continue
        seen.add(t)
        candidates.append((_comment_score(t), -order, t))
    candidates.sort(reverse=True)
    return [x[2] for x in candidates[:limit]]


def _comment_theme_summary(rows, limit=4):
    """자유의견 원문에서 반복적으로 언급된 주제를 집계합니다.
    한 코멘트가 여러 주제를 언급할 수 있으므로 주제별 비율의 합은 100%가 아닐 수 있습니다.
    """
    groups={
        "가격·비용":["가격","비싸","비용","가성비","유지비","추가 구매"],
        "성능·품질":["성능","품질","내구","소재","센서","타격","정확","소음"],
        "사용감·적합성":["그립","무게","밸런스","크기","규격","적합","사용감","손목","착용"],
        "비교·차별성":["비교","차이","차별","기존 제품","다른 제품","경쟁"],
        "후기·검증":["후기","리뷰","영상","테스트","실사용","사용자","선수","검증"],
        "신뢰·안전":["안전","신뢰","성분","인증","AS","교환"],
        "관리·유지":["세척","관리","필터","캡슐","교체","배터리","호환"],
        "디자인·휴대":["디자인","색상","예쁘","휴대","보관"]
    }
    texts=[]
    for r in rows:
        t=_clean_comment(r.get("q7"))
        if t and _is_substantive_comment(t):
            texts.append(t)
    topics=[]
    for label,kws in groups.items():
        matched=[t for t in texts if any(k.lower() in t.lower() for k in kws)]
        if matched:
            representative=max(matched,key=_comment_score)
            topics.append({"label":label,"count":len(matched),"share":_pct(len(matched),len(texts)),"example":representative})
    topics.sort(key=lambda x:(-x["count"],-x["share"],x["label"]))
    return {"comment_n":len(texts),"topics":topics[:limit]}

def _all_comment_records(rows):
    """모든 자유의견을 빠짐없이 반환합니다.
    동일한 문구가 여러 응답자에게서 반복되어도 각각의 응답으로 보존합니다.
    """
    items=[]
    group_counts=Counter()
    for r in reversed(rows):
        text=_clean_comment(r.get("q7"))
        if not text:
            continue
        iv=_interest(r.get("q1"))
        need=_purchase_need(r.get("q3"))
        if iv is True:
            group="관심고객"
        elif iv is False and need is True:
            group="설득 가능 고객"
        elif iv is False and need is False:
            group="비타깃 가능 고객"
        elif iv is False:
            group="비관심고객"
        else:
            group="관심도 미분류"
        gender=str(r.get("gender") or "").strip()
        if _is_hidden_gender(gender):
            gender=""
        item={
            "text":text,
            "group":group,
            "age_group":str(r.get("age_group") or "").strip(),
            "gender":gender,
            "context":str(r.get("q2") or "").strip(),
            "need":str(r.get("q3") or "").strip(),
        }
        items.append(item)
        group_counts[group]+=1
    return {
        "count":len(items),
        "items":items,
        "groups":[{"label":k,"count":v,"share":_pct(v,len(items))} for k,v in group_counts.most_common()]
    }

def _segment_map(rows):
    # Current survey: Q2 = product usage/context, Q1 = funding participation intent.
    g=defaultdict(list)
    for r in rows:
        seg=str(r.get("q2") or "").strip(); iv=_interest(r.get("q1"))
        if seg and iv is not None:g[seg].append(iv)
    total=sum(len(v) for v in g.values())
    items=[]
    for label,vals in g.items():
        rate=_pct(sum(v is True for v in vals),len(vals))
        # avg_intent retained as compatibility key; value is now participation-intent rate (0~100).
        items.append({"label":label,"count":len(vals),"share":_pct(len(vals),total),"avg_intent":rate,"high_intent_rate":rate})
    return sorted(items,key=lambda x:(-x["high_intent_rate"],-x["count"]))

def _age_intent(rows):
    g=defaultdict(list)
    for r in rows:
        age=str(r.get("age_group") or "").strip(); iv=_interest(r.get("q1"))
        if age and iv is not None:g[age].append(iv)
    return [{"label":k,"count":len(v),"avg_intent":None,"high_intent_rate":_pct(sum(x is True for x in v),len(v))} for k,v in sorted(g.items())]

def _demographic_reaction(rows, field):
    grouped=defaultdict(list)
    for r in rows:
        label=str(r.get(field) or "").strip()
        if field=="gender" and _is_hidden_gender(label):
            continue
        if label:
            grouped[label].append(r)
    out=[]
    for label,items in grouped.items():
        vals=[_interest(r.get("q1")) for r in items]
        vals=[x for x in vals if x is not None]
        barriers=_top_respondent(_multi(items,"q6"),len(items),1)
        attractions=_top_respondent(_multi(items,"q4"),len(items),1)
        evidence=_top_respondent(_multi(items,"q5"),len(items),1)
        out.append({
            "label":label,
            "count":len(items),
            "intent_valid_n":len(vals),
            "avg_intent":None,
            "high_intent_rate":_pct(sum(x is True for x in vals),len(vals)) if vals else None,
            "top_barrier":barriers[0]["label"] if barriers else "-",
            "top_attraction":attractions[0]["label"] if attractions else "-",
            "top_evidence":evidence[0]["label"] if evidence else "-",
        })
    return sorted(out,key=lambda x:(-(x.get("high_intent_rate") if x.get("high_intent_rate") is not None else -1),-x["count"],x["label"]))

def _purchase_need(v):
    """Current survey Q3 = purchase need / current pain or replacement situation."""
    s=str(v or "").strip()
    if not s:
        return None
    neg=("필요 없음","필요없음","필요하지","현재 제품 만족","현재 만족","관리 만족","관련 필요 낮음","만족해서")
    if any(k in s for k in neg):
        return False
    pos=(
        "교체 고려","교체 필요","신규 구매","추가·신규 구매 필요","추가 구매","구매 필요","구매 고려",
        "선물·단체 구매 가능","선물","단체 구매",
        "손목·그립 불편","클릭 소음","트래킹 불편","연결·휴대 불편",
        "급수 불편","구강 관리 고민","둘 다 개선 필요","개선 필요","불편"
    )
    if any(k in s for k in pos):
        return True
    return None

def _top_label(counter, nresp):
    arr=_top_respondent(counter,nresp,1)
    return arr[0] if arr else None

def _group_profile(rows, label):
    n=len(rows)
    interests=[_interest(r.get("q1")) for r in rows]
    interests=[x for x in interests if x is not None]
    age=_top_label(_count(rows,"age_group"),n)
    gender_n=_gender_valid_n(rows)
    gender=_top_label(_gender_counter(rows),gender_n)
    context=_top_label(_count(rows,"q2"),n)
    need=_top_label(_count(rows,"q3"),n)
    attraction=_top_label(_multi(rows,"q4"),n)
    evidence=_top_label(_multi(rows,"q5"),n)
    barrier=_top_label(_multi(rows,"q6"),n)
    need_known=[_purchase_need(r.get("q3")) for r in rows]
    need_true=sum(x is True for x in need_known)
    need_valid=sum(x is not None for x in need_known)
    return {
        "label":label,"count":n,
        "avg_intent":None,
        "high_intent_rate":_pct(sum(x is True for x in interests),len(interests)) if interests else None,
        "purchase_need_rate":_pct(need_true,need_valid) if need_valid else None,
        "purchase_need_valid_n":need_valid,
        "top_age":age,"top_gender":gender,"top_context":context,"top_need":need,
        "top_attraction":attraction,"top_evidence":evidence,"top_barrier":barrier,
        "attractions":_top_respondent(_multi(rows,"q4"),n,5),
        "evidence":_top_respondent(_multi(rows,"q5"),n,5),
        "barriers":_top_respondent(_multi(rows,"q6"),n,5),
        "q1":_single_top(_count(rows,"q1"),n,5),
        "q2":_single_top(_count(rows,"q2"),n,5),
        "q3":_single_top(_count(rows,"q3"),n,5),
        "comments":_comments(rows,6),
    }



def _target_feedback(rows, field, all_rows=None, positive=True):
    """타깃별 피드백 요약.
    순위는 단순 관심고객 수가 아니라 '해당 인구집단 안에서의 관심/비관심 비율'을 우선합니다.
    """
    grouped=defaultdict(list)
    for r in rows:
        label=str(r.get(field) or "").strip()
        if field=="gender" and _is_hidden_gender(label):
            continue
        if label:
            grouped[label].append(r)

    # 분모: 같은 연령/성별에서 Q1에 유효하게 응답한 전체 사람 수
    base=Counter()
    source=all_rows if all_rows is not None else rows
    for r in source:
        label=str(r.get(field) or "").strip()
        if field=="gender" and _is_hidden_gender(label):
            continue
        if label and _interest(r.get("q1")) is not None:
            base[label]+=1

    segment_total=_gender_valid_n(rows) if field=="gender" else len(rows)
    out=[]
    for label,items in grouped.items():
        n=len(items)
        base_n=base.get(label,n)
        rate=_pct(n,base_n) if base_n else 0
        out.append({
            "label":label,
            "count":n,
            "base_count":base_n,
            "share":_pct(n,segment_total) if segment_total else 0,
            "segment_rate":rate,
            "interest_rate":rate if positive else None,
            "noninterest_rate":rate if not positive else None,
            "sample_flag":"충분" if base_n>=TARGET_RANK_MIN_BASE else "참고" if base_n>=10 else "표본 부족",
            "ranking_eligible": base_n>=TARGET_RANK_MIN_BASE,
            "top_context":_top_label(_count(items,"q2"),n),
            "top_need":_top_label(_count(items,"q3"),n),
            "top_attraction":_top_label(_multi(items,"q4"),n),
            "top_evidence":_top_label(_multi(items,"q5"),n),
            "top_barrier":_top_label(_multi(items,"q6"),n),
            "comments":_comments(items,3),
        })
    # 주요 타깃은 집단별 유효응답 30명 이상에서만 선정하고, 그 안에서 비율을 우선해 순위화합니다.
    # 30명 미만 집단도 참고용 데이터로 남기되 주요 순위 뒤로 보냅니다.
    return sorted(out,key=lambda x:(not x.get("ranking_eligible",False),-x["segment_rate"],-x["base_count"],x["label"]))

def _interest_segments(rows):
    high=[]; low=[]; convertible=[]; non_target=[]; unknown=[]
    for r in rows:
        iv=_interest(r.get("q1"))
        if iv is True:
            high.append(r)
        elif iv is False:
            low.append(r)
            need=_purchase_need(r.get("q3"))
            if need is True: convertible.append(r)
            elif need is False: non_target.append(r)
        else:
            unknown.append(r)
    valid=len(high)+len(low)
    profiles={
        "high":_group_profile(high,"관심군 · Q1 펀딩 참여 의향 있음"),
        "neutral":_group_profile([],"중립군 · 현재 설문에는 별도 중립 선택지 없음"),
        "low":_group_profile(low,"비관심군 · Q1 펀딩 참여 의향 없음"),
        "convertible":_group_profile(convertible,"전환 가능군 · 참여 의향 낮음 + 구매 필요/문제 있음"),
        "non_target":_group_profile(non_target,"비타깃 가능군 · 참여 의향 낮음 + 구매 필요 낮음"),
    }
    for v in profiles.values():
        v["share"]=_pct(v["count"],valid) if valid else 0

    # 메이커가 "관심 있다 → 그들은 누구인가 → 무엇을 말했나" 순서로 볼 수 있도록
    # 관심군 내부의 인구통계 구성과 타깃별 피드백을 함께 반환합니다.
    profiles["high"]["age_distribution"]=_single_top(_count(high,"age_group"),len(high),8)
    profiles["high"]["gender_distribution"]=_single_top(_gender_counter(high),_gender_valid_n(high),6)
    profiles["high"]["age_feedback"]=_target_feedback(high,"age_group",rows,True)
    profiles["high"]["gender_feedback"]=_target_feedback(high,"gender",rows,True)

    profiles["low"]["age_distribution"]=_single_top(_count(low,"age_group"),len(low),8)
    profiles["low"]["gender_distribution"]=_single_top(_gender_counter(low),_gender_valid_n(low),6)
    profiles["low"]["age_feedback"]=_target_feedback(low,"age_group",rows,False)
    profiles["low"]["gender_feedback"]=_target_feedback(low,"gender",rows,False)
    profiles["convertible"]["age_distribution"]=_single_top(_count(convertible,"age_group"),len(convertible),8)
    profiles["convertible"]["gender_distribution"]=_single_top(_gender_counter(convertible),_gender_valid_n(convertible),6)

    return {"valid_n":valid,"unknown_n":len(unknown),**profiles}

def _demographic_reaction_v2(rows, field):
    grouped=defaultdict(list)
    for r in rows:
        label=str(r.get(field) or "").strip()
        if field=="gender" and _is_hidden_gender(label):
            continue
        if label:
            grouped[label].append(r)
    out=[]
    for label,items in grouped.items():
        prof=_group_profile(items,label)
        prof["sample_flag"]="충분" if len(items)>=30 else "참고" if len(items)>=10 else "표본 부족"
        out.append(prof)
    return sorted(out,key=lambda x:(-(x.get("high_intent_rate") if x.get("high_intent_rate") is not None else -1),-x["count"],x["label"]))

def _demographic_insights(items, dimension):
    reliable=[x for x in items if x.get("count",0)>=TARGET_RANK_MIN_BASE and x.get("high_intent_rate") is not None]
    if not reliable:
        return [{"title":f"{dimension}별 주요 타깃 순위 제외", "text":f"최종 표본에서 집단별 유효응답이 {TARGET_RANK_MIN_BASE}명 미만이라 참여의향 순위를 일반화하기 어렵습니다. 해당 집단은 참고값으로만 확인합니다.","level":"참고"}]
    insights=[]
    ranked=sorted(reliable,key=lambda x:(-(x.get("high_intent_rate") or 0),-x.get("count",0)))
    top=ranked[0]
    insights.append({"title":f"{top['label']}에서 펀딩 참여의향이 가장 높음","text":f"참여하겠다 {top['high_intent_rate']:.1f}% · n={top['count']}. 1순위 매력은 '{(top.get('top_attraction') or {}).get('label','-')}'입니다.","level":"발견"})
    barrier_groups=[x for x in reliable if (x.get("top_barrier") or {}).get("label")]
    if barrier_groups:
        # 각 집단의 1순위 장벽 중 비율이 가장 큰 신호
        bg=max(barrier_groups,key=lambda x:(x.get("top_barrier") or {}).get("share",0))
        b=bg.get("top_barrier") or {}
        insights.append({"title":f"{bg['label']}의 핵심 장벽 · {b.get('label','-')}","text":f"이 집단의 {b.get('share',0):.1f}%가 선택했습니다. 같은 전체 평균보다 집단별 차이를 함께 확인하세요.","level":"확인"})
    evidence_groups=[x for x in reliable if (x.get("top_evidence") or {}).get("label")]
    if evidence_groups:
        eg=max(evidence_groups,key=lambda x:(x.get("top_evidence") or {}).get("share",0))
        e=eg.get("top_evidence") or {}
        insights.append({"title":f"{eg['label']}가 가장 원하는 추가정보", "text":f"추가정보 1순위는 '{e.get('label','-')}'이며 선택률은 {e.get('share',0):.1f}%입니다. 상세페이지 보강 우선순위 후보입니다.","level":"확인"})
    return insights[:3]

def _roadmap(stage, n, target, segments, top_attraction=None, top_barrier=None, top_evidence=None, hi_cost=0):
    """메이커가 바로 행동으로 옮길 수 있도록 고객군 데이터와 연결한 출시 전 로드맵."""
    high=segments.get("high",{})
    low=segments.get("low",{})
    conv=segments.get("convertible",{})
    non=segments.get("non_target",{})

    def label(x):
        return (x or {}).get("label") or ""
    def share(x):
        try: return float((x or {}).get("share") or 0)
        except Exception: return 0.0
    def demo_text(profile):
        parts=[]
        age_items=profile.get("age_feedback") or []
        gender_items=profile.get("gender_feedback") or []
        age_rank=next((x for x in age_items if x.get("ranking_eligible")),None)
        gender_rank=next((x for x in gender_items if x.get("ranking_eligible")),None)
        if age_rank:
            parts.append(f"표본 확보 연령 중 관심률 1위 {age_rank.get('label','-')} {float(age_rank.get('segment_rate') or 0):.1f}%")
        elif age_items:
            parts.append("연령별 표본이 적어 주요 타깃 순위 제외")
        if gender_rank:
            parts.append(f"표본 확보 성별 중 관심률 1위 {gender_rank.get('label','-')} {float(gender_rank.get('segment_rate') or 0):.1f}%")
        elif gender_items:
            parts.append("성별 표본이 적어 주요 타깃 순위 제외")
        if label(profile.get("top_context")): parts.append(f"제품과의 관계 {label(profile.get('top_context'))}")
        return " · ".join(parts)

    items=[]

    # 1) 누구를 우선 타깃으로 볼지
    if high.get("count",0)>0:
        demo=demo_text(high)
        items.append({
            "key":"target",
            "title":"핵심 관심고객 타깃 확인",
            "status":"확인",
            "data":f"관심고객 {high['count']}명" + (f" · {demo}" if demo else ""),
            "detail":"최종 표본에서 관심을 보인 고객의 연령·성별·제품 접점을 우선 타깃 후보로 검토하세요. 집단별 유효응답이 적으면 참고값으로만 해석합니다."
        })

    # 2) 이미 먹히는 메시지는 유지
    att=high.get("top_attraction") or top_attraction
    if att:
        items.append({
            "key":"strength",
            "title":"관심고객이 반응한 강점 유지",
            "status":"유지",
            "data":f"{label(att)} · 관심고객 내 {share(att):.1f}% 선택" if high.get("top_attraction") else f"{label(att)} · 전체 응답 {share(att):.1f}% 선택",
            "detail":"이미 반응이 확인된 강점은 상세페이지 수정 과정에서 뒤로 밀리지 않도록 핵심 메시지로 유지하세요."
        })

    # 3) 관심고객의 마지막 장벽과 필요한 정보 연결
    bar=high.get("top_barrier") or top_barrier
    ev=high.get("top_evidence") or top_evidence
    if bar or ev:
        detail_parts=[]
        if bar:
            detail_parts.append(BARRIER_RECS.get(label(bar), f"'{label(bar)}'에 대한 설명과 근거를 보강하세요."))
        if ev:
            detail_parts.append(EVIDENCE_RECS.get(label(ev), f"'{label(ev)}' 정보를 추가하세요."))
        data_parts=[]
        if bar: data_parts.append(f"주요 망설임 {label(bar)} {share(bar):.1f}%")
        if ev: data_parts.append(f"추가로 원하는 정보 {label(ev)} {share(ev):.1f}%")
        items.append({
            "key":"confidence",
            "title":"관심고객의 구매 확신 강화",
            "status":"보완 권장" if max(share(bar),share(ev))>=25 else "확인",
            "data":" · ".join(data_parts),
            "detail":" ".join(detail_parts)
        })

    # 가격 저항이 특히 높을 때만 별도 노출
    if high.get("count",0)>0 and hi_cost>=30:
        items.append({
            "key":"price",
            "title":"관심고객의 가격 설득 보강",
            "status":"보완 권장",
            "data":f"관심고객 중 가격·비용 관련 고민 {hi_cost:.1f}%",
            "detail":"가격을 바로 낮추기보다 현재 가격이 납득되는 성능·구성·리워드 근거를 먼저 강화하세요."
        })

    # 4) 비관심이지만 필요가 있는 사람을 다시 설득
    if conv.get("count",0)>0:
        conv_demo=demo_text(conv)
        cbar=conv.get("top_barrier")
        cev=conv.get("top_evidence")
        detail_parts=[]
        if cbar: detail_parts.append(BARRIER_RECS.get(label(cbar), f"'{label(cbar)}'에 대한 설명과 근거를 보강하세요."))
        if cev: detail_parts.append(EVIDENCE_RECS.get(label(cev), f"'{label(cev)}' 정보를 추가하세요."))
        items.append({
            "key":"convert",
            "title":"설득 가능 고객의 관심 전환",
            "status":"보완 권장",
            "data":f"설득 가능 고객 {conv['count']}명" + (f" · {conv_demo}" if conv_demo else ""),
            "detail":" ".join(detail_parts) if detail_parts else "이 집단이 왜 참여를 망설였는지와 어떤 정보를 요구했는지 확인해 상세페이지의 설득 포인트를 보완하세요."
        })

    # 5) 비타깃에는 자원을 과투입하지 않도록 구분
    if non.get("count",0)>0 and low.get("count",0)>0:
        non_share=_pct(non.get("count",0),low.get("count",0))
        items.append({
            "key":"focus",
            "title":"비타깃 고객과 핵심 타깃 분리",
            "status":"집중",
            "data":f"비타깃 가능 고객 {non['count']}명 · 비관심고객의 {non_share:.1f}%",
            "detail":"제품 필요 자체가 낮은 집단을 모두 설득하려 하기보다 관심고객과 설득 가능 고객에 메시지·광고·상세페이지 자원을 우선 집중하세요."
        })

    return items

def _funding_keys(funding_rows,pid):
    keys=set()
    for r in funding_rows or []:
        if str(r.get("product_id") or "")!=str(pid): continue
        k=str(r.get("participant_key") or r.get("respondent_key") or "").strip()
        if k: keys.add(k)
    return keys

BARRIER_RECS={
"가격 부담":"가격을 바로 낮추기보다 현재 가격이 납득되는 성능·구성·리워드 근거를 상세페이지에서 먼저 강화하세요.",
"성능·품질 확신 부족":"실제 테스트 수치, 사용 영상, 기존 제품과의 비교 근거를 핵심 기능 설명 바로 뒤에 배치하세요.",
"적합 규격 판단 어려움":"길이·무게·밸런스와 사용자 유형별 선택 가이드를 한 화면에서 비교할 수 있게 보강하세요.",
"차별성·신뢰 부족":"경쟁 대안과의 차이를 비교표로 명확히 하고 메이커 전문성·개발 근거를 함께 제시하세요.",
"구매 필요성 낮음":"기능 나열보다 어떤 상황에서 기존 방식의 불편을 해결하는지 사용 시나리오를 상세페이지 앞부분에 강화하세요.",
"그립 적합성 우려":"손 크기·잡는 방식별 실제 그립 사진과 치수 가이드를 추가하세요.",
"성능 차이 불확실":"기존 마우스와 클릭 소음·트래킹·사용감의 체감 차이를 비교 콘텐츠로 보여주세요.",
"연결·배터리 우려":"연결 안정성, 배터리 지속시간, 호환 기기를 실사용 테스트와 함께 명시하세요.",
"교체 필요성 낮음":"교체가 필요한 구체적 상황과 현재 제품 대비 얻는 효익을 앞단에서 분명히 보여주세요.",
"반려동물 적응 우려":"실제 반려동물 사용 영상과 적응 단계 안내를 추가해 사용 가능성을 보여주세요.",
"캡슐 안전성 우려":"캡슐 성분·안전 기준·권장 사용법을 검증 가능한 근거와 함께 상세히 제시하세요.",
"유지비 부담":"필터·캡슐 교체 주기와 월/연 예상 유지비를 명확히 공개하세요.",
"세척 번거로움":"분해-세척-재조립 과정을 단계별 이미지와 예상 소요시간으로 보여주세요.",
}
EVIDENCE_RECS={
"상세 규격·선택 가이드":"규격 비교표와 사용자 유형별 선택 가이드를 추가","타격·스윙 영상":"실제 타격·스윙 영상을 핵심 성능 설명과 연결","성능·내구성·비교":"성능·내구성 테스트와 경쟁 제품 비교표를 추가","사용자·선수 후기":"실제 사용자/선수 사용 후기와 사용 맥락을 추가","메이커·개발·AS":"메이커 전문성, 개발 과정, 교환·AS 기준을 명확히 표시","크기·무게·그립":"실제 치수와 손 크기별 그립 적합성 가이드 추가","클릭 소음 비교":"일반 마우스 대비 클릭 소음 비교 영상 추가","센서·트래킹 테스트":"다양한 표면에서 트래킹 테스트 결과 추가","배터리·호환성":"배터리 지속시간과 기기 호환 정보를 표로 정리","실사용 후기":"장시간 업무·학습 환경 실사용 후기 추가","캡슐 안전·성분":"캡슐 성분·안전성·사용 기준을 증거와 함께 제시","필터 교체·비용":"필터·캡슐 교체주기 및 추가 구매비용 명시","실제 소음·음수":"실제 작동소음과 반려동물 음수 영상을 추가","세척·위생":"분해·세척과 위생관리 과정을 시각화","적합 반려동물":"반려동물 크기별 적합성 및 용량 가이드 추가",
}

def _action_level(share):
    if share>=40:return "높음"
    if share>=25:return "중간"
    return "관찰"

def analyze_project(project_key,raw_rows,funding_rows=None):
    settings=load_settings(); target=settings["target_sample_per_product"]; rows=_dedup(raw_rows); n=len(rows); meta=PRODUCT_CATALOG.get(str(project_key),{})
    stage=_stage(n,target); intent_dist,flags=_intent_dist(rows); valid_intent=len(flags)
    yes_n=sum(x is True for x in flags); no_n=sum(x is False for x in flags)
    high_rate=_pct(yes_n,valid_intent) if valid_intent else None; low_rate=_pct(no_n,valid_intent) if valid_intent else None
    # compatibility key: avg_intent now mirrors Q1 participation-intent rate (0~100), not a 1~5 mean.
    avg_intent=high_rate
    q4=_top_respondent(_multi(rows,"q4"),n); q5=_top_respondent(_multi(rows,"q5"),n); q6=_top_respondent(_multi(rows,"q6"),n); q1=_single_top(_count(rows,"q1"),n); q2=_single_top(_count(rows,"q2"),n); q3=_single_top(_count(rows,"q3"),n)
    cost_n=sum(_cost_selected(r) for r in rows); cost_rate=_pct(cost_n,n); hi=[r for r in rows if _interest(r.get("q1")) is True]; hi_cost=_pct(sum(_cost_selected(r) for r in hi),len(hi)) if hi else 0
    interest_segments=_interest_segments(rows)
    low_rows=[r for r in rows if _interest(r.get("q1")) is False]
    convertible_rows=[r for r in low_rows if _purchase_need(r.get("q3")) is True]
    comment_insights={
        "overall":_comment_theme_summary(rows),
        "interest":_comment_theme_summary(hi),
        "noninterest":_comment_theme_summary(low_rows),
        "convertible":_comment_theme_summary(convertible_rows),
    }
    age_reaction=_demographic_reaction_v2(rows,"age_group")
    gender_reaction=_demographic_reaction_v2(rows,"gender")
    price=_safe_num(rows[-1].get("reference_price")) if rows else None
    if price is None: price=meta.get("reference_price")
    top_barrier=q6[0] if q6 else None; top_evidence=q5[0] if q5 else None; top_attraction=q4[0] if q4 else None

    fkeys=_funding_keys(funding_rows,str(project_key)); funding_count=len(fkeys); funding_available=funding_rows is not None
    funding_rate=_pct(funding_count,n) if funding_available and n else None
    gap=round(high_rate-funding_rate,1) if funding_rate is not None and high_rate is not None else None
    hi_nonfund=[]
    if funding_available:
        for r in hi:
            k=_row_key(r)
            if not k or k not in fkeys: hi_nonfund.append(r)
    nonfund_barriers=_top_respondent(_multi(hi_nonfund,"q6"),len(hi_nonfund),5) if hi_nonfund else []

    actions=[]
    if n<30:
        actions.append({"signal":"참고","status":"최종 표본","title":"전체 표본 수 해석 주의","why":f"최종 분석 응답은 {n}명입니다.","recommendation":"전체 표본 자체가 작으므로 아래 비율은 방향 참고값으로 해석하고, 특히 연령·성별 하위집단은 일반화하지 마세요.","section":"데이터"})
    if top_barrier:
        label=top_barrier["label"]; actions.append({"signal":_action_level(top_barrier["share"]),"status":stage["confidence"],"title":f"구매저항 확인 · {label}","why":f"응답자의 {top_barrier['share']:.1f}%가 이 항목을 구매 고민 요인으로 선택했습니다.","recommendation":BARRIER_RECS.get(label,f"'{label}'에 대한 설명·증거·사용 시나리오를 출시 전 상세페이지에 보강하세요."),"section":"제품/상세페이지"})
    if top_evidence:
        label=top_evidence["label"]; actions.append({"signal":_action_level(top_evidence["share"]),"status":stage["confidence"],"title":f"상세페이지 보강 · {label}","why":f"응답자의 {top_evidence['share']:.1f}%가 구매 전에 이 정보를 더 원했습니다.","recommendation":EVIDENCE_RECS.get(label,f"'{label}' 정보를 실제 근거와 함께 추가하세요."),"section":"상세페이지"})
    if top_attraction:
        actions.append({"signal":"유지","status":stage["confidence"],"title":f"핵심 매력 유지 · {top_attraction['label']}","why":f"응답자의 {top_attraction['share']:.1f}%가 이 요소를 매력 포인트로 선택했습니다.","recommendation":"최종 수정 과정에서도 이 강점이 뒤로 밀리지 않도록 핵심 메시지로 유지하세요.","section":"제품/메시지"})
    if cost_rate>=30:
        actions.append({"signal":_action_level(cost_rate),"status":stage["confidence"],"title":"가격·비용 저항 점검","why":f"전체 응답의 {cost_rate:.1f}%에서 가격 또는 유지비 관련 고민이 나타났습니다. 펀딩 참여 의향이 있는 고객에서도 {hi_cost:.1f}%입니다.","recommendation":"가격 인하를 바로 결정하기보다 가격 대비 가치와 총비용 설명을 먼저 최종 점검하세요.","section":"가격/리워드"})
    if high_rate is None:
        headline=(f"펀딩 참여의향 데이터 연결을 확인 중입니다. 현재 가장 많이 나타난 구매저항은 '{top_barrier['label']}'입니다." if top_barrier else "펀딩 참여의향 데이터 연결을 확인 중입니다.")
    else:
        headline=(f"펀딩 참여의향은 높지만 '{top_barrier['label']}'이 가장 큰 출시 전 확인요인입니다." if high_rate>=60 and top_barrier else f"현재 가장 먼저 확인할 구매저항은 '{top_barrier['label']}'입니다." if top_barrier else "최종 표본에서 제품별 펀딩 참여의향과 구매저항 패턴을 확인합니다.")
    if funding_rate is not None and n>=30:
        if gap is None:
            headline += f" 참여의향 보조 집계율은 {funding_rate:.1f}%입니다."
        else:
            headline += f" 참여의향 보조 집계율은 {funding_rate:.1f}%로, 원응답과의 차이는 {gap:.1f}%p입니다."
    checks=[
        {"label":"펀딩 참여 의향 있음","value":f"{high_rate:.1f}%" if high_rate is not None else "연결 확인","status":"양호" if high_rate is not None and high_rate>=60 else "보완" if high_rate is not None and high_rate>=40 else "점검","note":f"참여의향 응답 {valid_intent}/{n}명"},
        {"label":"참여의향 보조 집계","value":f"{funding_rate:.1f}%" if funding_rate is not None else "연결 대기","status":"관찰","note":f"{funding_count}명 집계" if funding_rate is not None else "집계 시트 확인"},
        {"label":"가장 필요한 추가정보","value":top_evidence["label"] if top_evidence else "-","status":"보완" if top_evidence and top_evidence["share"]>=25 else "관찰","note":f"{top_evidence['share']:.1f}% 요청" if top_evidence else "응답 대기"},
    ]
    roadmap=_roadmap(stage,n,target,interest_segments,top_attraction,top_barrier,top_evidence,hi_cost)
    return {
        "project_key":str(project_key),"product_id":str(project_key),"brand":meta.get("brand",meta.get("short_name",str(project_key))),"slug":meta.get("slug",str(project_key)),"product_name":meta.get("name",str(project_key)),"short_name":meta.get("short_name",str(project_key)),"category":meta.get("category",""),
        "n":n,"target":target,"final_ready":True,"sample_stage":stage,"headline":headline,"checks":checks,
        "product_check":{"avg_intent":avg_intent,"high_intent_rate":high_rate,"low_intent_rate":low_rate,"intent_valid_n":valid_intent,"intent_distribution":intent_dist,"attractions":q4,"q1_segments":q1,"q2_needs":q2,"q3_needs":q3,"segment_map":_segment_map(rows),"intent_source":"펀딩 참여 여부 문항"},
        "price_check":{"reference_price":price,"cost_barrier_rate":cost_rate,"high_intent_cost_barrier_rate":hi_cost,"note":"현재 제시가격에서 가격·비용 저항을 추적합니다. 관심군은 Q1에서 펀딩 참여 의향이 있다고 답한 응답자입니다."},
        "conversion_check":{"funding_available":funding_available,"funding_count":funding_count,"funding_rate":funding_rate,"interest_action_gap":gap,"high_intent_n":len(hi),"high_intent_nonfunded_n":len(hi_nonfund),"high_intent_nonfunded_barriers":nonfund_barriers},
        "page_check":{"needed_evidence":q5,"top_barriers":q6,"text_topics":_text_topics(rows)},
        "voice_of_customer":_all_comment_records(rows),
        "comment_insights":comment_insights,
        "customer_segments":{
            "age":_single_top(_count(rows,"age_group"),n,8),
            "gender":_single_top(_gender_counter(rows),_gender_valid_n(rows),6),
            "age_intent":_age_intent(rows),
            "age_reaction":age_reaction,
            "gender_reaction":gender_reaction,
            "age_insights":_demographic_insights(age_reaction,"연령대"),
            "gender_insights":_demographic_insights(gender_reaction,"성별"),
        },
        "interest_segments":interest_segments,
        "roadmap":roadmap,
        "actions":actions[:4],
        "data_quality":{"raw_rows":len(raw_rows),"used_rows":n,"duplicate_n":max(0,len(raw_rows)-n),"intent_valid_n":valid_intent,"intent_complete_rate":_pct(valid_intent,n),"intent_source":"펀딩 참여 여부 문항"},
    }

def admin_overview(projects,funding_rows=None):
    analyses=[analyze_project(pid,projects.get(pid,[]),funding_rows) for pid in PRODUCT_ORDER]
    keys=defaultdict(set)
    for pid,rows in projects.items():
        for r in _dedup(rows):
            k=_row_key(r)
            if k:keys[k].add(str(pid))
    respondent_count=len(keys) if keys else max([a["n"] for a in analyses]+[0]); complete=sum(1 for v in keys.values() if all(pid in v for pid in PRODUCT_ORDER)) if keys else 0
    plist=[]; scatter=[]
    for a in analyses:
        top_bar=(a["page_check"]["top_barriers"][0]["label"] if a["page_check"]["top_barriers"] else "-")
        top_ev=(a["page_check"]["needed_evidence"][0]["label"] if a["page_check"]["needed_evidence"] else "-")
        plist.append({"project_key":a["project_key"],"brand":a["brand"],"slug":a["slug"],"product_name":a["product_name"],"short_name":a["short_name"],"category":a["category"],"n":a["n"],"target":a["target"],"progress":a["sample_stage"]["progress"],"stage":a["sample_stage"]["label"],"avg_intent":a["product_check"]["avg_intent"],"high_intent_rate":a["product_check"]["high_intent_rate"],"intent_valid_n":a["product_check"]["intent_valid_n"],"funding_rate":a["conversion_check"]["funding_rate"],"interest_action_gap":a["conversion_check"]["interest_action_gap"],"cost_barrier_rate":a["price_check"]["cost_barrier_rate"],"top_barrier":top_bar,"top_evidence":top_ev})
        scatter.append({"label":a["brand"],"avg_intent":a["product_check"]["avg_intent"],"high_intent_rate":a["product_check"]["high_intent_rate"],"cost_barrier_rate":a["price_check"]["cost_barrier_rate"],"funding_rate":a["conversion_check"]["funding_rate"],"n":a["n"]})
    reliable=[a for a in analyses if a["n"]>=30]
    barrier_counter=Counter(a["page_check"]["top_barriers"][0]["label"] for a in reliable if a["page_check"]["top_barriers"])
    evidence_counter=Counter(a["page_check"]["needed_evidence"][0]["label"] for a in reliable if a["page_check"]["needed_evidence"])
    common=[]
    if barrier_counter:
        label,c=barrier_counter.most_common(1)[0]; common.append({"title":"공통 구매장벽","value":label,"note":f"예비 분석 가능 제품 {len(reliable)}개 중 {c}개에서 1순위"})
    if evidence_counter:
        label,c=evidence_counter.most_common(1)[0]; common.append({"title":"공통 추가정보 요구","value":label,"note":f"예비 분석 가능 제품 {len(reliable)}개 중 {c}개에서 1순위"})
    if not common: common=[{"title":"공통 패턴","value":"뚜렷한 공통 신호 없음","note":"최종 표본에서 세 제품에 공통으로 반복되는 핵심 신호가 확인되지 않았습니다."}]
    completion_rate=_pct(complete,respondent_count) if respondent_count else 0
    counts=[a["n"] for a in analyses]
    balance_gap=(max(counts)-min(counts)) if counts else 0
    return {"project_count":3,"respondent_count":respondent_count,"complete_all3":complete,"completion_rate":completion_rate,"total_product_responses":sum(counts),"product_balance_gap":balance_gap,"projects":plist,"portfolio_scatter":scatter,"common_patterns":common}

def maker_token(project_key:str)->str:
    secret=load_settings().get("secret","").encode("utf-8"); return hmac.new(secret,str(project_key).encode("utf-8"),hashlib.sha256).hexdigest()[:32]

def resolve_token(token:str,projects:dict[str,list[dict]])->str|None:
    for k in PRODUCT_ORDER:
        if hmac.compare_digest(maker_token(k),str(token or "")): return k
    return None
