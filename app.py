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
st.set_page_config(page_title="엘랑비탈 ERP v.1.0.1", page_icon="🏥", layout="wide")
KST = timezone(timedelta(hours=9))

YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,
    "PACK_UNIT_KG": 0.15,
    "DRINK_RATIO": 6.5
}

# ==============================================================================
# 2. 보안 및 기초 함수 (Gspread 연동)
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
            st.title("🔒 엘랑비탈 ERP v.1.0.1")
            st.markdown("---")
            with st.form("login"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

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
            curr = float(sheet.cell(cell.row, 2).value or 0)
            sheet.update_cell(cell.row, 2, curr + change_qty)
            return True
        return False
    except: return False

def show_inventory_dashboard():
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("inventory")
        df_inv = pd.DataFrame(sheet.get_all_records())
        if not df_inv.empty:
            low_stock = df_inv[df_inv['현재고'].astype(float) <= 10]
            if not low_stock.empty:
                for _, row in low_stock.iterrows():
                    st.error(f"🚨 **재고 부족**: {row['항목명']} ({row['현재고']} 남음)")
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
# 4. 데이터 초기화 및 세션 상태
# ==============================================================================
def init_session_state():
    if 'target_date' not in st.session_state: st.session_state.target_date = datetime.now(KST)
    if 'patient_db' not in st.session_state: st.session_state.patient_db = load_data_from_sheet()
    if 'raw_material_list' not in st.session_state:
        st.session_state.raw_material_list = ["우유", "계란", "배추", "무", "마늘", "인삼", "동백꽃", "개망초", "아카시아 꽃"]
    
    # [중요] 방식 2를 위한 혼합제품 레시피 정의 (성분 분해용)
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            "혼합 [P.V.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 3, "표고버섯 대사체": 2, "EX": 5}},
            "혼합 [P.P.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 4, "인삼대사체(PAGI) 뇌질환용": 1, "EX": 5}},
            "혼합 [E.R.P.V.P]": {"batch_size": 5, "materials": {"애기똥풀 대사체": 1, "장미꽃 대사체": 1, "인삼대사체(PAGI) 항암용": 1, "송이 대사체": 1, "표고버섯 대사체": 1}},
            "혼합 [Ex.P]": {"batch_size": 10, "materials": {"EX": 8, "인삼대사체(PAGI) 항암용": 2}},
            "혼합 [R.P]": {"batch_size": 4, "materials": {"장미꽃 대사체": 3, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [Edf.P]": {"batch_size": 4, "materials": {"개망초(EDF)": 3, "인삼대사체(PAGI) 항암용": 1}},
            "계란커드 스타터 [혼합]": {"batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}},
            "철원산삼 대사체": {"batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}}
        }
    if 'regimen_db' not in st.session_state:
        st.session_state.regimen_db = {"울산 자궁근종": "처방 데이터 유지"}

init_session_state()

# ==============================================================================
# 5. 메인 로직 실행
# ==============================================================================
def calculate_round_v4(start_date_input, current_date_input, group_type):
    try:
        sd = pd.to_datetime(start_date_input).date()
        delta = (current_date_input.date() - sd).days
        r = round(delta / 7) + 1 if group_type == "매주 발송" else (delta // 14) + 1
        return r, sd.strftime('%Y-%m-%d')
    except: return 1, "오류"

show_inventory_dashboard()
st.sidebar.title("📌 메뉴")
app_mode = st.sidebar.radio("모드", ["🚛 배송/주문 관리", "🏭 생산/공정 관리"])

if app_mode == "🚛 배송/주문 관리":
    target_date = st.date_input("발송일", datetime.now(KST))
    db = st.session_state.patient_db
    sel_p = {}
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("매주 발송")
        for k, v in db.items():
            if v['group'] == "매주 발송":
                r, _ = calculate_round_v4(v['start_date_raw'], target_date, "매주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default'], key=f"chk_{k}"): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}
    with c2:
        st.subheader("격주/기타")
        for k, v in db.items():
            if v['group'] != "매주 발송":
                r, _ = calculate_round_v4(v['start_date_raw'], target_date, "격주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default'], key=f"chk_{k}"): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}

    t1, t2, t3, t4, t5 = st.tabs(["📦 라벨", "📊 총합", "🧪 혼합", "📊 커드수요", "📜 히스토리 분석"])
    
    with t1:
        if st.button("📝 발송 저장 및 재고 차감"):
            records = []
            for n, d in sel_p.items():
                c_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in d['items']])
                records.append([target_date.strftime('%Y-%m-%d'), n, d['group'], d['round'], c_str])
                for itm in d['items']: update_inventory(itm['제품'], -float(itm['수량']))
            if save_to_history(records): st.success("저장 완료!")
        for n, info in sel_p.items():
            with st.container(border=True):
                st.markdown(f"### 🧊 {n} ({info['round']}회)")
                for x in info['items']: st.write(f"□ {x['제품']} {x['수량']}개")

    # --- [탭 5: 히스토리 누적 분석 업그레이드] ---
    with t5:
        st.header("📜 누적 출고 데이터 분석")
        h_df = load_sheet_data("history", "발송일")
        
        if not h_df.empty:
            # 데이터 파싱
            parsed_raw = []
            for _, row in h_df.iterrows():
                for it in str(row['발송내역']).split(','):
                    if ':' in it:
                        try:
                            pn, pq = it.split(':')
                            parsed_raw.append({"이름": row['이름'], "그룹": row['그룹'], "제품": pn.strip(), "수량": int(pq.strip())})
                        except: continue
            p_df = pd.DataFrame(parsed_raw)

            with st.form("stat_analysis"):
                st.subheader("🔍 분석 환자 선택")
                targets = st.multiselect("사람들을 선택하세요 (다중 선택 가능)", sorted(p_df['이름'].unique()))
                submitted = st.form_submit_button("✅ 선택 완료 및 분석 시작")

            if submitted and targets:
                f_df = p_df[p_df['이름'].isin(targets)]
                
                # --- 방식 1: 표면 출고량 (혼합 제품 그대로 표시) ---
                st.markdown("#### 1️⃣ 방식 1: 발송된 제품 형태 그대로 표시 (누적 총량)")
                st.dataframe(f_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False), use_container_width=True)
                
                # --- 방식 2: 성분 분해 합산 (혼합 제품을 개별 제품으로 해체) ---
                st.markdown("#### 2️⃣ 방식 2: 혼합 제품을 개별 성분으로 분해하여 전체 합산")
                
                recipes = st.session_state.recipe_db
                decomposed_stats = {}
                
                for _, row in f_df.iterrows():
                    p_name = row['제품']
                    p_qty = row['수량']
                    
                    if p_name in recipes: # 혼합 제품인 경우
                        r = recipes[p_name]
                        ratio = p_qty / r['batch_size']
                        for mat_name, mat_qty in r['materials'].items():
                            val = mat_qty * ratio
                            decomposed_stats[mat_name] = decomposed_stats.get(mat_name, 0) + val
                    else: # 개별 제품인 경우
                        decomposed_stats[p_name] = decomposed_stats.get(p_name, 0) + p_qty
                
                decomp_df = pd.DataFrame(list(decomposed_stats.items()), columns=["개별 제품 성분", "최종 소요량(합계)"])
                st.dataframe(decomp_df.sort_values("최종 소요량(합계)", ascending=False), use_container_width=True)

                # --- 개인별 누적 요약 ---
                st.markdown("#### 👤 선택 환자별 개별 배송 히스토리 요약")
                pivot = f_df.pivot_table(index="이름", columns="제품", values="수량", aggfunc="sum", fill_value=0)
                pivot["개인별 총합"] = pivot.sum(axis=1)
                st.dataframe(pivot, use_container_width=True)

            st.divider()
            st.subheader("🌐 전체 통계 (울산 제외)")
            non_ulsan = p_df[~p_df['이름'].str.contains("울산", na=False)]
            st.write(f"울산 제외 총 출고 건수: {len(non_ulsan)}건")
            st.dataframe(non_ulsan.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False))
        else:
            st.info("기록이 없습니다.")

elif app_mode == "🏭 생산/공정 관리":
    st.title("🏭 생산/공정 관리 v.1.0.1")
    t_y, t_c, t_p = st.tabs(["📊 수율", "🧀 커드", "🔬 pH/기타"])
    # (v.0.9.9의 생산 관리 로직 유지 - 이전 소스와 동일)
    with t_y:
        y_bot = st.number_input("우유 투입(통)", 1, 100, 10)
        y_act = st.number_input("실제 생산(kg)", 0.0)
        if st.button("💾 수율 저장"):
            save_yield_log([datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "커드", y_bot, y_bot*0.5, y_act, 0, ""])
            st.success("저장 완료")
    with t_c:
        m_cnt = st.number_input("우유 개수", 1, 100, 30)
        if st.button("🚀 대사 시작"):
            update_inventory("우유", -float(m_cnt))
            st.success("재고 차감 및 시작")
    with t_p:
        ph = st.number_input("pH", 0.0, 14.0, 5.0)
        if st.button("💾 pH 저장"):
            save_ph_log(["DIRECT", datetime.now(KST).strftime("%Y-%m-%d %H:%M"), ph, 30.0, ""])
            st.success("저장 완료")
