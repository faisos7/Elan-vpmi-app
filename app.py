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
st.set_page_config(page_title="엘랑비탈 ERP v.0.9.9", page_icon="🏥", layout="wide")

# [중요] 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))

# [v.0.9.9] 수율 및 재고 관리 상수
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,  # 우유 1통(2.3L)당 예상 커드 0.5kg
    "PACK_UNIT_KG": 0.15,            # 소포장 단위 150g
    "DRINK_RATIO": 6.5              # 일반커드 -> 커드시원한것 희석 배수
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
            st.title("🔒 엘랑비탈 ERP v.0.9.9")
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
    """inventory 시트의 재고를 가감합니다."""
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
    except:
        return False

def show_inventory_dashboard():
    """상단 대시보드 알림"""
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("inventory")
        df_inv = pd.DataFrame(sheet.get_all_records())
        if not df_inv.empty:
            low_stock = df_inv[df_inv['현재고'].astype(float) <= 10]
            if not low_stock.empty:
                for _, row in low_stock.iterrows():
                    st.error(f"🚨 **재고 부족**: {row['항목명']} ({row['현재고']} {row['단위']} 남음)")
            with st.expander("📦 실시간 재고 현황판"):
                st.dataframe(df_inv, use_container_width=True)
    except:
        st.info("💡 'inventory' 시트를 생성하면 재고 대시보드가 활성화됩니다.")

@st.cache_data(ttl=60) 
def load_data_from_sheet():
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").sheet1
        data = sheet.get_all_records()
        default_caps = {
            "시원한 것": "280ml", "마시는 것": "280ml", "커드 시원한 것": "280ml",
            "인삼 사이다": "300ml", "EX": "280ml",
            "인삼대사체(PAGI)": "50ml", "인삼대사체(PAGI) 항암용": "50ml", "인삼대사체(PAGI) 뇌질환용": "50ml",
            "개망초(EDF)": "50ml", "장미꽃 대사체": "50ml", "애기똥풀 대사체": "50ml",
            "송이 대사체": "50ml", "표고버섯 대사체": "50ml", "철원산삼 대사체": "50ml",
            "계란 커드": "150g" 
        }
        db = {}
        for row in data:
            name = row.get('이름')
            if not name: continue
            items_list = []
            raw_items = str(row.get('주문내역', '')).split(',')
            for item in raw_items:
                if ':' in item:
                    p_name, p_qty = item.split(':')
                    clean_name = p_name.strip()
                    if clean_name == "PAGI 희석액": clean_name = "인삼대사체(PAGI) 항암용"
                    if clean_name == "커드": clean_name = "계란 커드"
                    cap = default_caps.get(clean_name, "")
                    items_list.append({"제품": clean_name, "수량": int(p_qty.strip()), "용량": cap})
            round_val = row.get('회차')
            try: round_num = int(str(round_val).replace('회', '').replace('주', '').strip())
            except: round_num = 1
            db[name] = {
                "group": row.get('그룹', ''), "note": row.get('비고', ''),
                "default": True if str(row.get('기본발송', '')).upper() == 'O' else False,
                "items": items_list, "round": round_num, "start_date_raw": str(row.get('시작일', ''))
            }
        return db
    except: return {}

def save_to_history(record_list):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("history")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="history", rows="1000", cols="10")
            sheet.append_row(["발송일", "이름", "그룹", "회차", "발송내역"])
        for record in reversed(record_list): sheet.insert_row(record, 2)
        return True
    except: return False

