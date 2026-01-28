import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import database  # Supabase 연결

# ---------------------------
# 1. 구글 시트 연결 (설정 관리용)
# ---------------------------
@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_path = "service_account.json"
    
    # 1. 파일이 없으면? -> 스트림릿 Secrets에서 꺼내서 만든다!
    if not os.path.exists(json_path):
        # (1) 우리가 아까 저장한 GOOGLE_SHEET_JSON 방식을 먼저 찾음
        if "GOOGLE_SHEET_JSON" in st.secrets:
            json_content = st.secrets["GOOGLE_SHEET_JSON"]
            with open(json_path, "w") as f:
                f.write(json_content)
            print("✅ 스트림릿 Secrets(GOOGLE_SHEET_JSON)에서 인증 파일을 생성했습니다.")
            
        # (2) 혹시 옛날 방식(낱개 저장)일 경우를 대비해 예비책으로 남겨둠
        elif "private_key" in st.secrets:
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
            
        else:
            # 둘 다 없으면 에러!
            st.error("❌ 에러: Secrets에 'GOOGLE_SHEET_JSON' 키가 없습니다.")
            return None
        
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
    
    # --- 수집 주기 ---
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
        
        # 에러 메시지 자세히 보기
        except Exception as e:
            st.error(f"⚠️ 에러 발생: {e}")
            st.caption("힌트: Secrets 설정이나 구글 시트 이름을 확인하세요.")

    # --- 키워드/금지어/사이트 관리 ---
    with st.expander("🔍 키워드 관리"):
        try:
            new_keyword = st.text_input("새 키워드")
            if st.button("키워드 저장"):
                if new_keyword:
                    get_data("Keywords").append_row([new_keyword])
                    st.success("저장 완료")
        except Exception as e: st.error(f"에러: {e}")
                
    with st.expander("🚫 금지어 관리"):
        try:
            new_ban_word = st.text_input("새 금지어")
            if st.button("금지어 저장"):
                if new_ban_word:
                    get_data("BanWords").append_row([new_ban_word])
                    st.success("저장 완료")
        except Exception as e: st.error(f"에러: {e}")

    with st.expander("📡 사이트 관리"):
        try:
            name = st.text_input("사이트명")
            url = st.text_input("RSS URL")
            if st.button("사이트 저장"):
                if name and url:
                    get_data("Sites").append_row([name, url])
                    st.success("저장 완료")
        except Exception as e: st.error(f"에러: {e}")

    st.divider()
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()

# --- 메인 화면 ---
try:
    # Supabase에서 데이터 로드
    raw_data = database.load_news()
    df = pd.DataFrame(raw_data)

    if not df.empty:
        # 보기 좋게 컬럼명 변경
        df = df.rename(columns={
            "collected_at": "수집일시",
            "source": "출처",
            "title": "제목",
            "link": "링크"
        })

        # 필터링
        col1, col2 = st.columns(2)
        search = col1.text_input("제목 검색", placeholder="검색어 입력")
        source = col2.multiselect("출처 필터", df['출처'].unique())
        
        if search: df = df[df['제목'].str.contains(search, case=False)]
        if source: df = df[df['출처'].isin(source)]

        st.markdown(f"### 📰 수집된 뉴스 ({len(df)}건)")
        
        # 데이터 표시
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "링크": st.column_config.LinkColumn("원문 보기")
            },
            column_order=["수집일시", "출처", "제목", "링크"]
        )
    else:
        st.info("아직 수집된 뉴스가 없습니다. 깃허브 Actions를 실행해주세요!")

except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
