from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).resolve().parents[1]
SETTINGS_PATH = BASE / "settings.json"
SAMPLE_PATH = BASE / "data" / "sample_data.csv"

PRODUCT_CATALOG = {
    "11": {
        "brand": "SCARNON",
        "slug": "scarnon",
        "short_name": "SCARNON 야구배트",
        "name": "불필요한 거품은 모두 뺀 항공우주등급 알로이 야구배트 :SCARNON",
        "category": "스포츠 / 아웃도어",
        "reference_price": 120000,
    },
    "12": {
        "brand": "NIMBLE",
        "slug": "nimble",
        "short_name": "NIMBLE 무선 마우스",
        "name": "손에 자연스럽게 맞는 저소음 인체공학 무선 마우스 : NIMBLE",
        "category": "오피스 / 전자기기",
        "reference_price": 47000,
    },
    "7": {
        "brand": "PETMINT",
        "slug": "petmint",
        "short_name": "PETMINT 워터케어",
        "name": "반려동물 자동 급수 & 데일리 워터케어기 : PETMINT",
        "category": "리빙 / 펫테크",
        "reference_price": 69000,
    },
}
PRODUCT_ORDER = ["11", "12", "7"]

# 외부 시장 데이터 검색어. 실제 API 데이터는 이 검색어를 기준으로 불러옵니다.
MARKET_PROFILES = {
    "11": {
        "keywords": ["야구배트", "알로이 배트", "사회인야구 배트"],
        "news_queries": ["야구배트", "사회인야구 장비"],
        "blog_queries": ["알로이 배트 사회인야구"],
        "shopping_category_id": "50000007",
        "shopping_category_name": "스포츠/레저",
        "shopping_audience_keyword": "야구배트",
    },
    "12": {
        "keywords": ["무선 마우스", "인체공학 마우스", "저소음 마우스"],
        "news_queries": ["무선 마우스", "인체공학 마우스"],
        "blog_queries": ["저소음 인체공학 마우스"],
        "shopping_category_id": "50000003",
        "shopping_category_name": "디지털/가전",
        "shopping_audience_keyword": "무선 마우스",
    },
    "7": {
        "keywords": ["반려동물 급수기", "고양이 정수기", "자동 급수기"],
        "news_queries": ["반려동물 급수기", "펫테크 급수"],
        "blog_queries": ["고양이 자동 급수기"],
        "shopping_category_id": "50000008",
        "shopping_category_name": "생활/건강",
        "shopping_audience_keyword": "반려동물 급수기",
    },
}


DEFAULT_SETTINGS = {
    "version": "15.2-pdf-readability-links",
    "google_sheet_url": "https://docs.google.com/spreadsheets/d/1xpvAqkwiXlvmdJG_6OzCqdfmvfcNx5_fMV5KNHK45HI/edit?gid=463830734#gid=463830734",
    "data_endpoint": "",
    "refresh_seconds": 10,
    "target_sample_per_product": 400,
    "secret": "",
    "demo_mode": False,
    "naver_api_client_id": "",
    "naver_api_client_secret": "",
    "market_refresh_minutes": 60,
}


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            pass
    env_sheet = os.environ.get("WADIPASS_GOOGLE_SHEET_URL", "").strip()
    if env_sheet:
        data["google_sheet_url"] = env_sheet
    env_secret = os.environ.get("WADIPASS_MAKER_LINK_SECRET", "").strip()
    if env_secret:
        data["secret"] = env_secret
    env_naver_id = os.environ.get("WADIPASS_NAVER_CLIENT_ID", "").strip()
    env_naver_secret = os.environ.get("WADIPASS_NAVER_CLIENT_SECRET", "").strip()
    if env_naver_id:
        data["naver_api_client_id"] = env_naver_id
    if env_naver_secret:
        data["naver_api_client_secret"] = env_naver_secret
    if not data.get("secret"):
        data["secret"] = secrets.token_urlsafe(32)
        save_settings(data)
    data["refresh_seconds"] = max(10, int(os.environ.get("WADIPASS_REFRESH_SECONDS") or data.get("refresh_seconds", 10) or 10))
    data["target_sample_per_product"] = max(1, int(os.environ.get("WADIPASS_TARGET_SAMPLE") or data.get("target_sample_per_product", 400) or 400))
    data["market_refresh_minutes"] = max(10, int(os.environ.get("WADIPASS_MARKET_REFRESH_MINUTES") or data.get("market_refresh_minutes", 60) or 60))
    return data


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def sheet_id(sheet_url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", str(sheet_url or ""))
    return m.group(1) if m else None


def derive_csv_urls(sheet_url: str) -> list[tuple[str, str]]:
    """Survey-capable Google Sheet candidate tabs, ordered by usefulness."""
    if not sheet_url:
        return []
    sid = sheet_id(sheet_url)
    if not sid:
        return [("입력 주소", sheet_url)]
    gid_m = re.search(r"[?#&]gid=(\d+)", sheet_url)
    gid = gid_m.group(1) if gid_m else "0"
    named = []
    for sheet in ["responses", "설문결과"]:
        named.append((sheet, f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet={quote(sheet)}"))
    named += [
        ("지정 탭", f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"),
        ("지정 탭", f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&gid={gid}"),
    ]
    return named
