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
st.set_page_config(page_title="엘랑비탈 ERP v.1.0.5", page_icon="🏥", layout="wide")
KST = timezone(timedelta(hours=9))

YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,
    "PACK_UNIT_KG": 0.15,
    "DRINK_RATIO": 6.5
}

# ==============================================================================
# 2. 회차 계산 엔진 (Excel 시작일 참조 최적화)
# ==============================================================================
def calculate_round_v5(start_date_input, current_date_input, group_type):
    try:
        if not start_date_input or str(start_date_input).lower() in ['nan', '', 'none']:
            return 1, "미기입"
        
        # 날짜 파싱
        start_date = pd.to_datetime(start_date_input).date()
        target_date = current_date_input.date() if isinstance(current_date_input, datetime) else current_date_input
        
        delta_days = (target_date - start_date).days
        if delta_days < 0: return 1, start_date.strftime('%Y-%m-%d')

        if "매주" in group_type:
            r = (delta_days // 7) + 1
        elif "격주" in group_type or "유방암" in group_type or "2주" in group_type:
            r = (delta_days // 14) + 1
        else:
            r = 1
        return int(max(r, 1)), start_date.strftime('%Y-%m-%d')
    except:
        return 1, "오류"

# ==============================================================================
# 3. 보안 및 기초 함수 (Gspread 연동)
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
            st.title("🔒 엘랑비탈 ERP v.1.0.5")
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
            for item in str(row.get('주문내역', '')).split(','):
                if ':' in item:
                    p_name, p_qty = item.split(':')
                    items_list.append({"제품": p_name.strip(), "수량": int(p_qty.strip())})
            db[name] = {
                "group": row.get('그룹', ''), "note": row.get('비고', ''),
                "default": True if str(row.get('기본발송', '')).upper() == 'O' else False,
                "items": items_list, "start_date_raw": str(row.get('시작일', ''))
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
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            "혼합 [P.P]": {"batch_size": 1, "materials": {"송이 대사체": 2, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [P.V.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 3, "표고버섯 대사체": 2, "EX": 5}},
            "혼합 [P.P.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 4, "인삼대사체(PAGI) 뇌질환용": 1, "EX": 5}},
            "혼합 [E.R.P.V.P]": {"batch_size": 5, "materials": {"애기똥풀 대사체": 1, "장미꽃 대사체": 1, "인삼대사체(PAGI) 항암용": 1, "송이 대사체": 1, "표고버섯 대사체": 1}},
            "혼합 [Ex.P]": {"batch_size": 10, "materials": {"EX": 8, "인삼대사체(PAGI) 항암용": 2}},
            "혼합 [R.P]": {"batch_size": 4, "materials": {"장미꽃 대사체": 3, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [Edf.P]": {"batch_size": 4, "materials": {"개망초(EDF)": 3, "인삼대사체(PAGI) 항암용": 1}},
            "계란커드 스타터 [혼합]": {"batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}},
            "철원산삼 대사체": {"batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}}
        }
    if 'schedule_db' not in st.session_state:
        st.session_state.schedule_db = {
            1: {"title": "1월", "main": ["동백꽃", "인삼사이다"], "note": "pH 3.8 도달 시 종료"},
            2: {"title": "2월", "main": ["갈대뿌리", "당근"], "note": "수율 37%"},
            3: {"title": "3월", "main": ["봄꽃", "표고"], "note": "1:1 비율"},
            4: {"title": "4월", "main": ["애기똥풀"], "note": "전초 사용"},
            5: {"title": "5월", "main": ["개망초+아카시아"], "note": "스타터용"},
            6: {"title": "6월", "main": ["매실", "개망초"], "note": "씨 제거"},
            7: {"title": "7월", "main": ["연꽃", "무궁화"], "note": "대사 속도 주의"},
            8: {"title": "8월", "main": ["풋사과"], "note": "1:6 비율"},
            9: {"title": "9월", "main": ["청귤", "장미꽃"], "note": "추석 준비"},
            10: {"title": "10월", "main": ["송이", "표고"], "note": "등외품 활용"},
            11: {"title": "11월", "main": ["무염김치", "인삼"], "note": "김장 시즌"},
            12: {"title": "12월", "main": ["동백꽃", "메주콩"], "note": "연말 마감"}
        }
    if 'raw_material_list' not in st.session_state:
        st.session_state.raw_material_list = ["우유", "계란", "배추", "무", "마늘", "인삼", "동백꽃", "개망초", "아카시아 꽃"]
    if 'regimen_db' not in st.session_state:
        st.session_state.regimen_db = {"울산 자궁근종": "장미꽃 및 인삼 대사체 처방 데이터"}
    if 'yearly_memos' not in st.session_state: st.session_state.yearly_memos = []

init_session_state()

# ==============================================================================
# 5. 메인 화면 구성 및 로직 (전체 복구)
# ==============================================================================
show_inventory_dashboard()
st.sidebar.title("📌 메뉴 선택")
app_mode = st.sidebar.radio("작업 모드", ["🚛 배송/주문 관리", "🏭 생산/공정 관리"])

st.title(f"🏥 엘랑비탈 ERP v.1.0.5 ({app_mode})")

if app_mode == "🚛 배송/주문 관리":
    target_date = st.date_input("발송일", datetime.now(KST))
    db = st.session_state.patient_db
    sel_p = {}
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("🚛 매주 발송 환자")
        for k, v in db.items():
            if "매주" in v['group']:
                r_num, sd_disp = calculate_round_v5(v['start_date_raw'], target_date, "매주 발송")
                if st.checkbox(f"{k} ({r_num}회차)", v['default'], key=f"c_{k}"):
                    sel_p[k] = v; sel_p[k]['round'] = r_num

    with c2:
        st.subheader("🚚 격주/기타 환자")
        for k, v in db.items():
            if "격주" in v['group'] or "유방암" in v['group']:
                r_num, sd_disp = calculate_round_v5(v['start_date_raw'], target_date, "격주 발송")
                if st.checkbox(f"{k} ({r_num}회차)", v['default'], key=f"c_{k}"):
                    sel_p[k] = v; sel_p[k]['round'] = r_num

    st.divider()
    t1, t2, t3, t4, t5 = st.tabs(["📦 라벨", "📊 제품총합", "🧪 혼합제조", "📊 커드수요", "📜 누적분석"])
    
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
                st.markdown(f"### 🧊 {n} ({info.get('round', 1)}회차)")
                for x in info['items']: st.write(f"□ {x['제품']} {x['수량']}개")

    with t2:
        st.subheader("📊 제품별 발송 합계")
        tot = {}
        for d in sel_p.values():
            for x in d['items']: tot[x['제품']] = tot.get(x['제품'], 0) + x['수량']
        st.dataframe(pd.DataFrame(list(tot.items()), columns=["제품", "수량"]), use_container_width=True)

    with t3:
        st.subheader("🧪 혼합 제조 지시")
        req = {}
        for d in sel_p.values():
            for x in d['items']:
                if "혼합" in x['제품']: req[x['제품']] = req.get(x['제품'], 0) + x['수량']
        for p, q in req.items():
            st.info(f"🧪 {p}: {q}개 제조 필요")

    with t4:
        cp = sum(x['수량'] for d in sel_p.values() for x in d['items'] if "커드" in x['제품'] and "시원" not in x['제품'])
        cc = sum(x['수량'] for d in sel_p.values() for x in d['items'] if "시원" in x['제품'])
        st.metric("계란커드", f"{cp}개"); st.metric("시원한것", f"{cc}개")

    with t5:
        st.header("📜 누적 출고 데이터 분석")
        h_df = load_sheet_data("history", "발송일")
        if not h_df.empty:
            parsed = []
            for _, row in h_df.iterrows():
                for it in str(row['발송내역']).split(','):
                    if ':' in it:
                        try:
                            pn, pq = it.split(':')
                            parsed.append({"이름": row['이름'], "그룹": row['그룹'], "제품": pn.strip(), "수량": int(pq.strip())})
                        except: continue
            p_df = pd.DataFrame(parsed)

            with st.form("stat_analysis"):
                targets = st.multiselect("분석 환자 선택", sorted(p_df['이름'].unique()))
                submitted = st.form_submit_button("✅ 분석 시작")

            if submitted and targets:
                f_df = p_df[p_df['이름'].isin(targets)]
                st.markdown("#### 1️⃣ 방식 1: 표면 누적 합계")
                st.dataframe(f_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False), use_container_width=True)
                
                st.markdown("#### 2️⃣ 방식 2: 성분 분해 합계")
                recipes = st.session_state.recipe_db
                stats = {}
                for _, row in f_df.iterrows():
                    n, q = row['제품'], row['수량']
                    if n in recipes:
                        r = recipes[n]; ratio = q / r['batch_size']
                        for mn, mq in r['materials'].items():
                            stats[mn] = stats.get(mn, 0) + (mq * ratio)
                    else: stats[n] = stats.get(n, 0) + q
                st.dataframe(pd.DataFrame(list(stats.items()), columns=["성분", "합계"]), use_container_width=True)

            st.divider()
            st.subheader("🌐 전체 통계 (울산 제외)")
            non_ulsan = p_df[~p_df['이름'].str.contains("울산", na=False)]
            st.dataframe(non_ulsan.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False), use_container_width=True)

# ==============================================================================
# 6. 생산/공정 관리 (원본 로직 전체 복구)
# ==============================================================================
elif app_mode == "🏭 생산/공정 관리":
    ty1, ty2, ty3, ty4, ty5, ty6 = st.tabs(["📊 수율", "🧀 커드생산", "🗓️ 일정", "💊 처방", "🏭 기타", "🔬 pH"])
    
    with ty1:
        st.subheader("📊 생산 수율 및 예측")
        y_bot = st.number_input("우유 투입(통)", 1, 100, 10)
        y_act = st.number_input("실제 생산(kg)", 0.0)
        if st.button("💾 저장"):
            save_yield_log([datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "커드", y_bot, y_bot*0.5, y_act, 0, ""])
            st.success("저장됨")

    with ty2:
        st.subheader("🧀 커드 생산 제어")
        m_cnt = st.number_input("우유 통수", 1, 100, 30)
        if st.button("🚀 대사 시작"):
            bid = f"B-{uuid.uuid4().hex[:4]}"
            if save_production_record("curd_prod", [bid, datetime.now(KST).strftime("%Y-%m-%d"), "커드", "우유", m_cnt*2.3, "15%", 0, 0, "", "진행중"]):
                update_inventory("우유", -float(m_cnt))
                st.success("대사 시작 및 재고 차감 완료")

    with ty3:
        st.subheader("🗓️ 연간 생산 캘린더")
        m_sel = st.selectbox("월 선택", list(range(1, 13)), datetime.now(KST).month-1)
        st.info(st.session_state.schedule_db[m_sel])

    with ty4:
        st.subheader("💊 환자별 맞춤 처방")
        st.write(st.session_state.regimen_db)

    with ty5:
        st.subheader("🏭 기타 생산 기록")
        p_nm = st.selectbox("원물 선택", st.session_state.raw_material_list)
        if st.button("💾 생산 데이터 저장"):
            save_production_record("other_prod", ["DIRECT", datetime.now(KST).strftime("%Y-%m-%d"), "기타", p_nm, 1.0, "1:8", 0, 0, "", "완료"])

    with ty6:
        st.subheader("🔬 대사/pH 관리")
        ph = st.number_input("pH 측정치", 0.0, 14.0, 5.0)
        if st.button("💾 pH 로그 저장"):
            if save_ph_log(["DIRECT", datetime.now(KST).strftime("%Y-%m-%d %H:%M"), ph, 30.0, ""]): st.success("저장 완료")
