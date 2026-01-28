import os
import json
import requests
import time
import pandas as pd
from datetime import datetime
from typing import List, Dict

# 라이브러리 임포트
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pygooglenews import GoogleNews
from dotenv import load_dotenv

# .env 파일에서 API 키 로드 (보안)
load_dotenv()

# ==========================================
# 1. 환경 설정 및 상수 (Configuration)
# ==========================================
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_JSON_PATH") # json 파일 경로

# AI 모델 설정
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# ==========================================
# 2. 유틸리티 함수 (Slack, Sheet)
# ==========================================

def send_slack_alert(news_item: Dict, analysis: Dict):
    """중요 뉴스 슬랙 알림 전송"""
    emoji = "🌟" if analysis['sentiment'] == "희망(긍정)" else "📢"
    color = "#36a64f" if analysis['sentiment'] == "희망(긍정)" else "#ff0000"
    
    payload = {
        "text": f"{emoji} [중요] 웰다잉 뉴스 알림: {news_item['title']}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{emoji} {news_item['title']}*\n\n*출처:* {news_item['source_type']} | *감정:* {analysis['sentiment']}\n{analysis['summary']}"
                }
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"<{news_item['link']}|기사 원문 보기>"}]
            }
        ]
    }
    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"Slack 전송 실패: {e}")

def get_existing_links(sheet) -> List[str]:
    """시트에서 이미 저장된 기사 링크 목록을 가져옴 (중복 방지용)"""
    try:
        return sheet.col_values(8) # 8번째 열이 '원문링크'라고 가정
    except:
        return []

# ==========================================
# 3. 데이터 수집기 (Collectors)
# ==========================================

def fetch_naver_news(keywords: List[str]) -> List[Dict]:
    """[국내] 네이버 뉴스 수집"""
    results = []
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    
    for kw in keywords:
        url = f"https://openapi.naver.com/v1/search/news.json?query={kw}&display=5&sort=sim"
        try:
            res = requests.get(url, headers=headers)
            items = res.json().get('items', [])
            for item in items:
                results.append({
                    'title': item['title'].replace('<b>', '').replace('</b>', ''), # 태그 제거
                    'link': item['link'],
                    'content': item['description'],
                    'source_type': 'NAVER(국내)'
                })
        except Exception as e:
            print(f"네이버 수집 에러 ({kw}): {e}")
            
    return results

def fetch_pygooglenews(keywords: List[str]) -> List[Dict]:
    """[해외] Google News RSS 검색 (광범위 수집)"""
    gn = GoogleNews(lang='en', country='US') # 기본 설정
    results = []
    
    for kw in keywords:
        try:
            search = gn.search(kw)
            for entry in search['entries'][:5]:
                results.append({
                    'title': entry.title,
                    'link': entry.link,
                    'content': entry.title, # RSS는 본문이 없으므로 제목으로 대체
                    'source_type': 'GOOGLE_RSS(해외)'
                })
        except Exception as e:
            print(f"Google News 수집 에러 ({kw}): {e}")
    return results

def fetch_newsapi(keywords: List[str]) -> List[Dict]:
    """[해외] NewsAPI.org (메이저 언론사 타겟)"""
    results = []
    for kw in keywords:
        url = f"https://newsapi.org/v2/everything?q={kw}&sortBy=publishedAt&apiKey={NEWS_API_KEY}&language=en"
        try:
            res = requests.get(url)
            articles = res.json().get('articles', [])
            for item in articles[:5]:
                results.append({
                    'title': item['title'],
                    'link': item['url'],
                    'content': item['description'] or item['title'],
                    'source_type': 'NEWS_API(외신)'
                })
        except Exception as e:
             print(f"NewsAPI 수집 에러 ({kw}): {e}")
    return results

# ==========================================
# 4. AI 두뇌 (Gemini Processor)
# ==========================================

