import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials

# 1. 시스템 설정
st.set_page_config(page_title="엘랑비탈 ERP v.1.1.4", layout="wide")
KST = timezone(timedelta(hours=9))

# 수율 상수
YIELD_CONSTANTS = {"MILK_BOTTLE_TO_CURD_KG": 0.5}

# 2. 기초 함수
def get_gspread_client():
    try:
        secrets = st.secrets["gcp_service_account"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        return gspread.authorize(creds)
    except: return None

# 로그인 체크 (단순화)
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 엘랑비탈 ERP v.1.1.4")
    pw = st.text_input("비밀번호:", type="password")
    if st.button("로그인"):
        if pw == "I love VPMI":
            st.session_state.authenticated = True
            st.rerun()
        else: st.error("비밀번호 불일치")
    st.stop()

# 3. 메인 UI 및 메뉴
st.sidebar.title("🏥 엘랑비탈 ERP v.1.1.4")
main_menu = st.sidebar.radio("📋 메뉴", ["🚛 배송 및 주문 관리", "🏭 생산 및 공정 관리", "📈 누적 데이터 분석", "📦 재고 현황판"])

# 4. 생산 및 공정 관리 (오류 수정 핵심 구간)
if main_menu == "🏭 생산 및 공정 관리":
    st.header("🏭 생산 공정 품질 관리 및 정밀 레시피")
    
    # 탭 선언 (리스트로 반환됨)
    p_tabs = st.tabs(["📊 수율/예측", "🧪 커드 생산 관리", "🗓️ 연간 스케줄", "🌡️ pH/품질"])

    # 탭 1: 수율/예측 (인덱스 [0] 사용)
    with p_tabs[0]:
        st.subheader("생산량 예측")
        y_bottles = st.number_input("우유 투입 (통)", 1, 100, 10)
        expected = y_bottles * 0.5
        st.metric("예상 생산량", f"{expected} kg")

    # 탭 2: 커드 생산 관리 (인덱스 [1] 사용 - 사용자 요청 레시피)
    with p_tabs[1]:
        st.subheader("🧪 정밀 레시피 (전재료 합산 방식)")
        col1, col2 = st.columns(2)
        with col1:
            batch_milk = st.number_input("우유 투입 개수", 1, 100, 20) # 20통 기준
            is_egg = st.toggle("계란 커드 모드", value=True)
            
            milk_kg = batch_milk * 2.3
            egg_kg = milk_kg / 4 if is_egg else 0
            base_total = milk_kg + egg_kg
            
            # 스타터 계산 (10% + 5% 로직)
            gaemang_aka = base_total * 0.1
            cool_starter = base_total * 0.05
            final_weight = base_total + gaemang_aka + cool_starter
            
        with col2:
            st.success(f"### ⚖️ 최종 합계 중량: {final_weight:.2f} kg")
            st.write(f"📍 우유: {milk_kg:.1f}kg / 계란: {egg_kg:.1f}kg")
            st.write(f"📍 개망초(8/9): {gaemang_aka*(8/9):.2f}kg")
            st.write(f"📍 아카시아(1/9): {gaemang_aka*(1/9):.2f}kg")
            st.write(f"📍 시원한것: {cool_starter:.2f}kg")

    # 탭 3: 연간 스케줄 (인덱스 [2] 사용)
    with p_tabs[2]:
        st.write("월별 주요 대사체 스케줄을 확인하세요.")

    # 탭 4: 품질 (인덱스 [3] 사용)
    with p_tabs[3]:
        st.number_input("pH 측정치", 0.0, 14.0, 4.2)

# 나머지 메뉴(배송, 분석 등)는 기존 로직을 동일하게 유지하되 
# 위와 같이 탭 번호([0], [1] 등)를 명시하여 작성하시면 됩니다.
