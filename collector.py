import os
import time
import json
import requests
import feedparser
import urllib.parse
import pandas as pd
from datetime import datetime
import google.generativeai as genai
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

def configure_genai():
    api_key = os.getenv("GENAI_API_KEY")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('models/gemini-1.5-flash')

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
# 2. 수집기 (직접 통신 버전)
# ==========================================
def fetch_google_news_direct(keywords, targets):
    results = []
    base_url = "https://news.google.com/rss/search"
    
    for target in targets:
        print(f"  ✈️ {target['name']} 뉴스 탐색 중...")
        for kw in keywords:
            try:
                # 1. 검색어 국가별 최적화
                search_kw = kw
                if target['code'] == 'JP' and kw == 'Euthanasia': search_kw = '安楽死'
                
                # 2. 구글 뉴스 RSS 주소 직접 생성 (라이브러리 제거됨)
                params = {
                    "q": search_kw,
                    "hl": target['lang'],
                    "gl": target['code'],
                    "ceid": f"{target['code']}:{target['lang']}"
                }
                query_string = urllib.parse.urlencode(params)
                rss_url = f"{base_url}?{query_string}"
                
                # 3. RSS 파싱
                feed = feedparser.parse(rss_url)
                
                for entry in feed.entries[:2]:
                    results.append({
                        'title': entry.title,
                        'link': entry.link,
                        'content': entry.title,
                        'source_type': f"Google({target['name']})"
                    })
            except Exception as e:
                print(f"    ⚠️ {target['name']} 에러: {e}")
    return results

def fetch_rss_sites(sites):
    results = []
    for site in sites:
        print(f"  📡 {site['name']} 블로그 탐색 중...")
        try:
            feed = feedparser.parse(site['url'])
            for entry in feed.entries[:3]:
                results.append({
                    'title': entry.title,
                    'link': entry.link,
                    'content': getattr(entry, 'summary', entry.title),
                    'source_type': f"Blog({site['name']})"
                })
        except Exception as e:
            print(f"    ⚠️ {site['name']} 에러: {e}")
    return results

def fetch_naver_news(keywords):
    results = []
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        return []

    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    for kw in ["웰다잉", "존엄사", "호스피스"]:
        try:
            url = f"https://openapi.naver.com/v1/search/news.json?query={kw}&display=3&sort=sim"
            res = requests.get(url, headers=headers).json()
            for item in res.get('items', []):
                results.append({
                    'title': item['title'].replace('<b>','').replace('</b>',''),
                    'link': item['link'],
                    'content': item['description'],
                    'source_type': 'NAVER(국내)'
                })
        except: pass
    return results

# ==========================================
# 3. AI 분석기
# ==========================================
def analyze_news(model, news):
    prompt = f"""
    당신은 웰다잉 뉴스 편집자입니다. 이 기사가 '죽음, 호스피스, 장례, 존엄사'와 관련 있는지 분석하세요.
    외국어라면 반드시 한국어로 번역해서 요약하세요.

    제목: {news['title']}
    내용: {news['content']}

    [응답 형식 JSON]
    {{
        "is_relevant": true/false,
        "category": "정책/기술/문화/사건 중 택1",
        "summary": "3문장 이내 한국어 요약",
        "sentiment": "희망/논쟁/비보 중 택1",
        "priority": 1~5 (점수)
    }}
    """
    try:
        res = model.generate_content(prompt)
        text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(text)
    except: return None

# ==========================================
# 4. 메인 실행
# ==========================================
def main():
    print("🚀 시스템 가동 시작...")
    client = get_sheet_client()
    targets, keywords, sites = load_configs(client)
    model = configure_genai()
    
    all_news = []
    all_news.extend(fetch_naver_news(keywords))
    # 변경된 함수 사용
    all_news.extend(fetch_google_news_direct(keywords, targets))
    all_news.extend(fetch_rss_sites(sites))
    
    print(f"📦 총 {len(all_news)}개 기사 수집. AI 분석 시작...")
    
    sheet = client.open("Global Well-Dying Archive").worksheet("News")
    existing_links = sheet.col_values(8)
    
    new_rows = []
    for i, news in enumerate(all_news):
        if news['link'] in existing_links: continue
        
        print(f"[{i+1}/{len(all_news)}] ⏳ AI 분석 중... (15초 대기) - {news['title'][:10]}")
        time.sleep(15) 
        
        analysis = analyze_news(model, news)
        
        if analysis and analysis['is_relevant']:
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                news['source_type'],
                analysis['category'],
                news['title'],
                analysis['summary'],
                analysis['sentiment'],
                analysis['priority'],
                news['link']
            ]
            new_rows.append(row)
            print(f"  ✅ 저장 대기: {news['title'][:15]}...")
        else:
            print("  ❌ 관련 없음/분석 실패")

    if new_rows:
        sheet.append_rows(new_rows)
        print(f"💾 {len(new_rows)}개 뉴스 저장 완료!")
    else:
        print("☁️ 저장할 새로운 뉴스가 없습니다.")

if __name__ == "__main__":
    main()