def analyze_with_gemini(news_item: Dict) -> Dict:
    """
    Gemini에게 기사 분석, 번역, 요약, 분류를 요청
    """
    prompt = f"""
    당신은 '웰다잉(Well-Dying)' 전문 뉴스 분석가입니다. 
    아래 기사는 영어일 수도 있고 한국어일 수도 있습니다.
    
    [기사 정보]
    제목: {news_item['title']}
    내용: {news_item['content']}
    출처: {news_item['source_type']}

    [지시사항]
    1. **관련성 판단**: 이 기사가 '죽음, 호스피스, 장례, 존엄사, 연명의료'와 밀접한 관련이 있는지 판단하세요. (광고나 단순 부고는 제외)
    2. **번역 및 요약**: 기사가 외국어라면 **반드시 한국어로 번역**하여 핵심 내용을 3문장으로 요약하세요.
    3. **감정 분석**: 기사의 톤을 [희망(긍정), 논쟁(중립), 비보(부정)] 중 하나로 분류하세요.
    4. **카테고리**: [정책/법안, 기술/의학, 문화/에세이, 사건/사고] 중 하나로 분류하세요.
    5. **중요도**: 1~5점 (5점이 가장 중요). 웰다잉 트렌드나 법안 변경 등은 높은 점수.

    [응답 형식 - JSON만 출력]
    {{
        "is_relevant": true/false,
        "summary": "한국어 요약 내용...",
        "sentiment": "감정분석 결과",
        "category": "카테고리",
        "priority": 3
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(text)
    except Exception as e:
        print(f"AI 분석 실패: {e}")
        return None

# ==========================================
# 5. 메인 실행 컨트롤러 (Main)
# ==========================================

def main():
    print("🚀 웰다잉 뉴스 아카이빙 시스템 가동...")
    
    # 1. 구글 시트 연결
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEET_KEY, scope)
    client = gspread.authorize(creds)
    sheet = client.open("Global Well-Dying Archive").sheet1 # 시트 이름 확인!
    
    existing_links = get_existing_links(sheet)
    print(f"📊 기존 데이터 {len(existing_links)}개 로드 완료.")

    # 2. 모든 소스에서 뉴스 수집
    all_news = []
    
    # (A) 국내
    print("🔍 네이버 뉴스 탐색 중...")
    all_news.extend(fetch_naver_news(["웰다잉", "호스피스", "존엄사", "연명의료"]))
    
    # (B) 해외 (Google RSS)
    print("🔍 구글 글로벌 뉴스 탐색 중...")
    all_news.extend(fetch_pygooglenews(["Euthanasia law", "Hospice care trends"]))
    
    # (C) 해외 (NewsAPI)
    print("🔍 NewsAPI 외신 탐색 중...")
    all_news.extend(fetch_newsapi(["End of life care", "Assisted dying"]))

    print(f"총 {len(all_news)}개의 후보 기사 수집됨. AI 분석 시작...")

    # 3. AI 분석 및 필터링
    new_rows = []
    
    for news in all_news:
        #
        # === [속도 조절 코드 시작] ===
        print(f"⏳ 과속 방지: 15초 대기 중... (현재 기사: {news['title'][:10]}...)")
        time.sleep(15) 
        # ===========================
    
        # 중복 검사 (링크 기준)
        if news['link'] in existing_links:
            continue
            
        # AI 분석
        analysis = analyze_with_gemini(news)
        
        if analysis and analysis['is_relevant']:
            # 데이터 행 생성
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            row = [
                timestamp,
                news['source_type'],      # 출처 분류 (NAVER, GOOGLE_RSS, NEWS_API)
                analysis['category'],
                news['title'],
                analysis['summary'],      # 한국어로 번역된 요약
                analysis['sentiment'],
                analysis['priority'],
                news['link']
            ]
            new_rows.append(row)
            print(f"✅ 저장됨: {news['title']}")
            
            # 중요 뉴스 슬랙 알림 (중요도 4 이상)
            if analysis['priority'] >= 4:
                send_slack_alert(news, analysis)
        else:
            print(f"❌ 스킵됨(관련없음): {news['title']}")

    # 4. 시트에 일괄 저장 (API 호출 최소화)
    if new_rows:
        sheet.append_rows(new_rows)
        print(f"💾 총 {len(new_rows)}개의 새로운 뉴스가 저장되었습니다.")
    else:
        print("☁️ 저장할 새로운 뉴스가 없습니다.")

if __name__ == "__main__":
    main()