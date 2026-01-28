import os
import time
import json
import requests
import feedparser
import urllib.parse
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 0. 금지어 목록
# ==========================================
EXCLUDE_KEYWORDS = ["게임", "Game", "주식", "증시", "종목", "영화", "Movie", "드라마", "웹툰", "리뷰", "이벤트"]

# ==========================================
# 1. 설정 및 초기화
# ==========================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_path = os.getenv("GOOGLE_SHEET_JSON_PATH", "service_account.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    return gspread.authorize(creds)

def check_time_and_run(client):
    """지정된 시간이 지났는지 확인하는 함수"""
    try:
        sh = client.open("Global Well-Dying Archive").worksheet("Settings")
        
        # 설정값 가져오기
        interval = int(sh.cell(2, 2).value) # B2: 수집주기(분)
        last_run_str = sh.cell(3, 2).value  # B3: 마지막 실행시간
        
        last_run = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M:%S")
        time_diff = datetime.now() - last_run
        minutes_passed = time_diff.total_seconds() / 60
        
        print(f"⏰ 설정 주기: {interval}분 | 지난 시간: {int(minutes_passed)}분")
        
        if minutes_passed < interval:
            print("💤 아직 일할 시간이 아닙니다. 다시 잡니다.")
            return False # 실행하지 마!
        
        # 실행하기로 결정했으면, 지금 시간을 기록
        sh.update_cell(3, 2, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return True # 실행해!
        
    except Exception as e:
        print(f"⚠️ 시간 설정 확인 중 오류 (그냥 실행합니다): {e}")
        return True

def load_configs(client):
    wb = client.open("Global Well-Dying Archive")
    
    # 1. 국가, 2. 키워드, 3. 사이트 로드 (기존과 동일)
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

    ban_words = []
    try:
        for r in wb.worksheet("BanWords").get_all_records():
            if r.get('금지어'): ban_words.append(r['금지어'])
    except: ban_words = EXCLUDE_KEYWORDS

    return targets, keywords, sites, ban_words

# ==========================================
# 2. 필터링 및 수집 함수들 (기존과 동일)
# ==========================================
def is_junk(title, ban_words):
    for bad_word in ban_words:
        if bad_word.lower() in title.lower(): return True
    return False

def fetch_google_news_direct(keywords, targets, ban_words):
    results = []
    base_url = "https://news.google.com/rss/search"
    for target in targets:
        for kw in keywords:
            try:
                search_kw = kw
                if target['code'] == 'JP' and kw == 'Euthanasia': search_kw = '安楽死'
                params = {"q": search_kw, "hl": target['lang'], "gl": target['code'], "ceid": f"{target['code']}:{target['lang']}"}
                feed = feedparser.parse(f"{base_url}?{urllib.parse.urlencode(params)}")
                for entry in feed.entries[:2]:
                    if not is_junk(entry.title, ban_words):
                        results.append({'title': entry.title, 'link': entry.link, 'source_type': f"Google({target['name']})"})
            except: pass
    return results

def fetch_rss_sites(sites, ban_words):
    results = []
    for site in sites:
        try:
            feed = feedparser.parse(site['url'])
            for entry in feed.entries[:3]:
                if not is_junk(entry.title, ban_words):
                    results.append({'title': entry.title, 'link': entry.link, 'source_type': f"Blog({site['name']})"})
        except: pass
    return results

def fetch_naver_news(keywords, ban_words):
    results = []
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret: return []
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    for kw in keywords[:5]:
        try:
            res = requests.get(f"https://openapi.naver.com/v1/search/news.json?query={kw}&display=3&sort=sim", headers=headers).json()
            for item in res.get('items', []):
                title = item['title'].replace('<b>','').replace('</b>','')
                if not is_junk(title, ban_words):
                    results.append({'title': title, 'link': item['link'], 'source_type': 'NAVER(국내)'})
        except: pass
    return results

# ==========================================
# 3. 메인 실행 (시간 체크 로직 추가됨)
# ==========================================
def main():
    print("🚀 스마트 수집기 가동 중...")
    client = get_sheet_client()
    
    # ⭐ 여기가 핵심! (시간이 안 됐으면 여기서 프로그램 종료)
    if not check_time_and_run(client):
        return 

    targets, keywords, sites, ban_words = load_configs(client)
    
    all_news = []
    all_news.extend(fetch_naver_news(keywords, ban_words))
    all_news.extend(fetch_google_news_direct(keywords, targets, ban_words))
    all_news.extend(fetch_rss_sites(sites, ban_words))
    
    print(f"📦 {len(all_news)}개 기사 확보. 저장 시작...")
    
    sheet = client.open("Global Well-Dying Archive").worksheet("News")
    existing_links = sheet.col_values(8)
    
    new_rows = []
    for news in all_news:
        if news['link'] in existing_links: continue
        translate_formula = f'=GOOGLETRANSLATE("{news["title"]}", "auto", "ko")'
        new_rows.append([datetime.now().strftime("%Y-%m-%d %H:%M"), news['source_type'], "수집됨", news['title'], translate_formula, "", "", news['link']])

    if new_rows:
        sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
        print(f"💾 {len(new_rows)}개 뉴스 저장 완료!")
    else:
        print("☁️ 새로 업데이트된 뉴스가 없습니다.")

if __name__ == "__main__":
    main()
