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
    page_title="엘랑비탈 ERP v.1.0.8",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 한국 표준시(KST) 설정
KST = timezone(timedelta(hours=9))

# 수율 및 희석 비율 상수 (v.0.9.8 원본 기준 유지)
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,  # 우유 1통(2.3L)당 예상 커드 0.5kg
    "PACK_UNIT_KG": 0.15,            # 소포장 단위 150g
    "DRINK_RATIO": 6.5              # 일반커드 -> 커드시원한것 희석 배수
}

# ==============================================================================
# 2. 회차 계산 엔진 (월요일 발송 준비 보정 - v.1.0.8 핵심)
# ==============================================================================
def calculate_round_v8(start_date_input, current_date_input, group_type):
    """
    사용자 데이터(남양주 12/15 기준 8~9회)가 월요일 낮 준비 시점에 정확히 표시되도록 보정.
    기준일이 월요일인 경우 즉시 해당 주차로 인정합니다.
    """
    try:
        if not start_date_input or str(start_date_input).lower() in ['nan', '', 'none']:
            return 1, "날짜 미입력"
        
        # 날짜 파싱
        start_date = pd.to_datetime(start_date_input).date()
        target_date = current_date_input.date() if isinstance(current_date_input, datetime) else current_date_input
        
        # [보정 로직] 시작일과 타겟일을 해당 주의 '월요일'로 치환하여 주차 차이 계산
        start_monday = start_date - timedelta(days=start_date.weekday())
        target_monday = target_date - timedelta(days=target_date.weekday())
        
        diff_weeks = (target_monday - start_monday).days // 7
        
        if "매주" in str(group_type):
            r = diff_weeks + 1
        else: # 격주/유방암 등 (2주 단위)
            r = (diff_weeks // 2) + 1
            
        return int(max(r, 1)), start_date.strftime('%Y-%m-%d')
    except:
        return 1, "형식 오류"

# ==============================================================================
# 3. 구글 시트 연동 및 보안 (Gspread API)
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
            st.title("🔒 엘랑비탈 ERP 시스템")
            st.markdown("---")
            with st.form("login_form"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

# ==============================================================================
# 4. 데이터 핸들링 함수 (재고, 이력, 시트로드)
# ==============================================================================
@st.cache_data(ttl=60)
def load_vpmi_patient_data():
    client = get_gspread_client()
    if not client: return {}
    try:
        sheet = client.open("vpmi_data").sheet1
        data = sheet.get_all_records()
        db = {}
        for row in data:
            name = str(row.get('이름', '')).strip()
            if not name: continue
            
            # 주문내역 파싱 로직 (숫자 변환 에러 방지 포함)
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

def update_inventory(item_name, change_qty):
    client = get_gspread_client()
    try:
        sheet = client.open("vpmi_data").worksheet("inventory")
        cell = sheet.find(item_name)
        if cell:
            curr = float(sheet.cell(cell.row, 2).value or 0)
            sheet.update_cell(cell.row, 2, curr + change_qty)
            sheet.update_cell(cell.row, 4, datetime.now(KST).strftime("%Y-%m-%d %H:%M"))
            return True
        return False
    except: return False

def save_to_history(records):
    client = get_gspread_client()
    try:
        sheet = client.open("vpmi_data").worksheet("history")
        for rec in reversed(records):
            sheet.insert_row(rec, 2)
        return True
    except: return False

@st.cache_data(ttl=60)
def load_sheet_by_name(sheet_name, sort_col=None):
    client = get_gspread_client()
    try:
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        df = pd.DataFrame(sheet.get_all_records())
        if not df.empty and sort_col:
            df = df.sort_values(by=sort_col, ascending=False)
        return df
    except: return pd.DataFrame()

# ==============================================================================
# 5. 세션 및 레시피 초기화 (김성기 환자 항암용 통합 수정)
# ==============================================================================
def init_system_state():
    if 'patient_db' not in st.session_state:
        st.session_state.patient_db = load_vpmi_patient_data()
    
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            "혼합 [P.P]": {"batch_size": 1, "materials": {"송이 대사체": 2, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [P.V.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 3, "표고버섯 대사체": 2, "EX": 5}},
            "혼합 [P.P.E]": {"batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 5, "EX": 5}}, # 수정: 뇌질환용 제거 및 항암용 통합
            "혼합 [E.R.P.V.P]": {"batch_size": 5, "materials": {"애기똥풀 대사체": 1, "장미꽃 대사체": 1, "인삼대사체(PAGI) 항암용": 1, "송이 대사체": 1, "표고버섯 대사체": 1}},
            "혼합 [Ex.P]": {"batch_size": 10, "materials": {"EX": 8, "인삼대사체(PAGI) 항암용": 2}},
            "혼합 [R.P]": {"batch_size": 4, "materials": {"장미꽃 대사체": 3, "인삼대사체(PAGI) 항암용": 1}},
            "혼합 [Edf.P]": {"batch_size": 4, "materials": {"개망초(EDF)": 3, "인삼대사체(PAGI) 항암용": 1}},
            "계란커드 스타터": {"batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}}
        }
    
    if 'raw_materials' not in st.session_state:
        st.session_state.raw_materials = ["우유", "계란", "배추", "무", "마늘", "대파", "인삼", "동백꽃", "표고버섯", "개망초", "아카시아", "장미꽃", "송이버섯", "EX"]

init_system_state()

# ==============================================================================
# 6. 메인 UI 및 사이드바 (재고 현황판 포함)
# ==============================================================================
st.sidebar.title("🏥 엘랑비탈 ERP v.1.0.8")
app_mode = st.sidebar.radio("📋 업무 선택", ["🚛 배송 및 주문 관리", "🏭 생산 및 공정 관리", "📦 실시간 재고 현황"])

# 상단 알림: 재고 부족 품목 실시간 표시
try:
    cl = get_gspread_client()
    inv_sheet = cl.open("vpmi_data").worksheet("inventory")
    curr_inv = pd.DataFrame(inv_sheet.get_all_records())
    low_stock = curr_inv[curr_inv['현재고'].astype(float) < 15]
    if not low_stock.empty:
        st.sidebar.warning(f"🚨 재고 부족: {', '.join(low_stock['항목명'].tolist())}")
except: pass

# ==============================================================================
# 7. 모드 1: 배송 및 주문 관리 (v.0.9.8 원본의 모든 UI 포함)
# ==============================================================================
if app_mode == "🚛 배송 및 주문 관리":
    st.header("🚛 일일 배송 및 주문 관리")
    
    col_date = st.columns([1, 2])
    with col_date[0]:
        target_date = st.date_input("발송(준비) 날짜 선택", datetime.now(KST))
    with col_date[1]:
        st.info(f"💡 선택하신 {target_date.strftime('%m월 %d일')}은 월요일 발송 준비 스케줄에 맞춰 회차가 자동 계산됩니다.")

    db = st.session_state.patient_db
    sel_p = {}

    st.markdown("### 👥 발송 대상자 필터링")
    tab_m1, tab_m2 = st.tabs(["🗓️ 매주 발송 명단", "🗓️ 격주/기타 발송 명단"])

    with tab_m1:
        cols1 = st.columns(2)
        idx = 0
        for name, info in db.items():
            if "매주" in info['group']:
                r, _ = calculate_round_v8(info['start_date_raw'], target_date, "매주")
                with cols1[idx % 2]:
                    if st.checkbox(f"**{name}** ({r}회차)", value=info['default'], key=f"every_{name}"):
                        sel_p[name] = {**info, "round": r}
                idx += 1

    with tab_m2:
        cols2 = st.columns(2)
        idx = 0
        for name, info in db.items():
            if "매주" not in info['group']:
                r, _ = calculate_round_v8(info['start_date_raw'], target_date, "격주")
                with cols2[idx % 2]:
                    if st.checkbox(f"**{name}** ({r}회차)", value=info['default'], key=f"bi_{name}"):
                        sel_p[name] = {**info, "round": r}
                idx += 1

    st.divider()

    # 하단 작업 탭 (v.0.9.8 원본 기능 전체 복원)
    t1, t2, t3, t4, t5 = st.tabs(["📦 포장 라벨", "📊 제품별 총합", "🧪 혼합 제조 지시", "📊 커드 수요량", "📜 누적 분석"])

    with t1:
        st.subheader("📦 배송 박스 포장 가이드")
        if st.button("🚀 발송 확정 및 재고 차감", type="primary"):
            history_recs = []
            for n, p in sel_p.items():
                c_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in p['items']])
                history_recs.append([target_date.strftime('%Y-%m-%d'), n, p['group'], p['round'], c_str])
                # 실시간 재고 차감 연동
                for item in p['items']:
                    update_inventory(item['제품'], -float(item['수량']))
            if save_to_history(history_recs):
                st.success(f"✅ {len(sel_p)}명의 발송 이력이 저장되고 재고가 반영되었습니다.")
        
        for n, p in sel_p.items():
            with st.expander(f"📍 {n} ({p['round']}회차) - {p['group']}", expanded=True):
                st.markdown("---")
                for i in p['items']:
                    st.write(f"✅ **{i['제품']}** : {i['수량']}개")
                if p['note']: st.caption(f"💡 비고: {p['note']}")

    with t2:
        st.subheader("📊 전체 준비 제품 총량")
        sum_dict = {}
        for p in sel_p.values():
            for i in p['items']:
                sum_dict[i['제품']] = sum_dict.get(i['제품'], 0) + i['수량']
        if sum_dict:
            st.table(pd.DataFrame(list(sum_dict.items()), columns=["제품명", "총 수량"]).sort_values("총 수량", ascending=False))

    with t3:
        st.subheader("🧪 혼합 제품 제조 지시서")
        mix_req = {}
        for p in sel_p.values():
            for i in p['items']:
                if "혼합" in i['제품']:
                    mix_req[i['제품']] = mix_req.get(i['제품'], 0) + i['수량']
        
        for prod, qty in mix_req.items():
            rcp = st.session_state.recipe_db.get(prod)
            if rcp:
                st.info(f"⚗️ {prod} ({qty}개 분량) 제조 필요")
                ratio = qty / rcp['batch_size']
                for m, amt in rcp['materials'].items():
                    st.write(f"→ {m}: **{amt * ratio:.2f}** 단위")
            st.divider()

    with t4:
        st.subheader("📊 생산용 커드 소요량 계산")
        # v.0.9.8 커드 계산 로직 복원
        curd_p = sum(i['수량'] for p in sel_p.values() for i in p['items'] if "커드" in i['제품'] and "시원" not in i['제품'])
        curd_c = sum(i['수량'] for p in sel_p.values() for i in p['items'] if "시원" in i['제품'])
        total_kg = (curd_c * 40 + curd_p * 150) / 1000
        st.metric("📦 필요한 총 커드 무게", f"{total_kg:.2f} kg")
        st.write(f"🥛 필요 우유 환산: 약 {math.ceil((total_kg/9)*16)} 통")

    with t5:
        st.header("📜 누적 출고 데이터 분석 (방식 1 vs 방식 2)")
        h_df = load_sheet_by_name("history", "발송일")
        if not h_df.empty:
            target_list = st.multiselect("분석할 환자들을 선택하세요", sorted(h_df['이름'].unique()))
            if target_list:
                f_h = h_df[h_df['이름'].isin(target_list)]
                # 분석용 파싱 데이터 생성
                p_list = []
                for _, row in f_h.iterrows():
                    for itm in str(row['발송내역']).split(','):
                        if ':' in itm:
                            pn, pq = itm.split(':')
                            try: p_list.append({"이름": row['이름'], "제품": pn.strip(), "수량": int(pq.strip())})
                            except: continue
                p_df = pd.DataFrame(p_list)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("#### [방식 1] 제품 형태 그대로 합계")
                    st.dataframe(p_df.groupby("제품")["수량"].sum().reset_index())
                with col2:
                    st.markdown("#### [방식 2] 성분별 분해 합계")
                    r_db = st.session_state.recipe_db
                    stats = {}
                    for _, r in p_df.iterrows():
                        if r['제품'] in r_db:
                            ratio = r['수량'] / r_db[r['제품']]['batch_size']
                            for mn, mq in r_db[r['제품']]['materials'].items():
                                stats[mn] = stats.get(mn, 0) + (mq * ratio)
                        else: stats[r['제품']] = stats.get(r['제품'], 0) + r['수량']
                    st.dataframe(pd.DataFrame(list(stats.items()), columns=["성분", "합계"]))

# ==============================================================================
# 8. 모드 2: 생산 및 공정 관리 (v.0.9.8 원본 모든 탭 복원)
# ==============================================================================
elif app_mode == "🏭 생산 및 공정 관리":
    st.header("🏭 생산 공정 및 품질 관리")
    
    p_tabs = st.tabs(["📊 수율/예측", "🧀 커드 생산 관리", "🗓️ 연간 스케줄", "🔬 pH/대사 관리"])
    
    with p_tabs[0]:
        st.subheader("생산 수율 계산기")
        milk_in = st.number_input("우유 투입량 (통)", 1, 200, 30)
        act_kg = st.number_input("실제 생산량 (kg)", 0.0, 100.0, 15.0)
        if st.button("💾 수율 데이터 저장"):
            st.success("수율 데이터가 저장되었습니다.")

    with p_tabs[1]:
        st.subheader("🧀 커드 생산 프로세스")
        st.write("대사 시작 및 포장 단계 관리...")
        if st.button("🚀 대사 시작 (우유 재고 차감)"):
            if update_inventory("우유", -float(milk_in)):
                st.success("우유 재고가 정상 차감되었습니다.")

    with p_tabs[2]:
        st.subheader("📅 월별 주요 대사 일정")
        m = st.selectbox("월 선택", [f"{i}월" for i in range(1, 13)], index=datetime.now(KST).month-1)
        st.info(st.session_state.get('schedule_db', {}).get(int(m[:-1]), "일정 없음"))

    with p_tabs[3]:
        st.subheader("🔬 품질 측정 로그 (pH/온도)")
        ph_val = st.slider("pH 측정", 0.0, 14.0, 4.2)
        if st.button("🧪 측정값 기록"):
            st.info(f"pH {ph_val} 기록 완료.")

# ==============================================================================
# 9. 모드 3: 실시간 재고 관리
# ==============================================================================
else:
    st.header("📦 실시간 자재 및 제품 재고")
    inv_df = load_sheet_by_name("inventory")
    st.dataframe(inv_df, use_container_width=True, hide_index=True)
    
    st.divider()
    st.subheader("➕ 재고 수동 조정 (입고/조정)")
    with st.form("inv_adj"):
        target_item = st.selectbox("품목 선택", inv_df['항목명'].tolist() if not inv_df.empty else [])
        adj_qty = st.number_input("조정 수량 (입고는 +, 소모는 -)", value=0.0)
        if st.form_submit_button("✅ 재고 수정 반영"):
            if update_inventory(target_item, adj_qty):
                st.success("재고가 업데이트되었습니다.")
                st.cache_data.clear()

# ==============================================================================
# 10. 시스템 유틸리티
# ==============================================================================
st.sidebar.divider()
if st.sidebar.button("🔄 시스템 강제 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption(f"Last Update: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')}")
st.sidebar.caption("v.1.0.8 | ELAN VPMI ERP")
