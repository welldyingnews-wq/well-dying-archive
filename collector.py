import os
import json
import feedparser
import urllib.parse
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv

# ⭐ Supabase 저장 담당 (database.py 파일이 같은 폴더에 있어야 함)
import database 

load_dotenv()

# ==========================================
# 1. 구글 시트 연결 (설정값 읽기 전용)
# ==========================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_filename = "service_account.json"

    # 깃허브 서버에는 파일이 없으므로, 환경변수(Secret)에서 꺼내서 만듦
    if not os.path.exists(json_filename):
        json_content = os.getenv("GOOGLE_SHEET_JSON")
        if not json_content:
            print("❌ 에러: 구글 시트 키(GOOGLE_SHEET_JSON)가 깃허브 Secrets에 없습니다.")
            return None
        
        with open(json_filename, "w") as f:
            f.write(json_content)
        print("✅ 깃허브 Secret을 이용해 인증 파일을 생성했습니다.")

    creds = ServiceAccountCredentials.from_json_keyfile_name(json_filename, scope)
    return gspread.authorize(creds)

def load_configs(client):
    """구글 시트에서 설정값(키워드, 금지어 등)만 쏙 빼오기"""
    print("📋 구글 시트에서 설정을 읽어옵니다...")
    wb = client.open("Global Well-Dying Archive")
    
    # 1. 타겟 국가
    targets = []
    try:
        for r in wb.worksheet("Config").get_all_records():
            if r.get('국가코드'): targets.append(r)
    except: targets = [{'code': 'US', 'lang': 'en', 'name': '미국'}]

    # 2. 키워드
    keywords = []
    try:
        for r in wb.worksheet("Keywords").get_all_records():
            if r.get('키워드'): keywords.append(r['키워드'])
    except: keywords = ["Euthanasia"]

    # 3. RSS 사이트
    sites = []
    try:
        for r in wb.worksheet("Sites").get_all_records():
            if r.get('RSS주소'): sites.append({'name': r['사이트명'], 'url': r['RSS주소']})
    except: sites = []

    # 4. 금지어
    ban_words = []
    try:
        for r in wb.worksheet("BanWords").get_all_records():
            if r.get('금지어'): ban_words.append(r['금지어'])
    except: pass
    
    return targets, keywords, sites, ban_words

# ==========================================
# 2. 뉴스 수집 로직 (기존과 동일)
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
    if not client_id: return []
    
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    for kw in keywords[:5]:
        try:
            url = f"https://openapi.naver.com/v1/search/news.json?query={kw}&display=3&sort=sim"
            res = requests.get(url, headers=headers).json()
            for item in res.get('items', []):
                title = item['title'].replace('<b>','').replace('</b>','').replace('&quot;', '"')
                if not is_junk(title, ban_words):
                    results.append({'title': title, 'link': item['link'], 'source_type': 'NAVER(국내)'})
        except: pass
    return results

# ==========================================
# 3. 메인 실행 (수집 -> Supabase 저장)
# ==========================================
def main():
    print("🚀 하이브리드 수집기 가동 (설정:구글시트 / 저장:Supabase)")
    
    # 1. 구글 시트 연결
    client = get_sheet_client()
    if not client: return

    # 2. 설정값 로드
    targets, keywords, sites, ban_words = load_configs(client)
    print(f"🔍 키워드: {keywords}")
    print(f"🚫 금지어: {len(ban_words)}개 적용됨")

    # 3. 뉴스 수집
    all_news = []
    all_news.extend(fetch_naver_news(keywords, ban_words))
    all_news.extend(fetch_google_news_direct(keywords, targets, ban_words))
    all_news.extend(fetch_rss_sites(sites, ban_words))
    
    print(f"📦 총 {len(all_news)}개 기사 확보.")

    # 4. 날짜 찍고 Supabase에 저장
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    for news in all_news:
        news['collected_at'] = current_time

    if all_news:
        try:
            # ⭐ 여기가 핵심: 시트 저장 코드는 없고, DB 저장 코드만 있음!
            count = database.save_news(all_news)
            print(f"💾 Supabase 저장 완료: {count}건 (중복 제외)")
        except Exception as e:
            print(f"🔥 저장 실패: {e}")
            print("Hint: database.py 파일이 있는지, Supabase URL/KEY가 맞는지 확인하세요.")
    else:
        print("☁️ 수집된 뉴스가 없습니다.")

if __name__ == "__main__":
    main()
