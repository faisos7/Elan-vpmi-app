import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
import holidays
import uuid
import json

# ==============================================================================
# 1. 시스템 설정 및 상수 (Config)
# ==============================================================================
st.set_page_config(
    page_title="엘랑비탈 ERP v.1.1.4",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# [중요] 한국 표준시(KST) 설정
KST = timezone(timedelta(hours=9))

# 수율 관리 및 희석 비율 상수
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,  # 우유 1통(2.3L)당 예상 커드 0.5kg
    "PACK_UNIT_KG": 0.15,            # 소포장 단위 150g
    "DRINK_RATIO": 6.5,             # 일반커드 -> 커드시원한것 희석 배수
    "BOTTLE_SIZE_ML": 280,
    "MIX_BOTTLE_ML": 150             # 혼합 제품 용기 사이즈 150ml
}

# ==============================================================================
# 2. 회차 계산 엔진 (월요일 준비 보정 로직)
# ==============================================================================
def calculate_round_final(start_date_input, current_date_input, group_type):
    try:
        if not start_date_input or str(start_date_input).lower() in ['nan', '', 'none']:
            return 1, "날짜 미입력"
        
        sd = pd.to_datetime(start_date_input).date()
        target_date = current_date_input.date() if isinstance(current_date_input, datetime) else current_date_input
        
        start_monday = sd - timedelta(days=sd.weekday())
        target_monday = target_date - timedelta(days=target_date.weekday())
        
        diff_weeks = (target_monday - start_monday).days // 7
        
        if "매주" in str(group_type):
            r = diff_weeks + 1
        elif any(word in str(group_type) for word in ["격주", "유방암", "2주"]):
            r = (diff_weeks // 2) + 1
        else:
            r = 1
            
        return int(max(r, 1)), sd.strftime('%Y-%m-%d')
    except:
        return 1, "형식 오류"

# ==============================================================================
# 3. 보안 및 기초 인프라 (Gspread API)
# ==============================================================================
def get_gspread_client():
    try:
        secrets = st.secrets["gcp_service_account"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"구글 인증 실패: {e}")
        return None

def check_password():
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    def password_entered():
        if st.session_state["password"] == "I love VPMI":
            st.session_state.authenticated = True
            del st.session_state["password"]
        else:
            st.session_state.authenticated = False
    if not st.session_state.authenticated:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.title("🔒 엘랑비탈 ERP v.1.1.4")
            st.markdown("---")
            with st.form("login_form"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

# ==============================================================================
# 4. 데이터 핸들링 로직 (Load / Save)
# ==============================================================================
@st.cache_data(ttl=60)
def load_patient_database():
    client = get_gspread_client()
    if not client: return {}
    try:
        sheet = client.open("vpmi_data").sheet1
        data = sheet.get_all_records()
        db = {}
        for row in data:
            name = str(row.get('이름', '')).strip()
            if not name: continue
            
            items_list = []
            raw_items = str(row.get('주문내역', '')).split(',')
            for item in raw_items:
                if ':' in item:
                    p_name, p_qty = item.split(':')
                    try:
                        items_list.append({"제품": p_name.strip(), "수량": int(p_qty.strip())})
                    except: continue
            
            db[name] = {
                "group": str(row.get('그룹', '일반')),
                "note": str(row.get('비고', '')),
                "default": True if str(row.get('기본발송', '')).upper() == 'O' else False,
                "items": items_list,
                "start_date_raw": str(row.get('시작일', ''))
            }
        return db
    except: return {}

def update_inventory_realtime(item_name, change_qty):
    client = get_gspread_client()
    try:
        sheet = client.open("vpmi_data").worksheet("inventory")
        cell = sheet.find(item_name)
        if cell:
            curr_val = float(sheet.cell(cell.row, 2).value or 0)
            sheet.update_cell(cell.row, 2, curr_val + change_qty)
            sheet.update_cell(cell.row, 4, datetime.now(KST).strftime("%Y-%m-%d %H:%M"))
            return True
        return False
    except: return False

def save_delivery_to_history(records):
    client = get_gspread_client()
    try:
        sheet = client.open("vpmi_data").worksheet("history")
        for rec in reversed(records):
            sheet.insert_row(rec, 2)
        return True
    except: return False

@st.cache_data(ttl=60)
def get_sheet_as_df(sheet_name, sort_col=None):
    client = get_gspread_client()
    try:
        sheet =
