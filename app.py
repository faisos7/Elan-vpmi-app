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
st.set_page_config(page_title="엘랑비탈 ERP v.1.0.0", page_icon="🏥", layout="wide")

# [중요] 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))

# 수율 및 재고 관리 상수
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,
    "PACK_UNIT_KG": 0.15,
    "DRINK_RATIO": 6.5
}

# ==============================================================================
# 2. 보안 설정 (Password)
# ==============================================================================
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
            st.title("🔒 엘랑비탈 ERP v.1.0.0")
            st.markdown("---")
            with st.form("login"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

# ==============================================================================
# 3. 구글 시트 연동 및 재고 함수 (Gspread)
# ==============================================================================
def get_gspread_client():
    secrets = st.secrets["gcp_service_account"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(secrets, scopes=scopes)
    return gspread.authorize(creds)

def update_inventory(item_name, change_qty):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("inventory")
        cell = sheet.find(item_name)
        if cell:
            current_val = sheet.cell(cell.row, 2).value
            current_val = float(current_val) if current_val else 0.0
            new_val = current_val + change_qty
            sheet.update_cell(cell.row, 2, new_val)
            sheet.update_cell(cell.row, 4, datetime.now(KST).strftime("%Y-%m-%d %H:%M"))
            return True
        return False
    except: return False

def show_inventory_dashboard():
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("inventory")
        data = sheet.get_all_records()
        df_inv = pd.DataFrame(data)
        if not df_inv.empty:
            low_stock = df_inv[df_inv['현재고'].astype(float) <= 10]
            if not low_stock.empty:
                for _, row in low_stock.iterrows():
                    st.error(f"🚨 **재고 부족**: {row['항목명']} ({row['현재고']} {row['단위']} 남음)")
            with st.expander("📦 실시간 재고 현황판"):
                st.dataframe(df_inv, use_container_width=True)
    except: pass

@st.cache_data(ttl=60)
def load_data_from_sheet():
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").sheet1
        data = sheet.get_all_records()
        db = {}
        for row in data:
            name = row.get('이름')
            if not name: continue
            items_list = []
            raw_items = str(row.get('주문내역', '')).split(',')
            for item in raw_items:
                if ':' in item:
                    p_name, p_qty = item.split(':')
                    items_list.append({"제품": p_name.strip(), "수량": int(p_qty.strip())})
            db[name] = {
                "group": row.get('그룹', ''), "items": items_list,
                "default": True if str(row.get('기본발송', '')).upper() == 'O' else False,
                "start_date_raw": str(row.get('시작일', ''))
            }
        return db
    except: return {}

def save_to_history(record_list):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("history")
        for record in reversed(record_list): sheet.insert_row(record, 2)
        return True
    except: return False

def save_production_record(sheet_name, record):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        sheet.insert_row(record, 2)
        return True
    except: return False

def save_yield_log(record):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("yield_logs")
        sheet.insert_row(record, 2)
        return True
    except: return False

def save_ph_log(record):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("ph_logs")
        sheet.insert_row(record, 2)
        return True
    except: return False

@st.cache_data(ttl=60)
def load_sheet_data(sheet_name, sort_col=None):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        df = pd.DataFrame(sheet.get_all_records())
        if not df.empty and sort_col: df = df.sort_values(by=sort_col, ascending=False)
        return df
    except: return pd.DataFrame()

# ==============================================================================
# 4. 데이터 초기화 및 보조 로직
# ==============================================================================
def init_session_state():
    if 'target_date' not in st.session_state: st.session_state.target_date = datetime.now(KST)
    if 'patient_db' not in st.session_state: st.session_state.patient_db = load_data_from_sheet()
    if 'raw_material_list' not in st.session_state:
        st.session_state.raw_material_list = ["우유", "계란", "배추", "무", "마늘", "인삼", "동백꽃", "개망초", "아카시아 꽃"]
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {"계란커드 스타터": {"batch_size": 9, "materials": {"개망초": 8, "아카시아": 1}}}
    if 'regimen_db' not in st.session_state:
        st.session_state.regimen_db = {"울산 자궁근종": "장미꽃 대사체 및 인삼 전체 대사체 활용"}

init_session_state()

def calculate_round_v4(start_date_input, current_date_input, group_type):
    try:
        sd = pd.to_datetime(start_date_input).date()
        delta = (current_date_input.date() - sd).days
        weeks = round(delta / 7)
        r = (weeks + 1 if group_type == "매주 발송" else (weeks // 2) + 1)
        return r, sd.strftime('%Y-%m-%d')
    except: return 1, "오류"

# ==============================================================================
# 5. 메인 화면 구성
# ==============================================================================
show_inventory_dashboard()
st.sidebar.title("📌 메뉴")
app_mode = st.sidebar.radio("작업 모드", ["🚛 배송/주문 관리", "🏭 생산/공정 관리"])

if app_mode == "🚛 배송/주문 관리":
    target_date = st.date_input("발송일", datetime.now(KST))
    db = st.session_state.patient_db
    sel_p = {}
    
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("매주 발송")
        for k, v in db.items():
            if v['group'] == "매주 발송":
                r, _ = calculate_round_v4(v['start_date_raw'], target_date, "매주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default']): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}
    with col_b:
        st.subheader("격주/기타")
        for k, v in db.items():
            if v['group'] != "매주 발송":
                r, _ = calculate_round_v4(v['start_date_raw'], target_date, "격주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default']): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}

    t1, t2, t3, t4, t5 = st.tabs(["📦 라벨", "📊 총합", "🧪 혼합", "📊 커드수요", "📜 히스토리 분석"])

    with t1:
        if st.button("📝 발송 저장 및 재고 차감"):
            records = []
            for n, d in sel_p.items():
                c_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in d['items']])
                records.append([target_date.strftime('%Y-%m-%d'), n, d['group'], d['round'], c_str])
                for i in d['items']: update_inventory(i['제품'], -float(i['수량']))
            if save_to_history(records): st.success("저장 완료!")

    with t5:
        st.header("📜 발송 히스토리 및 누적 분석")
        h_df = load_sheet_data("history", "발송일")
        
        if not h_df.empty:
            # --- 분석 데이터 가공 ---
            parsed_data = []
            for _, row in h_df.iterrows():
                items = str(row['발송내역']).split(',')
                for it in items:
                    if ':' in it:
                        p_name, p_qty = it.split(':')
                        parsed_data.append({
                            "발송일": row['발송일'], "이름": row['이름'], 
                            "그룹": row['그룹'], "제품": p_name.strip(), "수량": int(p_qty.strip())
                        })
            p_df = pd.DataFrame(parsed_data)
            
            # --- 1. 제품별 누적 총합 ---
            st.subheader("📊 제품별 누적 출고 총합")
            c1, c2 = st.columns(2)
            
            with c1:
                st.write("**[전체 환자 제품 총합]**")
                st.dataframe(p_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False))
            
            with c2:
                st.write("**['울산' 환자 제외 제품 총합]**")
                non_ulsan_p = p_df[~p_df['이름'].str.contains("울산") & (p_df['그룹'] != "울산")]
                st.dataframe(non_ulsan_p.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False))

            st.divider()
            
            # --- 2. 개인별 누적 총합 ---
            st.subheader("👤 개인별 누적 발송 합계")
            mode_p = st.radio("필터 선택", ["전체 개인별 합계", "울산 제외 개인별 합계"], horizontal=True)
            
            sum_df = p_df if "전체" in mode_p else non_ulsan_p
            pivot_p = sum_df.pivot_table(index="이름", columns="제품", values="수량", aggfunc="sum", fill_value=0)
            pivot_p["전체수량"] = pivot_p.sum(axis=1)
            st.dataframe(pivot_p.sort_values("전체수량", ascending=False))
            
            st.divider()
            st.subheader("📂 전체 로그")
            st.dataframe(h_df)
        else:
            st.info("기록이 없습니다.")

elif app_mode == "🏭 생산/공정 관리":
    st.title("🏭 생산/공정 관리 v.1.0.0")
    t_y, t_c, t_p = st.tabs(["📊 수율", "🧀 커드", "🔬 pH/기타"])
    
    with t_y:
        y_bot = st.number_input("우유(통)", 1, 100, 10)
        st.info(f"예상 커드: {y_bot * 0.5} kg")
        y_act = st.number_input("실제(kg)", 0.0)
        if st.button("💾 수율 저장"):
            save_yield_log([datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "커드", y_bot, y_bot*0.5, y_act, 0, ""])
            st.success("저장됨")

    with t_c:
        m_cnt = st.number_input("우유 개수", 1, 100, 30)
        if st.button("🚀 대사 시작 (재고 차감)"):
            update_inventory("우유", -float(m_cnt))
            st.success("재고 차감 완료")

    with t_p:
        ph = st.number_input("pH", 0.0, 14.0, 5.0, step=0.01)
        if st.button("💾 pH 저장"):
            save_ph_log(["DIRECT", datetime.now(KST).strftime("%Y-%m-%d %H:%M"), ph, 30.0, ""])
            st.success("저장됨")
