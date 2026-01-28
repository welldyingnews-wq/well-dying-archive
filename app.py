import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

# ---------------------------
# 1. 구글 시트 연결
# ---------------------------
@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_path = os.getenv("GOOGLE_SHEET_JSON_PATH", "service_account.json")

    # 클라우드 환경 대응 (Secrets 사용)
    if not os.path.exists(json_path):
        if "GOOGLE_JSON_CONTENT" in st.secrets:
            with open(json_path, "w") as f:
                f.write(st.secrets["GOOGLE_JSON_CONTENT"])
        else:
            st.error("❌ 키 파일을 찾을 수 없습니다.")
            return None

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

# --- 사이드바: 설정 관리 ---
with st.sidebar:
    st.header("⚙️ 설정 관리")
    
    # 1. 키워드 추가
    with st.expander("🔍 검색 키워드 관리"):
        new_keyword = st.text_input("새 키워드 추가")
        if st.button("키워드 저장"):
            if new_keyword:
                sh = get_data("Keywords")
                sh.append_row([new_keyword])
                st.success(f"'{new_keyword}' 추가 완료!")
                st.cache_data.clear()

    # 2. 금지어 관리 (새로 추가된 기능!)
    with st.expander("🚫 금지어(필터) 관리"):
        st.caption("제목에 이 단어가 있으면 수집하지 않습니다.")
        new_ban_word = st.text_input("새 금지어 추가")
        if st.button("금지어 저장"):
            if new_ban_word:
                try:
                    sh = get_data("BanWords")
                    sh.append_row([new_ban_word])
                    st.success(f"'{new_ban_word}' 차단 완료!")
                    st.cache_data.clear()
                except:
                    st.error("구글 시트에 'BanWords' 탭을 먼저 만들어주세요!")
        
        # 현재 금지어 목록 보여주기
        try:
            sh = get_data("BanWords")
            ban_list = sh.col_values(1)[1:] # 헤더 제외
            st.write(f"현재 {len(ban_list)}개 차단 중:")
            st.code(", ".join(ban_list))
        except:
            st.warning("'BanWords' 탭이 없습니다.")

    st.divider()
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

# --- 메인 화면: 뉴스 보기 ---
sh = get_data("News")
rows = sh.get_all_records()
df = pd.DataFrame(rows)

if not df.empty:
    # 필터링
    col1, col2 = st.columns(2)
    with col1:
        search_query = st.text_input("제목 검색", placeholder="관심있는 단어를 입력하세요")
    with col2:
        source_filter = st.multiselect("출처 필터", df['출처'].unique())

    if search_query:
        df = df[df['제목'].str.contains(search_query, case=False)]
    if source_filter:
        df = df[df['출처'].isin(source_filter)]

    # 최신순 정렬
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
