from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

import requests

from .config import load_settings, MARKET_PROFILES

BASE_URL = "https://naverapihub.apigw.ntruss.com"
_trend_cache: dict[str, tuple[float, dict]] = {}
_shopping_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()

AGE_LABELS = {
    "10": "10대",
    "20": "20대",
    "30": "30대",
    "40": "40대",
    "50": "50대",
    "60": "60대 이상",
}
GENDER_LABELS = {"m": "남성", "f": "여성"}


def _headers(settings: dict) -> dict:
    return {
        "X-NCP-APIGW-API-KEY-ID": str(settings.get("naver_api_client_id") or "").strip(),
        "X-NCP-APIGW-API-KEY": str(settings.get("naver_api_client_secret") or "").strip(),
        "Content-Type": "application/json",
    }


def _trend(project_key: str, settings: dict) -> list[dict]:
    """NAVER DataLab Search Trend quantitative data."""
    profile = MARKET_PROFILES.get(str(project_key), {})
    keywords = profile.get("keywords") or []
    if not keywords:
        return []

    end = date.today()
    start = end - timedelta(days=365)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "month",
        "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords[:5]],
    }
    r = requests.post(
        f"{BASE_URL}/search-trend/v1/search",
        headers=_headers(settings),
        json=body,
        timeout=12,
    )
    r.raise_for_status()
    payload = r.json()
    out = []
    for item in payload.get("results") or []:
        out.append(
            {
                "title": str(item.get("title") or ""),
                "keywords": item.get("keywords") or [],
                "data": [
                    {
                        "period": str(x.get("period") or ""),
                        "ratio": round(float(x.get("ratio") or 0), 2),
                    }
                    for x in (item.get("data") or [])
                ],
            }
        )
    return out


def _series_summary(series: list[dict], basis: str, note: str) -> dict:
    if not series:
        return {}

    primary = series[0]
    points = [x for x in (primary.get("data") or []) if x.get("period")]
    values = [float(x.get("ratio") or 0) for x in points]
    recent = values[-3:] if values else []
    previous = values[-6:-3] if len(values) >= 6 else []
    recent_avg = round(mean(recent), 1) if recent else None
    previous_avg = round(mean(previous), 1) if previous else None
    delta_pct = None
    state = "비교 데이터 부족"
    if recent_avg is not None and previous_avg not in (None, 0):
        delta_pct = round((recent_avg - previous_avg) / previous_avg * 100, 1)
        if delta_pct >= 10:
            state = "최근 관심 증가"
        elif delta_pct <= -10:
            state = "최근 관심 감소"
        else:
            state = "최근 관심 보합"

    latest_period = ""
    latest_keyword = ""
    latest_ratio = None
    latest_candidates = []
    for s in series:
        data = s.get("data") or []
        if not data:
            continue
        x = data[-1]
        latest_candidates.append(
            (float(x.get("ratio") or 0), str(s.get("title") or ""), str(x.get("period") or ""))
        )
    if latest_candidates:
        latest_ratio, latest_keyword, latest_period = max(latest_candidates, key=lambda x: x[0])
        latest_ratio = round(latest_ratio, 1)

    peak_period = ""
    peak_ratio = None
    if points:
        peak = max(points, key=lambda x: float(x.get("ratio") or 0))
        peak_period = str(peak.get("period") or "")
        peak_ratio = round(float(peak.get("ratio") or 0), 1)

    return {
        "primary_keyword": str(primary.get("title") or ""),
        "state": state,
        "recent_3m_avg": recent_avg,
        "previous_3m_avg": previous_avg,
        "delta_pct": delta_pct,
        "latest_period": latest_period,
        "latest_keyword": latest_keyword,
        "latest_ratio": latest_ratio,
        "peak_period": peak_period,
        "peak_ratio": peak_ratio,
        "basis": basis,
        "calculation_note": note,
    }


def _trend_summary(series: list[dict]) -> dict:
    return _series_summary(
        series,
        "NAVER DataLab 통합검색 상대 검색 관심지수",
        "최근 3개월 평균과 직전 3개월 평균을 단순 비교한 수치이며 절대 검색량이 아닙니다.",
    )


def _load_trend_cached(project_key: str, settings: dict, force: bool = False) -> dict:
    ttl = max(600, int(settings.get("market_refresh_minutes", 60)) * 60)
    key = str(project_key)
    with _lock:
        hit = _trend_cache.get(key)
        if hit and not force and time.time() - hit[0] < ttl:
            return hit[1]

    result = {"trend": [], "trend_summary": {}, "error": "", "updated_at": int(time.time())}
    try:
        result["trend"] = _trend(key, settings)
        result["trend_summary"] = _trend_summary(result["trend"])
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    with _lock:
        _trend_cache[key] = (time.time(), result)
    return result


