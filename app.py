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
    st.header("⚙️ 설정 관리")
    
    # --- [NEW] 수집 주기 설정 ---
    with st.expander("⏱️ 수집 주기 설정"):
        try:
            sh_settings = get_data("Settings")
            current_interval = sh_settings.cell(2, 2).value
            st.info(f"현재 설정: {current_interval}분 마다")
            
            new_interval = st.selectbox(
                "주기 변경", 
                options=["30", "60", "120", "180", "360", "720"],
                index=1
            )
            
            if st.button("주기 적용"):
                sh_settings.update_cell(2, 2, new_interval)
                st.success(f"{new_interval}분으로 변경 완료!")
                st.cache_data.clear()
        except:
            st.error("'Settings' 시트가 없습니다.")

    # --- 기존 메뉴들 ---
    with st.expander("🔍 검색 키워드 관리"):
        new_keyword = st.text_input("새 키워드 추가")
        if st.button("키워드 저장"):
            if new_keyword:
                get_data("Keywords").append_row([new_keyword])
                st.success("추가 완료!")
                
    with st.expander("🚫 금지어 관리"):
        new_ban_word = st.text_input("새 금지어 추가")
        if st.button("금지어 저장"):
            if new_ban_word:
                get_data("BanWords").append_row([new_ban_word])
                st.success("추가 완료!")

    with st.expander("📡 모니터링 사이트"):
        new_site_name = st.text_input("사이트 이름")
        new_site_url = st.text_input("RSS URL")
        if st.button("사이트 저장"):
            if new_site_name and new_site_url:
                get_data("Sites").append_row([new_site_name, new_site_url])
                st.success("추가 완료!")

    st.divider()
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()

# --- 메인 화면 ---
try:
    df = pd.DataFrame(get_data("News").get_all_records())
    if not df.empty:
        col1, col2 = st.columns(2)
        search = col1.text_input("제목 검색")
        source = col2.multiselect("출처 필터", df['출처'].unique())
        
        if search: df = df[df['제목'].str.contains(search, case=False)]
        if source: df = df[df['출처'].isin(source)]

        st.markdown(f"### 📰 수집된 뉴스 ({len(df)}건)")
        st.dataframe(df[['수집일시', '출처', '제목', '요약', '링크']], use_container_width=True, hide_index=True, column_config={"링크": st.column_config.LinkColumn("보기")})
    else: st.info("데이터 없음")
except Exception as e: st.error(f"오류: {e}")
