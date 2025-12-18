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
st.set_page_config(page_title="엘랑비탈 ERP v.1.0.3", page_icon="🏥", layout="wide")

# [중요] 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))

# [v.0.9.8] 수율 관리 상수 정의
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,  # 우유 1통(2.3L)당 예상 커드 0.5kg
    "PACK_UNIT_KG": 0.15,            # 소포장 단위 150g
    "DRINK_RATIO": 6.5              # 일반커드 -> 커드시원한것 희석 배수
}

# 2. 보안 설정
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
            st.title("🔒 엘랑비탈 ERP v.1.0.3")
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
            current_val = float(sheet.cell(cell.row, 2).value or 0)
            sheet.update_cell(cell.row, 2, current_val + change_qty)
            sheet.update_cell(cell.row, 4, datetime.now(KST).strftime("%Y-%m-%d %H:%M"))
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
                val = sheet.cell(cell.row, 7).value
                sheet.update_cell(cell.row, 7, (int(val) if val else 0) + add_done)
            if add_fail > 0:
                val = sheet.cell(cell.row, 8).value
                sheet.update_cell(cell.row, 8, (int(val) if val else 0) + add_fail)
            return True
        return False
    except: return False

@st.cache_data(ttl=60)
def load_sheet_data(sheet_name, sort_col=None):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and sort_col and sort_col in df.columns:
            df = df.sort_values(by=sort_col, ascending=False)
        return df
    except: return pd.DataFrame()