def _shopping_keyword_trend(project_key: str, settings: dict) -> list[dict]:
    profile = MARKET_PROFILES.get(str(project_key), {})
    category = str(profile.get("shopping_category_id") or "").strip()
    keywords = profile.get("keywords") or []
    if not category or not keywords:
        return []

    end = date.today()
    start = end - timedelta(days=365)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "month",
        "category": category,
        "keyword": [{"name": k, "param": [k]} for k in keywords[:5]],
    }
    r = requests.post(
        f"{BASE_URL}/shopping/v1/category/keywords",
        headers=_headers(settings),
        json=body,
        timeout=12,
    )
    r.raise_for_status()
    payload = r.json()
    out = []
    for item in payload.get("results") or []:
        out.append(
            {
                "title": str(item.get("title") or ""),
                "keywords": item.get("keyword") or [],
                "data": [
                    {
                        "period": str(x.get("period") or ""),
                        "ratio": round(float(x.get("ratio") or 0), 2),
                    }
                    for x in (item.get("data") or [])
                ],
            }
        )
    return out


def _shopping_breakdown(project_key: str, settings: dict, kind: str) -> dict:
    profile = MARKET_PROFILES.get(str(project_key), {})
    category = str(profile.get("shopping_category_id") or "").strip()
    category_name = str(profile.get("shopping_category_name") or "")
    keyword = str(profile.get("shopping_audience_keyword") or (profile.get("keywords") or [""])[0]).strip()
    if not category or not keyword or kind not in {"age", "gender"}:
        return {}

    end = date.today()
    start = end - timedelta(days=92)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "month",
        "category": category,
        "keyword": keyword,
    }
    r = requests.post(
        f"{BASE_URL}/shopping/v1/category/keyword/{kind}",
        headers=_headers(settings),
        json=body,
        timeout=12,
    )
    r.raise_for_status()
    payload = r.json()
    result = (payload.get("results") or [{}])[0]
    grouped: dict[str, list[float]] = defaultdict(list)
    periods: dict[str, set[str]] = defaultdict(set)
    for x in result.get("data") or []:
        group = str(x.get("group") or "")
        if not group:
            continue
        grouped[group].append(float(x.get("ratio") or 0))
        if x.get("period"):
            periods[group].add(str(x.get("period")))

    labels = AGE_LABELS if kind == "age" else GENDER_LABELS
    rows = []
    for group, vals in grouped.items():
        rows.append(
            {
                "group": group,
                "label": labels.get(group, group),
                "index": round(mean(vals), 1) if vals else 0,
                "period_count": len(periods[group]),
            }
        )
    rows.sort(key=lambda x: x["index"], reverse=True)
    return {
        "kind": kind,
        "keyword": keyword,
        "category_id": category,
        "category_name": category_name,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "rows": rows,
        "top": rows[0] if rows else {},
        "note": "최근 약 3개월 데이터를 월 단위로 조회해 그룹별 상대 클릭지수를 평균한 값입니다. 비중·실제 클릭수·구매율이 아닙니다.",
    }


def _shopping_summary(series: list[dict], age: dict, gender: dict) -> dict:
    summary = _series_summary(
        series,
        "NAVER Shopping Insight 상대 검색 클릭지수",
        "최근 3개월 평균과 직전 3개월 평균을 단순 비교한 수치이며 실제 클릭수·구매량이 아닙니다.",
    )
    summary["top_age"] = (age or {}).get("top") or {}
    summary["top_gender"] = (gender or {}).get("top") or {}
    return summary


def _load_shopping_cached(project_key: str, settings: dict, force: bool = False) -> dict:
    ttl = max(600, int(settings.get("market_refresh_minutes", 60)) * 60)
    key = str(project_key)
    with _lock:
        hit = _shopping_cache.get(key)
        if hit and not force and time.time() - hit[0] < ttl:
            return hit[1]

    result = {
        "trend": [],
        "age": {},
        "gender": {},
        "summary": {},
        "errors": {},
        "updated_at": int(time.time()),
    }
    try:
        result["trend"] = _shopping_keyword_trend(key, settings)
    except Exception as e:
        result["errors"]["shopping_keywords"] = f"{type(e).__name__}: {e}"
    try:
        result["age"] = _shopping_breakdown(key, settings, "age")
    except Exception as e:
        result["errors"]["shopping_age"] = f"{type(e).__name__}: {e}"
    try:
        result["gender"] = _shopping_breakdown(key, settings, "gender")
    except Exception as e:
        result["errors"]["shopping_gender"] = f"{type(e).__name__}: {e}"
    result["summary"] = _shopping_summary(result["trend"], result["age"], result["gender"])

    with _lock:
        _shopping_cache[key] = (time.time(), result)
    return result


