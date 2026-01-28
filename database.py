import os
from supabase import create_client
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# Supabase 접속 정보 가져오기
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 연결 클라이언트 생성
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    print("⚠️ 경고: Supabase URL 또는 KEY가 설정되지 않았습니다.")

def save_news(news_list):
    """
    뉴스 리스트를 받아 Supabase에 저장하는 함수
    (이미 있는 링크는 건너뜀)
    """
    if not supabase: return 0
    if not news_list: return 0

    count = 0
    for news in news_list:
        try:
            # 1. 링크 중복 확인 (이미 저장된 뉴스인가?)
            # 'link' 컬럼이 news['link']와 같은 데이터가 있는지 카운트
            existing = supabase.table("news").select("id", count="exact").eq("link", news['link']).execute()
            
            if existing.count > 0:
                continue # 이미 있으면 패스

            # 2. 없으면 저장
            data = {
                "collected_at": news.get('collected_at'),
                "source": news.get('source_type'),
                "title": news.get('title'),
                "link": news.get('link'),
                # 나중에 AI가 채울 칸은 비워둠 (null)
            }
            supabase.table("news").insert(data).execute()
            count += 1
            
        except Exception as e:
            print(f"❌ 저장 에러 ({news['title']}): {e}")
            
    return count

def load_news():
    """
    저장된 모든 뉴스를 최신순으로 가져오는 함수
    """
    if not supabase: return []
    
    try:
        response = supabase.table("news").select("*").order("id", desc=True).execute()
        return response.data
    except Exception as e:
        print(f"❌ 불러오기 에러: {e}")
        return []
