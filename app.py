import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json

# ---------------------------
# 1. 구글 시트 연결
# ---------------------------
@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_path = "service_account.json"

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
        with open(json_path, "w") as f:
            json.dump(service_account_info, f)

    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    return gspread.authorize(creds)

def get_data(sheet_name):
    client = get_client()
    sh = client.open("Global Well-Dying Archive")
    return sh.worksheet(sheet_name)

# ---------------------------
# 2. 메인 UI
# ---------------------------
st.set_page_config(page_title="Global Well-Dying Archive", layout="wide")
st.title("🌍 Global Well-Dying News Archive")

with st.sidebar:
    st.header("⚙️ 설정 관리")
    
    # --- 1. 검색 키워드 ---
    with st.expander("🔍 검색 키워드 관리"):
        new_keyword = st.text_input("새 키워드 추가")
        if st.button("키워드 저장"):
            if new_keyword:
                sh = get_data("Keywords")
                sh.append_row([new_keyword])
                st.success(f"'{new_keyword}' 추가 완료!")
                st.cache_data.clear()

    # --- 2. 금지어 ---
    with st.expander("🚫 금지어(필터) 관리"):
        new_ban_word = st.text_input("새 금지어 추가")
        if st.button("금지어 저장"):
            if new_ban_word:
                try:
                    sh = get_data("BanWords")
                    sh.append_row([new_ban_word])
                    st.success(f"'{new_ban_word}' 차단 완료!")
                    st.cache_data.clear()
                except:
                    st.error("'BanWords' 시트를 먼저 만들어주세요!")

    # --- 3. [NEW] 모니터링 사이트 ---
    with st.expander("📡 모니터링 사이트(RSS)"):
        st.caption("뉴스 사이트의 RSS 주소를 입력하세요.")
        new_site_name = st.text_input("사이트 이름 (예: CNN)")
        new_site_url = st.text_input("RSS 주소 (URL)")
        
        if st.button("사이트 저장"):
            if new_site_name and new_site_url:
                try:
                    sh = get_data("Sites")
                    sh.append_row([new_site_name, new_site_url])
                    st.success(f"'{new_site_name}' 추가 완료!")
                    st.cache_data.clear()
                except:
                    st.error("'Sites' 시트(탭)가 있는지 확인하세요!")
        
        # 등록된 사이트 목록 보기
        try:
            sh = get_data("Sites")
            sites_data = sh.get_all_records()
            if sites_data:
                st.caption(f"현재 {len(sites_data)}개 감시 중")
                st.dataframe(pd.DataFrame(sites_data), hide_index=True)
        except:
            st.warning("'Sites' 탭이 없습니다.")

    st.divider()
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

# --- 메인 뉴스 화면 ---
try:
    sh = get_data("News")
    rows = sh.get_all_records()
    df = pd.DataFrame(rows)

    if not df.empty:
        col1, col2 = st.columns(2)
        with col1:
            search_query = st.text_input("제목 검색", placeholder="관심있는 단어를 입력하세요")
        with col2:
            source_filter = st.multiselect("출처 필터", df['출처'].unique())

        if search_query:
            df = df[df['제목'].str.contains(search_query, case=False)]
        if source_filter:
            df = df[df['출처'].isin(source_filter)]

        st.markdown(f"### 📰 수집된 뉴스 ({len(df)}건)")
        st.dataframe(
            df[['수집일시', '출처', '제목', '요약', '링크']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "링크": st.column_config.LinkColumn("기사 보기")
            }
        )
    else:
        st.info("아직 수집된 뉴스가 없습니다.")
except Exception as e:
    st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