def _search_reference_group(kind: str, query: str, settings: dict, display: int = 5) -> dict:
    """Fetch NAVER Search API results for direct reference display only.

    The result count here is a requested display size, NOT market volume. Search
    results are not summarized, classified, sentiment-scored, or fed into AI.
    """
    requested = max(1, min(10, int(display)))
    params = {
        "query": query,
        "display": requested,
        "start": 1,
        "sort": "date",
    }
    r = requests.get(
        f"{BASE_URL}/search/v1/{kind}",
        headers=_headers(settings),
        params=params,
        timeout=12,
    )
    r.raise_for_status()
    payload = r.json()
    items = []
    for x in payload.get("items") or []:
        items.append(
            {
                "title": str(x.get("title") or ""),
                "url": str(x.get("originallink") or x.get("link") or ""),
                "naver_url": str(x.get("link") or ""),
                "pub_date": str(x.get("pubDate") or x.get("postdate") or ""),
            }
        )
    return {
        "query": query,
        "kind": kind,
        "requested_display": requested,
        "returned_count": len(items),
        "api_total": int(payload.get("total") or 0),
        "items": items,
    }


def _load_search_references(project_key: str, settings: dict) -> dict:
    """Search API references are fetched live and deliberately not server-cached."""
    profile = MARKET_PROFILES.get(str(project_key), {})
    keywords = profile.get("keywords") or []
    news_queries = profile.get("news_queries") or keywords[:1]
    blog_queries = profile.get("blog_queries") or keywords[:1]

    news_groups = []
    blog_groups = []
    errors: dict[str, str] = {}

    for i, query in enumerate(news_queries[:2]):
        try:
            news_groups.append(_search_reference_group("news", str(query), settings, 5))
        except Exception as e:
            errors[f"news_{i+1}"] = f"{type(e).__name__}: {e}"

    for i, query in enumerate(blog_queries[:1]):
        try:
            blog_groups.append(_search_reference_group("blog", str(query), settings, 5))
        except Exception as e:
            errors[f"blog_{i+1}"] = f"{type(e).__name__}: {e}"

    return {
        "news_groups": news_groups,
        "blog_groups": blog_groups,
        "errors": errors,
        "updated_at": int(time.time()),
    }


def get_market_data(project_key: str, force: bool = False) -> dict:
    settings = load_settings()
    profile = MARKET_PROFILES.get(str(project_key), {})
    keywords = profile.get("keywords") or []
    cid = str(settings.get("naver_api_client_id") or "").strip()
    secret = str(settings.get("naver_api_client_secret") or "").strip()

    base = {
        "connected": False,
        "provider": "NAVER API HUB",
        "keywords": keywords,
        "trend": [],
        "trend_summary": {},
        "shopping_trend": [],
        "shopping_summary": {},
        "shopping_age": {},
        "shopping_gender": {},
        "shopping_category": {
            "id": str(profile.get("shopping_category_id") or ""),
            "name": str(profile.get("shopping_category_name") or ""),
        },
        "news_groups": [],
        "blog_groups": [],
        "errors": {},
        "updated_at": int(time.time()),
        "analysis_source": "NAVER DataLab Search Trend + Shopping Insight",
        "reference_source": "NAVER Search API",
        "usage_policy": {
            "automatic_analysis": "Search Trend 검색 상대지수와 Shopping Insight 쇼핑 클릭 상대지수만 수치 계산·시각화에 사용",
            "direct_reference": "뉴스·블로그 검색결과는 제목·날짜·원문 링크만 별도 표시",
            "not_used": "뉴스·블로그는 AI 요약·감성분석·재분류·설문 인사이트 결합에 사용하지 않음",
            "search_cache": "검색 API 결과는 서버에 저장·캐싱하지 않고 요청 시 직접 조회",
        },
    }

    if not cid or not secret:
        base["reason"] = "NAVER API HUB Client ID / Client Secret이 아직 설정되지 않았습니다."
        return base

    trend_result = _load_trend_cached(str(project_key), settings, force=force)
    base["trend"] = trend_result.get("trend") or []
    base["trend_summary"] = trend_result.get("trend_summary") or {}
    base["trend_updated_at"] = trend_result.get("updated_at")
    if trend_result.get("error"):
        base["errors"]["trend"] = trend_result["error"]

    shopping_result = _load_shopping_cached(str(project_key), settings, force=force)
    base["shopping_trend"] = shopping_result.get("trend") or []
    base["shopping_summary"] = shopping_result.get("summary") or {}
    base["shopping_age"] = shopping_result.get("age") or {}
    base["shopping_gender"] = shopping_result.get("gender") or {}
    base["shopping_updated_at"] = shopping_result.get("updated_at")
    base["errors"].update(shopping_result.get("errors") or {})

    refs = _load_search_references(str(project_key), settings)
    base["news_groups"] = refs.get("news_groups") or []
    base["blog_groups"] = refs.get("blog_groups") or []
    base["reference_updated_at"] = refs.get("updated_at")
    base["errors"].update(refs.get("errors") or {})

    base["connected"] = bool(
        base["trend"] or base["shopping_trend"] or base["news_groups"] or base["blog_groups"]
    )
    if not base["connected"]:
        base["reason"] = "NAVER API HUB에서 시장 데이터를 불러오지 못했습니다. API 권한과 키를 확인해 주세요."
    return base