def save_production_record(sheet_name, record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet(sheet_name)
        except:
            sheet = client.open("vpmi_data").add_worksheet(title=sheet_name, rows="1000", cols="10")
            sheet.append_row(["배치ID", "생산일", "종류", "원재료", "투입량(kg)", "비율", "완성(개)", "폐기(병)", "비고", "상태"])
        sheet.insert_row(record, 2)
        return True
    except: return False

def save_yield_log(record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("yield_logs")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="yield_logs", rows="1000", cols="10")
            sheet.append_row(["기록일시", "생산모드", "투입(통)", "예상(kg)", "실제(kg)", "손실률(%)", "비고"])
        sheet.insert_row(record, 2)
        return True
    except: return False

def save_ph_log(record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("ph_logs")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="ph_logs", rows="1000", cols="10")
            sheet.append_row(["배치ID", "측정일시", "pH", "온도", "비고"])
        sheet.insert_row(record, 2)
        return True
    except: return False

def update_production_status(sheet_name, batch_id, new_status, add_done=0, add_fail=0):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        cell = sheet.find(batch_id)
        if cell:
            sheet.update_cell(cell.row, 10, new_status)
            if add_done > 0:
                curr = sheet.cell(cell.row, 7).value
                sheet.update_cell(cell.row, 7, (int(curr) if curr else 0) + add_done)
            if add_fail > 0:
                curr = sheet.cell(cell.row, 8).value
                sheet.update_cell(cell.row, 8, (int(curr) if curr else 0) + add_fail)
            return True
        return False
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
# 4. 세션 상태 초기화 (init_session_state)
# ==============================================================================
def init_session_state():
    if 'target_date' not in st.session_state: st.session_state.target_date = datetime.now(KST)
    if 'view_month' not in st.session_state: st.session_state.view_month = st.session_state.target_date.month
    if 'patient_db' not in st.session_state: st.session_state.patient_db = load_data_from_sheet()
    if 'schedule_db' not in st.session_state:
        st.session_state.schedule_db = {
            1: {"title": "1월", "main": ["동백꽃", "인삼사이다", "유기농 우유 커드"], "note": "pH 3.8 종료"},
            2: {"title": "2월", "main": ["갈대뿌리", "당근"], "note": "수율 37%"},
            3: {"title": "3월", "main": ["봄꽃", "표고"], "note": "1:1 비율"},
            4: {"title": "4월", "main": ["애기똥풀", "등나무꽃"], "note": "전초"},
            5: {"title": "5월", "main": ["개망초+아카시아", "뽕잎"], "note": "스타터용"},
            6: {"title": "6월", "main": ["매실", "개망초"], "note": "씨 제거"},
            7: {"title": "7월", "main": ["연꽃", "무궁화"], "note": "대사 속도 주의"},
            8: {"title": "8월", "main": ["풋사과"], "note": "1:6"},
            9: {"title": "9월", "main": ["청귤", "장미"], "note": "추석 준비"},
            10: {"title": "10월", "main": ["송이", "표고"], "note": "등외품"},
            11: {"title": "11월", "main": ["무염김치", "인삼"], "note": "김장"},
            12: {"title": "12월", "main": ["동백꽃", "메주콩"], "note": "마감"}
        }
    if 'yearly_memos' not in st.session_state: st.session_state.yearly_memos = []
    if 'raw_material_list' not in st.session_state:
        st.session_state.raw_material_list = ["우유", "계란", "배추", "무", "마늘", "인삼", "동백꽃", "개망초", "아카시아"]
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            "계란커드 스타터 [혼합]": {"batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}},
            "철원산삼 대사체": {"batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}},
            "혼합 [P.V.E]": {"batch_size": 10, "materials": {"인삼대사체 항암": 3, "표고 대사체": 2, "EX": 5}}
        }
    if 'regimen_db' not in st.session_state:
        st.session_state.regimen_db = {"울산 자궁근종": "1. 아침 장미꽃, 2. 밤 인삼 대사체"}

# ==============================================================================
# 5. 메인 로직 실행
# ==============================================================================
init_session_state()
show_inventory_dashboard()

def calculate_round_v4(start_date_input, current_date_input, group_type):
    try:
        sd = pd.to_datetime(start_date_input).date()
        delta = (current_date_input.date() - sd).days
        weeks = round(delta / 7)
        r = (weeks + 1 if group_type == "매주 발송" else (weeks // 2) + 1)
        return max(r, 1), sd.strftime('%Y-%m-%d')
    except: return 1, "날짜없음"

kr_holidays = holidays.KR()
def check_delivery_date(date_obj):
    if date_obj.weekday() == 4: return False, "⛔ 금요일 발송 금지"
    if date_obj.weekday() >= 5: return False, "⛔ 주말 불가"
    if date_obj in kr_holidays: return False, f"⛔ 휴일({kr_holidays.get(date_obj)})"
    return True, "✅ 발송 가능"

st.sidebar.title("📌 메뉴")
app_mode = st.sidebar.radio("모드", ["🚛 배송/주문 관리", "🏭 생산/공정 관리"])

# --- [MODE 1] 배송 관리 ---
if app_mode == "🚛 배송/주문 관리":
    st.title("🚛 배송/주문 관리 v.0.9.9")
    target_date = st.date_input("발송일", datetime.now(KST))
    is_ok, msg = check_delivery_date(target_date)
    if is_ok: st.success(msg)
    else: st.error(msg)
    
    db = st.session_state.patient_db
    sel_p = {}
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("매주 발송")
        for k, v in db.items():
            if v['group'] == "매주 발송":
                r, sd = calculate_round_v4(v['start_date_raw'], target_date, "매주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default']): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}
    with c2:
        st.subheader("격주/기타")
        for k, v in db.items():
            if v['group'] != "매주 발송":
                r, sd = calculate_round_v4(v['start_date_raw'], target_date, "격주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default']): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}
    
    st.divider()
    t1, t2, t3, t4, t5 = st.tabs(["📦 라벨/포장", "📊 총합", "🧪 혼합", "📊 커드수요", "📂 이력"])
    
    with t1:
        if st.button("📝 발송 저장 및 재고 차감"):
            records = []
            for name, data in sel_p.items():
                content = ", ".join([f"{i['제품']}:{i['수량']}" for i in data['items']])
                records.append([target_date.strftime('%Y-%m-%d'), name, data['group'], data['round'], content])
                for itm in data['items']: update_inventory(itm['제품'], -float(itm['수량']))
            if save_to_history(records): st.success("완료!")
        for n, d in sel_p.items():
            with st.container(border=True):
                st.markdown(f"### 🧊 {n} ({d['round']}회)")
                for x in d['items']: st.write(f"- {x['제품']} {x['수량']}개")

    with t2:
        st.header("제품별 총합")
        tot = {}
        for d in sel_p.values():
            for x in d['items']:
                k = x['제품']
                tot[k] = tot.get(k, 0) + x['수량']
        st.dataframe(pd.DataFrame(list(tot.items()), columns=["제품", "수량"]))

    with t3:
        st.header("혼합 제조")
        req = {}
        for d in sel_p.values():
            for x in d['items']:
                if "혼합" in x['제품']: req[x['제품']] = req.get(x['제품'], 0) + x['수량']
        for p, q in req.items():
            with st.expander(f"{p} ({q}개)"):
                st.write(f"레시피 계산 결과: {q}개분 원료 필요")

    with t4:
        st.header("커드 수요량")
        cp = sum(x['수량'] for d in sel_p.values() for x in d['items'] if "커드" in x['제품'] and "시원" not in x['제품'])
        cc = sum(x['수량'] for d in sel_p.values() for x in d['items'] if "시원" in x['제품'])
        st.metric("계란커드", f"{cp}개")
        st.metric("시원한것", f"{cc}개")

    with t5:
        st.header("발송 이력")
        st.dataframe(load_sheet_data("history", "발송일"))

# --- [MODE 2] 생산 관리 ---
elif app_mode == "🏭 생산/공정 관리":
    st.title("🏭 생산/공정 관리 v.0.9.9")
    t_y, t_c, t_s, t_r, t_o, t_p = st.tabs(["📊 수율", "🧀 커드", "🗓️ 일정", "💊 처방", "🏭 기타", "🔬 pH"])
    
    with t_y:
        st.header("생산 예측")
        y_bot = st.number_input("우유(통)", 1, 100, 10)
        st.info(f"예상 커드: {y_bot * 0.5} kg")
        y_act = st.number_input("실제(kg)", 0.0)
        if y_act > 0 and st.button("💾 수율 저장"):
            loss = (y_bot*0.5 - y_act)/(y_bot*0.5)*100
            save_yield_log([datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "커드", y_bot, y_bot*0.5, y_act, round(loss,2), ""])
            st.success(f"손실률 {loss:.1f}% 저장됨")

    with t_c:
        st.header("커드 생산 시작")
        m_cnt = st.number_input("우유 개수", 1, 100, 30)
        t_prod = st.radio("종류", ["계란 커드", "일반 커드"])
        if st.button("🚀 대사 시작 (재고 차감)"):
            bid = f"{datetime.now(KST).strftime('%y%m%d')}-{t_prod[:2]}-{uuid.uuid4().hex[:4]}"
            rec = [bid, datetime.now(KST).strftime("%Y-%m-%d"), t_prod, "우유", m_cnt*2.3, "15%", 0, 0, "", "진행중"]
            if save_production_record("curd_prod", rec):
                update_inventory("우유", -float(m_cnt))
                if "계란" in t_prod: update_inventory("계란", -float(m_cnt*2.3/4))
                st.success("대사 시작 및 재고 차감 완료!")

    with t_s:
        st.header("연간 일정")
        m = st.selectbox("월", list(range(1,13)), datetime.now(KST).month-1)
        st.write(st.session_state.schedule_db[m])

    with t_r:
        st.header("맞춤 처방")
        st.write(st.session_state.regimen_db)

    with t_o:
        st.header("기타 생산")
        p_nm = st.selectbox("원재료", st.session_state.raw_material_list)
        p_wg = st.number_input("무게(kg)", 1.0)
        if st.button("💾 기타 생산 저장"):
            save_production_record("other_prod", ["DIRECT", datetime.now(KST).strftime("%Y-%m-%d"), "기타", p_nm, p_wg, "1:8", 0,0,"","진행중"])

    with t_p:
        st.header("pH 측정 관리")
        ph = st.number_input("pH", 0.0, 14.0, 5.0)
        temp = st.number_input("온도", 0.0, 50.0, 30.0)
        if st.button("💾 pH 저장"):
            save_ph_log(["DIRECT", datetime.now(KST).strftime("%Y-%m-%d %H:%M"), ph, temp, ""])
            st.success("저장 완료")