# ==============================================================================
# 4. 데이터 초기화 및 세션 상태 (모든 레시피 및 리스트 포함)
# ==============================================================================
def init_session_state():
    if 'target_date' not in st.session_state: st.session_state.target_date = datetime.now(KST)
    if 'patient_db' not in st.session_state: st.session_state.patient_db = load_data_from_sheet()
    if 'schedule_db' not in st.session_state:
        st.session_state.schedule_db = {
            1: {"title": "1월", "main": ["동백꽃", "인삼사이다", "유기농 우유 커드"], "note": "pH 3.8 도달 시 종료"},
            2: {"title": "2월", "main": ["갈대뿌리", "당근"], "note": "수율 약 37%"},
            3: {"title": "3월", "main": ["봄꽃 대사", "표고버섯"], "note": "꽃:줄기 1:1"},
            4: {"title": "4월", "main": ["애기똥풀", "등나무꽃"], "note": "애기똥풀 전초"},
            5: {"title": "5월", "main": ["개망초+아카시아 합제", "뽕잎"], "note": "스타터용"},
            6: {"title": "6월", "main": ["매실", "개망초"], "note": "매실 씨 제거"},
            7: {"title": "7월", "main": ["토종홉 꽃", "연꽃", "무궁화"], "note": "여름철 대사 주의"},
            8: {"title": "8월", "main": ["풋사과"], "note": "1:6 비율"},
            9: {"title": "9월", "main": ["청귤", "장미꽃"], "note": "추석 준비"},
            10: {"title": "10월", "main": ["송이버섯", "표고버섯", "산자나무"], "note": "송이 등외품"},
            11: {"title": "11월", "main": ["무염김치", "생지황", "인삼"], "note": "김장"},
            12: {"title": "12월", "main": ["동백꽃", "메주콩"], "note": "마감"}
        }
    if 'yearly_memos' not in st.session_state: st.session_state.yearly_memos = []
    if 'raw_material_list' not in st.session_state:
        st.session_state.raw_material_list = ["우유", "계란", "배추", "무", "마늘", "대파", "양파", "생강", "배", "고춧가루", "찹쌀가루", "새우젓", "멸치액젓", "올리고당", "조성액", "EX", "정제수", "인삼", "동백꽃", "표고버섯", "개망초", "아카시아 꽃"]
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            "혼합 [P.V.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 3, "표고버섯 대사체": 2, "EX": 5}},
            "혼합 [P.P.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 4, "인삼대사체(PAGI) 뇌질환용": 1, "EX": 5}},
            "혼합 [E.R.P.V.P]": {"batch_size": 5, "materials": {"애기똥풀 대사체": 1, "장미꽃 대사체": 1, "인삼대사체(PAGI) 항암용": 1, "송이 대사체": 1, "표고버섯 대사체": 1}},
            "혼합 [Ex.P]": {"batch_size": 10, "materials": {"EX": 8, "인삼대사체(PAGI) 항암용": 2}},
            "혼합 [R.P]": {"batch_size": 4, "materials": {"장미꽃 대사체": 3, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [Edf.P]": {"batch_size": 4, "materials": {"개망초(EDF)": 3, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [P.P]": {"batch_size": 1, "materials": {"송이 대사체": 2, "인삼대사체(PAGI) 항암용": 1}},
            "계란커드 스타터 [혼합]": {"batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}},
            "철원산삼 대사체": {"batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}}
        }
    if 'regimen_db' not in st.session_state:
        st.session_state.regimen_db = {"울산 자궁근종": """1. 아침: 장미꽃 대사체\n2. 취침 전: 인삼 대사체\n3. 식사 대용: 시원한 것 1병"""}

init_session_state()

# ==============================================================================
# 5. 보조 함수
# ==============================================================================
def calculate_round_v4(start_date_input, current_date_input, group_type):
    try:
        if not start_date_input or str(start_date_input) == 'nan': return 0, "날짜없음"
        sd = pd.to_datetime(start_date_input).date()
        delta = (current_date_input.date() - sd).days
        r = round(delta / 7) + 1 if group_type == "매주 발송" else (delta // 14) + 1
        return r, sd.strftime('%Y-%m-%d')
    except: return 1, "오류"

kr_holidays = holidays.KR()
def check_delivery_date(date_obj):
    if date_obj.weekday() == 4: return False, "⛔ 금요일 발송 불가"
    if date_obj.weekday() >= 5: return False, "⛔ 주말 발송 불가"
    if date_obj in kr_holidays: return False, f"⛔ 휴일({kr_holidays.get(date_obj)})"
    return True, "✅ 발송 가능"

# ==============================================================================
# 6. 메인 화면 및 탭 로직 (풀 버전)
# ==============================================================================
show_inventory_dashboard()
st.sidebar.title("📌 메뉴")
app_mode = st.sidebar.radio("모드", ["🚛 배송/주문 관리", "🏭 생산/공정 관리"])

if app_mode == "🚛 배송/주문 관리":
    st.title("🚛 배송/주문 관리 v.1.0.3")
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
                r, _ = calculate_round_v4(v['start_date_raw'], target_date, "매주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default'], key=f"c_{k}"): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}
    with c2:
        st.subheader("격주/기타")
        for k, v in db.items():
            if v['group'] != "매주 발송":
                r, _ = calculate_round_v4(v['start_date_raw'], target_date, "격주 발송")
                if st.checkbox(f"{k} ({r}회)", v['default'], key=f"c_{k}"): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r}

    st.divider()
    t1, t2, t3, t4, t5 = st.tabs(["📦 라벨/포장", "📊 제품총합", "🧪 혼합제조", "📊 커드수요", "📂 히스토리/정산"])
    
    with t1:
        if st.button("📝 발송 저장 및 재고 차감"):
            records = []
            for n, d in sel_p.items():
                c_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in d['items']])
                records.append([target_date.strftime('%Y-%m-%d'), n, d['group'], d['round'], c_str])
                for it in d['items']: update_inventory(it['제품'], -float(it['수량']))
            if save_to_history(records): st.success("저장 완료!")
        for n, info in sel_p.items():
            with st.container(border=True):
                st.markdown(f"### 🧊 {n} ({info['round']}회)")
                for x in info['items']: st.write(f"□ {x['제품']} {x['수량']}개")

    with t2:
        tot = {}
        for d in sel_p.values():
            for x in d['items']: tot[x['제품']] = tot.get(x['제품'], 0) + x['수량']
        st.dataframe(pd.DataFrame(list(tot.items()), columns=["제품", "수량"]), use_container_width=True)

    with t3:
        req = {}
        for d in sel_p.values():
            for x in d['items']:
                if "혼합" in x['제품']: req[x['제품']] = req.get(x['제품'], 0) + x['수량']
        for p, q in req.items():
            with st.expander(f"{p} ({q}개)"):
                st.write(f"레시피 기준 소요 원료 계산...")

    with t4:
        cp = sum(x['수량'] for d in sel_p.values() for x in d['items'] if "커드" in x['제품'] and "시원" not in x['제품'])
        cc = sum(x['수량'] for d in sel_p.values() for x in d['items'] if "시원" in x['제품'])
        st.metric("계란커드", f"{cp}개"); st.metric("시원한것", f"{cc}개")

    with t5:
        st.header("📜 누적 출고 데이터 분석")
        h_df = load_sheet_data("history", "발송일")
        if not h_df.empty:
            parsed_raw = []
            for _, row in h_df.iterrows():
                for it in str(row['발송내역']).split(','):
                    if ':' in it:
                        try:
                            pn, pq = it.split(':')
                            parsed_raw.append({"이름": row['이름'], "제품": pn.strip(), "수량": int(pq.strip())})
                        except: continue
            p_df = pd.DataFrame(parsed_raw)

            with st.form("stat_form"):
                targets = st.multiselect("분석 환자 선택", sorted(p_df['이름'].unique()))
                sub = st.form_submit_button("✅ 분석 시작")

            if sub and targets:
                f_df = p_df[p_df['이름'].isin(targets)]
                st.write("#### 1️⃣ 방식 1: 패키징 그대로 합계")
                st.dataframe(f_df.groupby("제품")["수량"].sum().reset_index())
                
                st.write("#### 2️⃣ 방식 2: 개별 성분 분해 합계")
                recipes = st.session_state.recipe_db
                stats = {}
                for _, row in f_df.iterrows():
                    n, q = row['제품'], row['수량']
                    if n in recipes:
                        r = recipes[n]
                        ratio = q / r['batch_size']
                        for mn, mq in r['materials'].items():
                            stats[mn] = stats.get(mn, 0) + (mq * ratio)
                    else: stats[n] = stats.get(n, 0) + q
                st.dataframe(pd.DataFrame(list(stats.items()), columns=["성분", "합계"]))

            st.divider()
            st.subheader("🌐 전체 통계 (울산 제외)")
            non_ulsan = p_df[~p_df['이름'].str.contains("울산", na=False)]
            st.dataframe(non_ulsan.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False))

elif app_mode == "🏭 생산/공정 관리":
    st.title("🏭 생산/공정 관리 v.1.0.3")
    t_y, t_c, t_s, t_r, t_o, t_p = st.tabs(["📊 수율", "🧀 커드", "🗓️ 일정", "💊 처방", "🏭 기타", "🔬 pH"])
    
    with t_y:
        y_bot = st.number_input("우유(통)", 1, 100, 10)
        y_act = st.number_input("실제(kg)", 0.0)
        if st.button("💾 저장"):
            save_yield_log([datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "커드", y_bot, y_bot*0.5, y_act, 0, ""])

    with t_c:
        m_cnt = st.number_input("우유 개수", 1, 100, 30)
        if st.button("🚀 대사 시작"):
            update_inventory("우유", -float(m_cnt))
            st.success("시작")

    with t_s:
        m_sel = st.selectbox("월", list(range(1,13)), datetime.now(KST).month-1)
        st.write(st.session_state.schedule_db[m_sel])

    with t_r:
        st.write(st.session_state.regimen_db)

    with t_o:
        p_nm = st.selectbox("원물", st.session_state.raw_material_list)
        if st.button("💾 기타 저장"):
            save_production_record("other_prod", ["DIRECT", datetime.now(KST).strftime("%Y-%m-%d"), "기타", p_nm, 1.0, "1:8", 0, 0, "", "완료"])

    with t_p:
        ph = st.number_input("pH", 0.0, 14.0, 5.0)
        if st.button("💾 pH 저장"):
            save_ph_log(["DIRECT", datetime.now(KST).strftime("%Y-%m-%d %H:%M"), ph, 30.0, ""])
