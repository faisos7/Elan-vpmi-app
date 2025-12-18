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
st.set_page_config(page_title="엘랑비탈 ERP v.1.0.7", page_icon="🏥", layout="wide")
KST = timezone(timedelta(hours=9))

YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,
    "PACK_UNIT_KG": 0.15,
    "DRINK_RATIO": 6.5
}

# ==============================================================================
# 2. 회차 계산 엔진 (에러 방지 로직 강화)
# ==============================================================================
def calculate_round_v7(start_date_input, current_date_input, group_type):
    try:
        if not start_date_input or str(start_date_input).lower() in ['nan', '', 'none']:
            return 1, "날짜미입력"
        
        # 날짜 파싱 (Excel 날짜 형식 유연하게 대응)
        start_date = pd.to_datetime(start_date_input).date()
        target_date = current_date_input.date() if isinstance(current_date_input, datetime) else current_date_input
        
        delta_days = (target_date - start_date).days
        if delta_days < 0: return 1, start_date.strftime('%Y-%m-%d')

        # 사용자 데이터 기준: 남양주(매주)=8회차 이상, 격주=3회차 이상
        if "매주" in str(group_type):
            r = (delta_days // 7) + 1
        else: # 격주/유방암 등
            r = (delta_days // 14) + 1
            
        return int(max(r, 1)), start_date.strftime('%Y-%m-%d')
    except:
        return 1, "형식확인요망"

# ==============================================================================
# 3. 구글 시트 연동 및 보안 (Gspread)
# ==============================================================================
def get_gspread_client():
    try:
        secrets = st.secrets["gcp_service_account"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        return gspread.authorize(creds)
    except: return None

def check_password():
    if 'authenticated' not in st.session_state: st.session_state.authenticated = False
    def password_entered():
        if st.session_state["password"] == "I love VPMI":
            st.session_state.authenticated = True
            del st.session_state["password"]
    if not st.session_state.authenticated:
        st.title("🔒 로그인")
        st.text_input("비밀번호:", type="password", key="password", on_change=password_entered)
        return False
    return True

if not check_password(): st.stop()

# ==============================================================================
# 4. 데이터 로드 및 인벤토리 (핵심 로직)
# ==============================================================================
@st.cache_data(ttl=60)
def load_vpmi_data():
    client = get_gspread_client()
    if not client: return {}
    try:
        sheet = client.open("vpmi_data").sheet1
        data = sheet.get_all_records()
        db = {}
        for row in data:
            name = str(row.get('이름', '')).strip()
            if not name: continue
            items = []
            for itm in str(row.get('주문내역', '')).split(','):
                if ':' in itm:
                    p, q = itm.split(':')
                    try: items.append({"제품": p.strip(), "수량": int(q.strip())})
                    except: continue # 수량이 숫자가 아니면 무시
            db[name] = {
                "group": str(row.get('그룹', '')), "note": str(row.get('비고', '')),
                "items": items, "default": True if str(row.get('기본발송', '')).upper() == 'O' else False,
                "start_date_raw": str(row.get('시작일', ''))
            }
        return db
    except: return {}

def update_inventory(item_name, change_qty):
    client = get_gspread_client()
    try:
        sheet = client.open("vpmi_data").worksheet("inventory")
        cell = sheet.find(item_name)
        if cell:
            curr = float(sheet.cell(cell.row, 2).value or 0)
            sheet.update_cell(cell.row, 2, curr + change_qty)
            return True
        return False
    except: return False

def save_history(records):
    client = get_gspread_client()
    try:
        sheet = client.open("vpmi_data").worksheet("history")
        for r in reversed(records): sheet.insert_row(r, 2)
        return True
    except: return False

# ==============================================================================
# 5. 세션 상태 및 레시피 (김성기 환자 PPE 수정 반영)
# ==============================================================================
def init_session():
    if 'patient_db' not in st.session_state: st.session_state.patient_db = load_vpmi_data()
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            "혼합 [P.P]": {"batch_size": 1, "materials": {"송이 대사체": 2, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [P.V.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 3, "표고버섯 대사체": 2, "EX": 5}},
            "혼합 [P.P.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 5, "EX": 5}}, # 뇌질환용 제거 및 항암용 통합
            "혼합 [E.R.P.V.P]": {"batch_size": 5, "materials": {"애기똥풀 대사체": 1, "장미꽃 대사체": 1, "인삼대사체(PAGI) 항암용": 1, "송이 대사체": 1, "표고버섯 대사체": 1}},
            "혼합 [Ex.P]": {"batch_size": 10, "materials": {"EX": 8, "인삼대사체(PAGI) 항암용": 2}},
            "혼합 [R.P]": {"batch_size": 4, "materials": {"장미꽃 대사체": 3, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [Edf.P]": {"batch_size": 4, "materials": {"개망초(EDF)": 3, "인삼대사체(PAGI) 항암용": 1}}
        }
    if 'schedule' not in st.session_state:
        st.session_state.schedule = {
            1: "1월: 동백꽃, 인삼사이다", 2: "2월: 갈대뿌리, 당근", 3: "3월: 봄꽃, 표고",
            4: "4월: 애기똥풀", 5: "5월: 개망초, 아카시아", 6: "6월: 매실, 개망초",
            7: "7월: 연꽃, 무궁화", 8: "8월: 풋사과", 9: "9월: 청귤, 장미꽃",
            10: "10월: 송이, 표고", 11: "11월: 무염김치, 인삼", 12: "12월: 연말 마감"
        }

init_session()

# ==============================================================================
# 6. 메인 UI (사이드바 및 모드 제어)
# ==============================================================================
st.sidebar.title("엘랑비탈 ERP v.1.0.7")
mode = st.sidebar.radio("📋 메뉴", ["🚛 배송 및 주문 관리", "🏭 생산 공정 관리", "📦 재고 대시보드"])

if mode == "🚛 배송 및 주문 관리":
    st.header("🚛 일일 배송 관리")
    target_date = st.date_input("발송일", datetime.now(KST))
    
    db = st.session_state.patient_db
    sel_p = {}
    
    t_every, t_bi = st.tabs(["🗓️ 매주 발송", "🗓️ 격주/기타"])
    
    with t_every:
        cols = st.columns(2)
        idx = 0
        for n, info in db.items():
            if "매주" in info['group']:
                r, sd = calculate_round_v7(info['start_date_raw'], target_date, "매주")
                with cols[idx % 2]:
                    if st.checkbox(f"**{n}** ({r}회차)", value=info['default'], key=f"chk_{n}"):
                        sel_p[n] = {**info, "round": r}
                idx += 1
                
    with t_bi:
        cols = st.columns(2)
        idx = 0
        for n, info in db.items():
            if "매주" not in info['group']:
                r, sd = calculate_round_v7(info['start_date_raw'], target_date, "격주")
                with cols[idx % 2]:
                    if st.checkbox(f"**{n}** ({r}회차)", value=info['default'], key=f"chk_{n}"):
                        sel_p[n] = {**info, "round": r}
                idx += 1

    st.divider()
    w1, w2, w3, w4 = st.tabs(["📦 포장 라벨", "🧪 혼합 제조", "📊 통계 분석", "📂 발송 이력"])

    with w1:
        if st.button("🚀 발송 확정 및 재고 차감", type="primary"):
            logs = []
            for n, p in sel_p.items():
                c_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in p['items']])
                logs.append([target_date.strftime('%Y-%m-%d'), n, p['group'], p['round'], c_str])
                for itm in p['items']: update_inventory(itm['제품'], -float(itm['수량']))
            if save_history(logs): st.success("데이터 저장 및 재고 반영 완료!")
        
        for n, p in sel_p.items():
            with st.expander(f"📍 {n} ({p['round']}회차)", expanded=True):
                for i in p['items']: st.write(f"- {i['제품']}: {i['수량']}개")

    with w2:
        mix_data = {}
        for p in sel_p.values():
            for i in p['items']:
                if "혼합" in i['제품']: mix_data[i['제품']] = mix_data.get(i['제품'], 0) + i['수량']
        for prd, qty in mix_data.items():
            rcp = st.session_state.recipe_db.get(prd)
            if rcp:
                st.info(f"🧪 {prd} ({qty}개 분량) 제조 필요")
                ratio = qty / rcp['batch_size']
                for m, q in rcp['materials'].items(): st.write(f"→ {m}: **{q*ratio:.2f}** 단위")

    with w3:
        st.subheader("📜 누적 데이터 분석 (방식 1 vs 방식 2)")
        client = get_gspread_client()
        h_df = pd.DataFrame(client.open("vpmi_data").worksheet("history").get_all_records())
        
        if not h_df.empty:
            targets = st.multiselect("분석 대상 선택", sorted(h_df['이름'].unique()))
            if targets:
                f_h = h_df[h_df['이름'].isin(targets)]
                parsed = []
                for _, row in f_h.iterrows():
                    for it in str(row['발송내역']).split(','):
                        if ':' in it:
                            p, q = it.split(':')
                            try: parsed.append({"이름": row['이름'], "제품": p.strip(), "수량": int(q.strip())})
                            except: continue
                p_df = pd.DataFrame(parsed)
                
                c1, c2 = st.columns(2)
                with c1:
                    st.write("#### [방식 1] 제품별 누적 합계")
                    st.dataframe(p_df.groupby("제품")["수량"].sum())
                with c2:
                    st.write("#### [방식 2] 성분별 분해 합계")
                    r_db = st.session_state.recipe_db
                    stats = {}
                    for _, r in p_df.iterrows():
                        if r['제품'] in r_db:
                            rcp = r_db[r['제품']]; ratio = r['수량'] / rcp['batch_size']
                            for mn, mq in rcp['materials'].items(): stats[mn] = stats.get(mn, 0) + (mq*ratio)
                        else: stats[r['제품']] = stats.get(r['제품'], 0) + r['수량']
                    st.dataframe(pd.DataFrame(list(stats.items()), columns=["성분", "합계"]))

    with w4:
        st.dataframe(h_df, use_container_width=True)

elif mode == "🏭 생산 공정 관리":
    st.header("🏭 생산 공정 관리")
    st.info(st.session_state.schedule.get(datetime.now(KST).month))
    ph = st.number_input("현재 대사 pH 측정", 0.0, 14.0, 4.2)
    if st.button("💾 품질 로그 저장"): st.success(f"pH {ph} 기록 완료")

else:
    st.header("📦 실시간 재고 관리")
    cl = get_gspread_client()
    inv = pd.DataFrame(cl.open("vpmi_data").worksheet("inventory").get_all_records())
    st.dataframe(inv, use_container_width=True)

st.sidebar.divider()
if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()
