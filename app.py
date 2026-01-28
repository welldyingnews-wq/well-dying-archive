import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json

# ⭐ Supabase 창고지기 불러오기 (필수!)
import database 

# ---------------------------
# 1. 구글 시트 연결 (설정 관리용)
# ---------------------------
@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_path = "service_account.json"
    
    # 스트림릿 Secrets에서 구글 키 가져오기
    if "private_key" in st.secrets:
        service_account_info = {
            "type": "service_account",
            "project_id": st.secrets["project_id"],
            "private_key_id": st.secrets["private_key_id"],
            "private_key": st.secrets["private_key"],
            "client_email": st.secrets["client_email"],
            "client_id": st.secrets["client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": st.secrets["client_x509_cert_url"]
        }
        with open(json_path, "w") as f: json.dump(service_account_info, f)
        
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    return gspread.authorize(creds)

def get_data(sheet_name):
    client = get_client()
    return client.open("Global Well-Dying Archive").worksheet(sheet_name)

# ---------------------------
# 2. 메인 UI
# ---------------------------
st.set_page_config(page_title="Global Well-Dying Archive", layout="wide")
st.title("🌍 Global Well-Dying News Archive")

with st.sidebar:
    st.header("⚙️ 설정 관리 (구글 시트)")
    
    # --- 수집 주기 설정 ---
    with st.expander("⏱️ 수집 주기 설정"):
        try:
            sh_settings = get_data("Settings")
            current_interval = sh_settings.cell(2, 2).value
            st.info(f"현재 설정: {current_interval}분 마다")
            
            new_interval = st.selectbox("주기 변경", options=["30", "60", "120", "180", "360", "720"], index=1)
            
            if st.button("주기 적용"):
                sh_settings.update_cell(2, 2, new_interval)
                st.success(f"{new_interval}분으로 변경 완료!")
                st.cache_data.clear()
        except:
            st.error("'Settings' 시트가 없습니다.")

    # --- 키워드 관리 ---
    with st.expander("🔍 검색 키워드 관리"):
        new_keyword = st.text_input("새 키워드 추가")
        if st.button("키워드 저장"):
            if new_keyword:
                get_data("Keywords").append_row([new_keyword])
                st.success("추가 완료!")
                
    # --- 금지어 관리 ---
    with st.expander("🚫 금지어 관리"):
        new_ban_word = st.text_input("새 금지어 추가")
        if st.button("금지어 저장"):
            if new_ban_word:
                get_data("BanWords").append_row([new_ban_word])
                st.success("추가 완료!")

    # --- 사이트 관리 ---
    with st.expander("📡 모니터링 사이트"):
        new_site_name = st.text_input("사이트 이름")
        new_site_url = st.text_input("RSS URL")
        if st.button("사이트 저장"):
            if new_site_name and new_site_url:
                get_data("Sites").append_row([new_site_name, new_site_url])
                st.success("추가 완료!")

    st.divider()
    
    # AI 분석 버튼 (원할 때 누르기)
    if st.button("🤖 AI 뉴스 분석 (최신 5개)"):
        import ai_analyst
        with st.spinner("제미나이가 기사를 읽는 중..."):
            ai_analyst.analyze_news()
        st.success("분석 완료! 새로고침 해주세요.")

    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()

# --- 메인 화면 (여기가 완전히 바뀌었습니다!) ---
try:
    # 1. Supabase에서 데이터 가져오기
    raw_data = database.load_news()
    df = pd.DataFrame(raw_data)

    if not df.empty:
        # 2. 보기 좋게 컬럼 이름 한글로 변경
        # (Supabase 영어 컬럼 -> 대시보드 한글 컬럼)
        df = df.rename(columns={
            "collected_at": "수집일시",
            "source": "출처",
            "title": "제목",
            "link": "링크",
            "ai_summary": "AI요약",
            "ai_tags": "태그"
        })

        # 3. 필터 UI
        col1, col2 = st.columns(2)
        search = col1.text_input("제목 검색", placeholder="검색어를 입력하세요")
        source = col2.multiselect("출처 필터", df['출처'].unique())
        
        if search: df = df[df['제목'].str.contains(search, case=False)]
        if source: df = df[df['출처'].isin(source)]

        st.markdown(f"### 📰 수집된 뉴스 ({len(df)}건)")
        
        # 4. 데이터 표시 (AI 요약 포함)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "링크": st.column_config.LinkColumn("원문 보기"),
                "AI요약": st.column_config.TextColumn("AI 3줄 요약", width="medium"),
                "태그": st.column_config.TextColumn("태그", width="small")
            },
            # 보여줄 컬럼 순서 지정
            column_order=["수집일시", "출처", "제목", "AI요약", "태그", "링크"]
        )
    else:
        st.info("아직 Supabase에 저장된 뉴스가 없습니다. 수집기를 실행해주세요!")

except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
