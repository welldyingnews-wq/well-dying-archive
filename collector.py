import os
import time
import feedparser
import urllib.parse
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv

# ⭐ 핵심: Supabase 저장 담당 친구(database.py)를 불러옵니다
import database 

load_dotenv()

# ==========================================
# 1. 구글 시트 연결 (설정값 읽기용)
# ==========================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # 깃허브 vs 로컬 환경 구분
    json_path = "service_account.json"
    if not os.path.exists(json_path):
        json_path = os.getenv("GOOGLE_SHEET_JSON_PATH", "service_account.json")
        
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    return gspread.authorize(creds)

def check_time_and_run(client):
    """설정된 시간이 지났는지 확인 (구글 시트 'Settings' 탭 읽기)"""
    try:
        sh = client.open("Global Well-Dying Archive").worksheet("Settings")
        interval = int(sh.cell(2, 2).value) # 수집 주기(분)
        last_run_str = sh.cell(3, 2).value  # 마지막 실행 시간
        
        last_run = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M:%S")
        minutes_passed = (datetime.now() - last_run).total_seconds() / 60
        
        print(f"⏰ 지난 시간: {int(minutes_passed)}분 (설정: {interval}분)")
        
        if minutes_passed < interval:
            print("💤 아직 일할 시간이 아닙니다. 다시 잡니다.")
            return False
            
        # 실행하기로 했으니 시간 갱신
        sh.update_cell(3, 2, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return True
    except Exception as e:
        print(f"⚠️ 시간 설정 확인 실패 (그냥 실행함): {e}")
        return True

def load_configs(client):
    """구글 시트에서 키워드, 금지어, 사이트 목록 가져오기"""
    wb = client.open("Global Well-Dying Archive")
    
    targets = []
    try:
        for r in wb.worksheet("Config").get_all_records():
            if r.get('국가코드'): targets.append(r)
    except: targets = [{'code': 'US', 'lang': 'en', 'name': '미국'}]

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
    except: pass
    
    return targets, keywords, sites, ban_words

# ==========================================
# 2. 뉴스 수집 함수들 (기존 로직 유지)
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
                for entry in feed.entries[:2]: # 키워드당 2개만
                    if not is_junk(entry.title, ban_words):
                        results.append({'title': entry.title, 'link': entry.link, 'source_type': f"Google({target['name']})"})
            except: pass
    return results

def fetch_rss_sites(sites, ban_words):
    results = []
    for site in sites:
        try:
            feed = feedparser.parse(site['url'])
            for entry in feed.entries[:3]: # 사이트당 3개만
                if not is_junk(entry.title, ban_words):
                    results.append({'title': entry.title, 'link': entry.link, 'source_type': f"Blog({site['name']})"})
        except: pass
    return results

def fetch_naver_news(keywords, ban_words):
    results = []
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    
    if not client_id or not client_secret: 
        return []
        
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    
    for kw in keywords[:5]: # 네이버는 쿼터 아끼기 위해 키워드 5개만
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
# 3. 메인 실행 (여기가 바뀌었습니다!)
# ==========================================
def main():
    print("🚀 Supabase 수집기 가동 시작...")
    
    # 1. 구글 시트 연결 (설정값 로딩용)
    try:
        client = get_sheet_client()
    except Exception as e:
        print(f"❌ 구글 시트 연결 실패: {e}")
        return

    # 2. 시간 체크 (일할 시간인가?)
    # (테스트할 땐 아래 두 줄을 주석 처리(#) 하셔도 됩니다)
    if not check_time_and_run(client):
        return 

    # 3. 설정값(키워드 등) 가져오기
    targets, keywords, sites, ban_words = load_configs(client)
    print(f"🔍 키워드 {len(keywords)}개, 사이트 {len(sites)}개로 수집을 시작합니다.")

    # 4. 뉴스 수집
    all_news = []
    
    # (1) 네이버 뉴스
    naver_news = fetch_naver_news(keywords, ban_words)
    all_news.extend(naver_news)
    print(f"   - 네이버: {len(naver_news)}개")

    # (2) 구글 뉴스
    google_news = fetch_google_news_direct(keywords, targets, ban_words)
    all_news.extend(google_news)
    print(f"   - 구글: {len(google_news)}개")

    # (3) RSS 사이트
    rss_news = fetch_rss_sites(sites, ban_words)
    all_news.extend(rss_news)
    print(f"   - RSS: {len(rss_news)}개")
    
    print(f"📦 총 {len(all_news)}개 기사 확보.")

    # 5. 수집 시간표 찍기 (Supabase로 보내기 전 준비)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    for news in all_news:
        news['collected_at'] = current_time

    # ⭐⭐ [중요] 구글 시트 저장 코드 삭제됨! Supabase 저장만 수행 ⭐⭐
    if all_news:
        try:
            count = database.save_news(all_news)
            print(f"💾 Supabase에 {count}개 저장 성공!")
        except Exception as e:
            print(f"🔥 Supabase 저장 실패: {e}")
            print("혹시 database.py 파일이 없거나 키 설정이 안 되었나요?")
    else:
        print("☁️ 새로 수집된 뉴스가 없습니다.")

if __name__ == "__main__":
    main()
