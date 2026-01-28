import os
import time
import json
import requests
import feedparser
import urllib.parse
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 0. 금지어 목록 (이 단어가 제목에 있으면 수집 안 함!)
# ==========================================
# 여기에 걸러내고 싶은 단어를 계속 추가하시면 됩니다.
EXCLUDE_KEYWORDS = [
    "게임", "Game", "주식", "증시", "종목", "영화", "Movie", "드라마", 
    "웹툰", "리뷰", "Review", "시황", "캐릭터", "공략", "이벤트", "할인"
]

# ==========================================
# 1. 설정 및 초기화
# ==========================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_path = os.getenv("GOOGLE_SHEET_JSON_PATH", "service_account.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    return gspread.authorize(creds)

def load_configs(client):
    wb = client.open("Global Well-Dying Archive")
    
    targets = []
    try:
        for r in wb.worksheet("Config").get_all_records():
            if r.get('국가코드'): targets.append({'code': r['국가코드'], 'lang': r['언어'], 'name': r['국가명']})
    except: targets = [{'code': 'US', 'lang': 'en', 'name': '미국(기본)'}]

    keywords = []
    try:
        for r in wb.worksheet("Keywords").get_all_records():
            if r.get('키워드'): keywords.append(r['키워드'])
    except: keywords = ["Euthanasia"]

    sites = []
    try:
        for r in wb.worksheet("Sites").get_all_records():
            if r.get('RSS주소'): sites.append({'name': r['사이트명'], 'url': r['RSS주소']})
    except: sites = []

    return targets, keywords, sites

# ==========================================
# 2. 필터링 함수 (핵심!)
# ==========================================
def is_junk(title):
    # 1. 금지어가 포함되어 있는지 확인
    for bad_word in EXCLUDE_KEYWORDS:
        if bad_word.lower() in title.lower():
            return True # 쓰레기 기사임
    return False # 통과

# ==========================================
# 3. 수집기 (직접 통신 + 필터링 적용)
# ==========================================
def fetch_google_news_direct(keywords, targets):
    results = []
    base_url = "https://news.google.com/rss/search"
    
    for target in targets:
        print(f"  ✈️ {target['name']} 뉴스 탐색 중...")
        for kw in keywords:
            try:
                search_kw = kw
                if target['code'] == 'JP' and kw == 'Euthanasia': search_kw = '安楽死'
                
                params = {
                    "q": search_kw,
                    "hl": target['lang'],
                    "gl": target['code'],
                    "ceid": f"{target['code']}:{target['lang']}"
                }
                query_string = urllib.parse.urlencode(params)
                rss_url = f"{base_url}?{query_string}"
                
                feed = feedparser.parse(rss_url)
                
                for entry in feed.entries[:2]:
                    # 여기서 금지어 체크!
                    if is_junk(entry.title):
                        continue 

                    results.append({
                        'title': entry.title,
                        'link': entry.link,
                        'source_type': f"Google({target['name']})"
                    })
            except: pass
    return results

def fetch_rss_sites(sites):
    results = []
    for site in sites:
        try:
            feed = feedparser.parse(site['url'])
            for entry in feed.entries[:3]:
                if is_junk(entry.title): continue # 금지어 체크

                results.append({
                    'title': entry.title,
                    'link': entry.link,
                    'source_type': f"Blog({site['name']})"
                })
        except: pass
    return results

def fetch_naver_news(keywords):
    results = []
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    
    if not client_id or not client_secret: return []

    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    short_keywords = keywords[:5] 
    
    for kw in short_keywords:
        try:
            url = f"https://openapi.naver.com/v1/search/news.json?query={kw}&display=3&sort=sim"
            res = requests.get(url, headers=headers).json()
            for item in res.get('items', []):
                title = item['title'].replace('<b>','').replace('</b>','')
                if is_junk(title): continue # 금지어 체크

                results.append({
                    'title': title,
                    'link': item['link'],
                    'source_type': 'NAVER(국내)'
                })
        except: pass
    return results

# ==========================================
# 4. 메인 실행
# ==========================================
def main():
    print("🚀 스마트 수집기(Smart Light) 가동 시작...")
    client = get_sheet_client()
    targets, keywords, sites = load_configs(client)
    
    all_news = []
    all_news.extend(fetch_naver_news(keywords))
    all_news.extend(fetch_google_news_direct(keywords, targets))
    all_news.extend(fetch_rss_sites(sites))
    
    print(f"📦 필터링 후 {len(all_news)}개 기사 확보. 저장 시작...")
    
    sheet = client.open("Global Well-Dying Archive").worksheet("News")
    existing_links = sheet.col_values(8)
    
    new_rows = []
    for news in all_news:
        if news['link'] in existing_links: continue
        
        # E열(요약)에 엑셀 함수를 넣어서 자동 번역되게 함!
        # D열(제목) 값을 한국어로 번역하라는 명령
        translate_formula = f'=GOOGLETRANSLATE("{news["title"]}", "auto", "ko")'

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            news['source_type'],
            "수집됨",
            news['title'],
            translate_formula, # ⭐ 여기가 핵심! (엑셀 함수가 들어감)
            "",
            "",
            news['link']
        ]
        new_rows.append(row)

    if new_rows:
        # append_rows에서 value_input_option='USER_ENTERED'를 써야 함수가 작동함
        sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
        print(f"💾 {len(new_rows)}개 뉴스 저장 완료! (번역 함수 포함)")
    else:
        print("☁️ 새로 업데이트된 뉴스가 없습니다.")

if __name__ == "__main__":
    main()
