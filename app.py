import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from dotenv import load_dotenv
import subprocess

# 1. 환경 설정 및 페이지 제목 (가장 먼저 실행됨)
load_dotenv()
st.set_page_config(page_title="Well-Dying Archive", layout="wide", page_icon="🕯️")
st.title("🕯️ 글로벌 웰다잉 뉴스 관제센터")

# 2. 구글 시트 연결 함수 (캐싱 사용)
@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # .env 파일에서 JSON 파일 경로 가져오기
    json_path = os.getenv("GOOGLE_SHEET_JSON_PATH")
    
    # 경로가 없거나 파일이 없으면 에러 발생시키기 (화면에 보여주기 위해)
    if not json_path or not os.path.exists(json_path):
        raise FileNotFoundError(f"키 파일({json_path})을 찾을 수 없습니다. .env 파일을 확인하세요.")
        
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    return gspread.authorize(creds)

# 3. 탭 생성 (내용을 채우기 전에 껍데기부터 만듭니다)
tabs = st.tabs(["📰 뉴스 모니터링", "🌍 국가 설정", "🔑 키워드 설정", "📡 블로그(RSS) 설정"])

# 4. 실제 기능 연결 (여기를 try-except로 감싸서 안전하게 만듭니다)
try:
    # 로딩 중 표시
    with st.spinner("구글 시트에 연결 중입니다..."):
        client = get_client()
        wb = client.open("Global Well-Dying Archive")

    # === [탭 1] 뉴스 모니터링 ===
    with tabs[0]:
        st.subheader("📰 수집된 뉴스 목록")
        
        # 수동 실행 버튼
        if st.button("🚀 시스템 즉시 가동 (뉴스 수집 시작)", type="primary"):
            status_area = st.empty() # 상태 메시지 표시 공간
            status_area.info("뉴스 수집 엔진을 가동합니다... (터미널을 확인하세요)")
            
            # collector.py 실행
            process = subprocess.run(["python3", "collector.py"], capture_output=True, text=True)
            
            if process.returncode == 0:
                status_area.success("✅ 수집 완료! 아래 표를 새로고침하세요.")
                with st.expander("실행 로그 보기"):
                    st.code(process.stdout)
            else:
                status_area.error("❌ 수집 중 에러 발생")
                st.error(process.stderr)
        
        # 뉴스 데이터 표시
        try:
            news_sheet = wb.worksheet("News")
            data = news_sheet.get_all_records()
            df = pd.DataFrame(data)
            if not df.empty:
                # 최신순 정렬 (수집일시 기준)
                if '수집일시' in df.columns:
                    df = df.sort_values(by="수집일시", ascending=False)
                st.dataframe(df, use_container_width=True)
            else:
                st.info("아직 수집된 뉴스가 없습니다. 위 버튼을 눌러보세요.")
        except gspread.exceptions.WorksheetNotFound:
            st.warning("'News' 탭을 찾을 수 없습니다. 구글 시트에 탭을 만들어주세요.")

    # === [탭 2] 국가 설정 ===
    with tabs[1]:
        st.subheader("🌍 수집 대상 국가 관리")
        try:
            ws_config = wb.worksheet("Config")
            df_config = pd.DataFrame(ws_config.get_all_records())
            st.dataframe(df_config, use_container_width=True)
            
            st.markdown("---")
            st.write("#### ➕ 국가 추가")
            c1, c2, c3 = st.columns(3)
            with c1: code = st.text_input("국가코드 (예: DE)", key="c_code")
            with c2: lang = st.text_input("언어코드 (예: de)", key="c_lang")
            with c3: name = st.text_input("국가명 (예: 독일)", key="c_name")
            
            if st.button("국가 추가하기"):
                if code and lang and name:
                    ws_config.append_row([code, lang, name])
                    st.success(f"{name} 추가 완료! 탭을 다시 클릭하면 갱신됩니다.")
                else:
                    st.warning("모든 칸을 입력해주세요.")
        except gspread.exceptions.WorksheetNotFound:
            st.error("'Config' 탭이 없습니다.")

    # === [탭 3] 키워드 설정 ===
    with tabs[2]:
        st.subheader("🔑 검색 키워드 관리")
        try:
            ws_kw = wb.worksheet("Keywords")
            df_kw = pd.DataFrame(ws_kw.get_all_records())
            st.dataframe(df_kw, use_container_width=True)
            
            st.markdown("---")
            st.write("#### ➕ 키워드 추가")
            k1, k2 = st.columns(2)
            with k1: new_kw = st.text_input("새 키워드 (예: Pet Loss)", key="k_kw")
            with k2: new_desc = st.text_input("설명 (예: 반려동물 장례)", key="k_desc")
            
            if st.button("키워드 추가하기"):
                if new_kw:
                    ws_kw.append_row([new_kw, new_desc])
                    st.success("키워드 추가 완료!")
        except gspread.exceptions.WorksheetNotFound:
            st.error("'Keywords' 탭이 없습니다.")

    # === [탭 4] 블로그 설정 ===
    with tabs[3]:
        st.subheader("📡 특정 사이트(RSS) 관리")
        try:
            ws_site = wb.worksheet("Sites")
            df_site = pd.DataFrame(ws_site.get_all_records())
            st.dataframe(df_site, use_container_width=True)
            
            st.markdown("---")
            st.write("#### ➕ 사이트 추가")
            s1, s2 = st.columns(2)
            with s1: site_name = st.text_input("사이트명", key="s_name")
            with s2: rss_url = st.text_input("RSS 주소", key="s_url")
            
            if st.button("사이트 추가하기"):
                if site_name and rss_url:
                    ws_site.append_row([site_name, rss_url])
                    st.success("사이트 추가 완료!")
        except gspread.exceptions.WorksheetNotFound:
            st.error("'Sites' 탭이 없습니다.")

except Exception as e:
    # 🚨 여기서 에러를 잡아서 화면에 보여줍니다!
    st.error("🚨 시스템 오류 발생!")
    st.markdown(f"""
    구글 시트에 연결하는 도중 문제가 생겼습니다. 아래 내용을 확인해주세요.
    
    **에러 메시지:**
    `{e}`
    
    **체크리스트:**
    1. `.env` 파일에 `GOOGLE_SHEET_JSON_PATH`가 올바른지 확인하세요.
    2. `service_account.json` 파일이 프로젝트 폴더에 있는지 확인하세요.
    3. 구글 시트 이름이 **"Global Well-Dying Archive"**가 맞는지 확인하세요.
    4. 구글 시트에 4개의 탭(News, Config, Keywords, Sites)이 모두 있는지 확인하세요.
    """)