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
# 1. 설정 및 초기화
# ==========================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_path = os.getenv("GOOGLE_SHEET_JSON_PATH", "service_account.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    return gspread.authorize(creds)

def load_configs(client):
    wb = client.open("Global Well-Dying Archive")
    
    # 1. 국가 설정 로드
    targets = []
    try:
        for r in wb.worksheet("Config").get_all_records():
            if r.get('국가코드'): targets.append({'code': r['국가코드'], 'lang': r['언어'], 'name': r['국가명']})
    except: targets = [{'code': 'US', 'lang': 'en', 'name': '미국(기본)'}]

    # 2. 검색 키워드 로드
    keywords = []
    try:
        for r in wb.worksheet("Keywords").get_all_records():
            if r.get('키워드'): keywords.append(r['키워드'])
    except: keywords = ["Euthanasia"]

    # 3. RSS 사이트 로드
    sites = []
    try:
        for r in wb.worksheet("Sites").get_all_records():
            if r.get('RSS주소'): sites.append({'name': r['사이트명'], 'url': r['RSS주소']})
    except: sites = []

    # 4. [NEW] 금지어 로드 (시트에서 가져옴!)
    ban_words = []
    try:
        for r in wb.worksheet("BanWords").get_all_records():
            if r.get('금지어'): ban_words.append(r['금지어'])
    except: 
        # 시트가 없거나 비었을 때 기본값
        ban_words = ["게임", "주식", "증시", "드라마", "웹툰"]

    return targets, keywords, sites, ban_words

# ==========================================
# 2. 필터링 함수
# ==========================================
def is_junk(title, ban_words):
    for bad_word in ban_words:
        if bad_word.lower() in title.lower():
            return True
    return False

# ==========================================
# 3. 수집기
# ==========================================
def fetch_google_news_direct(keywords, targets, ban_words):
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
                    if is_junk(entry.title, ban_words): continue # 금지어 체크
                    
                    results.append({
                        'title': entry.title,
                        'link': entry.link,
                        'source_type': f"Google({target['name']})"
                    })
            except: pass
    return results

def fetch_rss_sites(sites, ban_words):
    results = []
    for site in sites:
        try:
            feed = feedparser.parse(site['url'])
            for entry in feed.entries[:3]:
                if is_junk(entry.title, ban_words): continue
                
                results.append({
                    'title': entry.title,
                    'link': entry.link,
                    'source_type': f"Blog({site['name']})"
                })
        except: pass
    return results

def fetch_naver_news(keywords, ban_words):
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
                if is_junk(title, ban_words): continue

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
    targets, keywords, sites, ban_words = load_configs(client)
    
    print(f"🚫 적용된 금지어: {ban_words}")
    
    all_news = []
    all_news.extend(fetch_naver_news(keywords, ban_words))
    all_news.extend(fetch_google_news_direct(keywords, targets, ban_words))
    all_news.extend(fetch_rss_sites(sites, ban_words))
    
    print(f"📦 필터링 후 {len(all_news)}개 기사 확보. 저장 시작...")
    
    sheet = client.open("Global Well-Dying Archive").worksheet("News")
    existing_links = sheet.col_values(8)
    
    new_rows = []
    for news in all_news:
        if news['link'] in existing_links: continue
        
        translate_formula = f'=GOOGLETRANSLATE("{news["title"]}", "auto", "ko")'

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            news['source_type'],
            "수집됨",
            news['title'],
            translate_formula,
            "",
            "",
            news['link']
        ]
        new_rows.append(row)

    if new_rows:
        sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
        print(f"💾 {len(new_rows)}개 뉴스 저장 완료!")
    else:
        print("☁️ 새로 업데이트된 뉴스가 없습니다.")

if __name__ == "__main__":
    main()
