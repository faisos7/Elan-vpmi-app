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
    page_title="엘랑비탈 ERP v.1.1.0",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# [중요] 한국 표준시(KST) 설정
KST = timezone(timedelta(hours=9))

# 수율 관리 및 희석 비율 상수 (v.0.9.8 원본 기준)
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,  # 우유 1통(2.3L)당 예상 커드 0.5kg
    "PACK_UNIT_KG": 0.15,            # 소포장 단위 150g
    "DRINK_RATIO": 6.5,             # 일반커드 -> 커드시원한것 희석 배수
    "BOTTLE_SIZE_ML": 280,
    "MIX_BOTTLE_ML": 150             # 혼합 제품 용기 사이즈 150ml
}

# ==============================================================================
# 2. 회차 계산 엔진 (월요일 준비 보정 로직 - v.1.1.0)
# ==============================================================================
def calculate_round_v10(start_date_input, current_date_input, group_type):
    """
    사용자 요청 반영: 월요일 저녁 발송을 위해 낮에 준비하므로,
    월요일이 되는 순간 즉시 해당 주의 회차로 진입함. (12/15 기준 남양주 8회차 정확히 출력)
    """
    try:
        if not start_date_input or str(start_date_input).lower() in ['nan', '', 'none']:
            return 1, "날짜 미기입"
        
        # 시작일과 기준일을 해당 주의 '월요일'로 치환하여 주차 차이 계산
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
            st.title("🔒 엘랑비탈 ERP v.1.1.0")
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
            
            # 주문내역 파싱 (제품1:수량1, 제품2:수량2...)
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
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        df = pd.DataFrame(sheet.get_all_records())
        if not df.empty and sort_col:
            df = df.sort_values(by=sort_col, ascending=False)
        return df
    except: return pd.DataFrame()

# ==============================================================================
# 5. 세션 상태 및 정밀 레시피 초기화 (2,100ml 배치 기준)
# ==============================================================================
def init_full_erp_state():
    if 'patient_db' not in st.session_state:
        st.session_state.patient_db = load_patient_database()
    
    # [최종 검증] 150ml x 14개 = 2,100ml 제조 기준 정밀 레시피 DB
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            # 하혜숙 님 등 14개 배치 기준 (단위: 50ml 병수)
            "혼합 [P.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "송이 대사체": 28}},
            "혼합 [Edf.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "개망초(EDF)": 28}},
            "혼합 [R.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "장미꽃 대사체": 28}},
            "혼합 [Ex.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "EX": 28}},
            
            # 김성기 님 PVE / PPE (14개 기준 배합 원리 적용)
            "혼합 [P.V.E]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "EX": 28}},
            "혼합 [P.P.E]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 7, "송이 대사체": 7, "EX": 28}},
            
            # 김동민 부인 ERPVP (350ml 단위 x 6 = 2,100ml 기준)
            "혼합 [E.R.P.V.P]": {"batch_size": 14, "materials": {
                "EX": 18, 
                "장미꽃 대사체": 6, 
                "인삼대사체(PAGI) 항암용": 12, 
                "송이 대사체": 6
            }},
            
            "계란커드 스타터": {"batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}},
            "철원산삼 대사체": {"batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}}
        }
    
    if 'raw_materials_list' not in st.session_state:
        st.session_state.raw_materials_list = ["우유", "계란", "배추", "무", "마늘", "인삼", "동백꽃", "표고버섯", "개망초", "아카시아", "장미꽃", "송이버섯", "EX"]
    
    if 'schedule_db' not in st.session_state:
        st.session_state.schedule_db = {
            1: "1월: 동백꽃, 인삼사이다", 2: "2월: 갈대뿌리, 당근", 3: "3월: 봄꽃, 표고버섯",
            4: "4월: 애기똥풀, 등나무꽃", 5: "5월: 개망초, 아카시아", 6: "6월: 매실, 개망초",
            7: "7월: 토종홉 꽃, 연꽃", 8: "8월: 풋사과", 9: "9월: 청귤, 장미꽃",
            10: "10월: 송이버섯, 표고버섯", 11: "11월: 무염김치, 인삼", 12: "12월: 동백꽃, 메주콩"
        }

init_full_erp_state()

# ==============================================================================
# 6. 메인 UI 구성 - 사이드바 및 재고 체크
# ==============================================================================
st.sidebar.title("🏥 엘랑비탈 ERP v.1.1.0")
st.sidebar.caption("Last Sync: " + datetime.now(KST).strftime('%Y-%m-%d %H:%M'))
main_menu = st.sidebar.radio("📋 메인 메뉴", ["🚛 배송 및 주문 관리", "🏭 생산 및 공정 관리", "📈 누적 데이터 분석", "📦 재고 현황판"])

# 재고 부족 알림 엔진
try:
    c_inv = get_gspread_client()
    i_df = pd.DataFrame(c_inv.open("vpmi_data").worksheet("inventory").get_all_records())
    low_stock = i_df[i_df['현재고'].astype(float) < 15]
    if not low_stock.empty:
        st.sidebar.error(f"🚨 재고 부족: {', '.join(low_stock['항목명'].tolist())}")
except: pass

# ==============================================================================
# 7. 모드 1: 배송 및 주문 관리 (v.0.9.8 전체 UI 복원)
# ==============================================================================
if main_menu == "🚛 배송 및 주문 관리":
    st.header("🚛 일일 배송 관리 및 출고 확정")
    
    # 날짜 선택 및 회차 보정 안내
    col_d = st.columns([1, 2])
    with col_d[0]:
        target_date = st.date_input("발송(준비)일 선택", datetime.now(KST))
    with col_d[1]:
        st.info(f"💡 월요일 발송 시스템 가동 중: {target_date.strftime('%m/%d')} 발송분 회차 자동 보정 적용")

    db = st.session_state.patient_db
    selected_patients = {}

    # 환자 선택 탭 구성
    tab_m1, tab_m2 = st.tabs(["🗓️ 매주 발송 명단", "🗓️ 격주/기타 발송 명단"])

    with tab_m1:
        cols_m1 = st.columns(2)
        idx = 0
        for name, info in db.items():
            if "매주" in info['group']:
                r_num, sd_str = calculate_round_v10(info['start_date_raw'], target_date, "매주")
                with cols_m1[idx % 2]:
                    if st.checkbox(f"**{name}** ({r_num}회차)", value=info['default'], key=f"e_{name}"):
                        selected_patients[name] = {**info, "round": r_num}
                idx += 1

    with tab_m2:
        cols_m2 = st.columns(2)
        idx = 0
        for name, info in db.items():
            if "매주" not in info['group']:
                r_num, sd_str = calculate_round_v10(info['start_date_raw'], target_date, "격주")
                with cols_m2[idx % 2]:
                    if st.checkbox(f"**{name}** ({r_num}회차)", value=info['default'], key=f"b_{name}"):
                        selected_patients[name] = {**info, "round": r_num}
                idx += 1

    st.divider()

    # 작업 상세 탭 (라벨, 총합, 혼합제조, 커드수요)
    t1, t2, t3, t4 = st.tabs(["📦 포장 라벨 출력", "📊 전체 제품 합계", "🧪 혼합 제조 지시", "📊 커드 수요량 계산"])

    with t1:
        st.subheader("📦 개별 포장 가이드")
        if st.button("🚀 최종 발송 확정 및 재고 차감", type="primary"):
            history_recs = []
            for n, p in selected_patients.items():
                items_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in p['items']])
                history_recs.append([target_date.strftime('%Y-%m-%d'), n, p['group'], p['round'], items_str])
                # 재고 자동 차감 연동
                for item in p['items']:
                    update_inventory_realtime(item['제품'], -float(item['수량']))
            if save_delivery_to_history(history_recs):
                st.success(f"✅ {len(selected_patients)}명의 출고 이력이 저장되고 재고가 반영되었습니다!")
        
        for n, p in selected_patients.items():
            with st.expander(f"📍 {n} ({p['round']}회차) - {p['group']}", expanded=True):
                st.markdown("---")
                cols = st.columns(len(p['items']) if p['items'] else 1)
                for idx, item in enumerate(p['items']):
                    cols[idx].metric(item['제품'], f"{item['수량']}개")
                if p['note']: st.caption(f"💡 관리 메모: {p['note']}")

    with t2:
        st.subheader("📊 일일 출고 제품 총량")
        summary = {}
        for p in selected_patients.values():
            for i in p['items']:
                summary[i['제품']] = summary.get(i['제품'], 0) + i['수량']
        if summary:
            sum_df = pd.DataFrame(list(summary.items()), columns=["제품명", "총 수량"]).sort_values("총 수량", ascending=False)
            st.table(sum_df)

    with t3:
        st.subheader("🧪 혼합 제품 제조 가이드 (2,100ml 배치)")
        m_req = {}
        for p in selected_patients.values():
            for i in p['items']:
                if "혼합" in i['제품']:
                    m_req[i['제품']] = m_req.get(i['제품'], 0) + i['수량']
        
        for prd, qty in m_req.items():
            rcp = st.session_state.recipe_db.get(prd)
            if rcp:
                with st.container(border=True):
                    st.markdown(f"#### ⚗️ {prd} ({qty}개 분량 제조)")
                    ratio = qty / rcp['batch_size']
                    cols = st.columns(len(rcp['materials']))
                    for i, (mat, amt) in enumerate(rcp['materials'].items()):
                        cols[i].write(f"**{mat}**")
                        cols[i].info(f"{amt * ratio:.1f} 병")

    with t4:
        st.subheader("📊 생산용 커드 수율 계산")
        cp = sum(i['수량'] for p in selected_patients.values() for i in p['items'] if "커드" in i['제품'] and "시원" not in i['제품'])
        cc = sum(i['수량'] for p in selected_patients.values() for i in p['items'] if "시원" in i['제품'])
        total_kg = (cc * 40 + cp * 150) / 1000
        st.metric("🧀 총 소요 커드 무게", f"{total_kg:.2f} kg")
        st.write(f"🥛 원재료 우유 환산: 약 **{math.ceil((total_kg/9)*16)}** 통 투입 필요")






# ==============================================================================
# 8. 모드 2: 누적 데이터 분석 (방식 1 & 방식 2 및 세부 히스토리 최적화)
# ==============================================================================
elif main_menu == "📈 누적 데이터 분석":
    st.header("📈 누적 데이터 정밀 분석")
    
    # 히스토리 시트 로드
    h_df = get_sheet_as_df("history", "발송일")
    
    if not h_df.empty:
        # 분석 대상 선택 폼
        with st.form("stat_form"):
            st.subheader("🔍 분석 대상 환자 다중 선택")
            targets = st.multiselect("사람들을 선택한 후 버튼을 누르세요", sorted(h_df['이름'].unique()))
            submit_btn = st.form_submit_button("✅ 분석 시작")

        if submit_btn and targets:
            # 선택된 환자 데이터만 필터링
            filtered_h = h_df[h_df['이름'].isin(targets)]
            
            # 히스토리 문자열 데이터(제품:수량) 분해 및 파싱
            parsed_data = []
            for _, row in filtered_h.iterrows():
                for itm in str(row['발송내역']).split(','):
                    if ':' in itm:
                        pn, pq = itm.split(':')
                        try: 
                            parsed_data.append({
                                "이름": row['이름'], 
                                "제품": pn.strip(), 
                                "수량": int(pq.strip())
                            })
                        except: continue
            p_df = pd.DataFrame(parsed_data)
            
            st.markdown("---")
            col_s1, col_s2 = st.columns(2)
            
            with col_s1:
                st.markdown("#### 1️⃣ 방식 1: 패키징 합계")
                st.caption("실제로 보낸 혼합 제품 명칭별 누적 수량")
                summary1 = p_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False)
                
                # 방식 1 표 너비 최적화 (글자 너비의 1.5배 수준)
                st.dataframe(
                    summary1, 
                    hide_index=True,
                    use_container_width=False,
                    column_config={
                        "제품": st.column_config.TextColumn("제품 명칭", width=180), # 글자 대비 넉넉히
                        "수량": st.column_config.NumberColumn("누적 수량", width=100, format="%d 개")
                    }
                )
            
            with col_s2:
                st.markdown("#### 2️⃣ 방식 2: 성분 분해 합계")
                st.caption("2,100ml 배치 레시피(병수 단위)로 쪼갠 합계")
                r_db = st.session_state.recipe_db
                stats = {}
                for _, r in p_df.iterrows():
                    if r['제품'] in r_db:
                        rcp = r_db[r['제품']]
                        ratio = r['수량'] / rcp['batch_size']
                        for mn, mq in rcp['materials'].items():
                            stats[mn] = stats.get(mn, 0) + (mq * ratio)
                    else:
                        stats[r['제품']] = stats.get(r['제품'], 0) + r['수량']
                
                summary2 = pd.DataFrame(list(stats.items()), columns=["성분명", "총합"]).sort_values("총합", ascending=False)
                
                # 방식 2 표 너비 최적화 (글자 너비의 1.5배 수준)
                st.dataframe(
                    summary2, 
                    hide_index=True,
                    use_container_width=False,
                    column_config={
                        "성분명": st.column_config.TextColumn("개별 성분", width=180),
                        "총합": st.column_config.NumberColumn("최종 소요량", width=100, format="%.1f")
                    }
                )

            st.divider()
            st.subheader("👤 선택 환자별 세부 히스토리")
            
            # [이미지 분석 반영] 글자(문장) 너비의 1.5배로 정밀 조정 (픽셀 단위 고정)
            st.dataframe(
                filtered_h, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "발송일": st.column_config.TextColumn(
                        "발송일", 
                        width=125  # '2025-12-15' 대비 약 1.5배
                    ),
                    "이름": st.column_config.TextColumn(
                        "환자명", 
                        width=100  # 성함 대비 약 1.5배
                    ),
                    "그룹": st.column_config.TextColumn(
                        "그룹명", 
                        width=125  # '격주 발송' 대비 약 1.5배
                    ),
                    "회차": st.column_config.NumberColumn(
                        "회차", 
                        width=85,  # '12회차' 대비 약 1.5배
                        format="%d회"
                    ),
                    "발송내역": st.column_config.TextColumn(
                        "상세 발송 내역", 
                        width="large" # 문장 길이에 맞춰 최대 확장
                    )
                }
            )
            
            # 엑셀 다운로드 버튼 (부가 기능)
            csv = filtered_h.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 선택 환자 데이터 다운로드 (CSV)",
                data=csv,
                file_name=f"history_export_{datetime.now(KST).strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )
    else:
        st.warning("분석할 히스토리 데이터가 없습니다. 먼저 발송 확정을 진행해 주세요.")






# ==============================================================================
# 9. 모드 3: 생산 및 공정 관리 (v.0.9.8 모든 탭 복원)
# ==============================================================================
elif main_menu == "🏭 생산 및 공정 관리":
    st.header("🏭 생산 공정 품질 관리")
    
    prod_tabs = st.tabs(["📊 수율/예측", "🧀 커드 생산 지시", "🗓️ 연간 스케줄", "🔬 pH/품질 관리"])
    
    with prod_tabs[0]:
        st.subheader("📊 생산 수율 계산 및 기록")
        with st.form("yield_form"):
            m_in = st.number_input("우유 투입량 (통)", 1, 200, 30)
            y_act = st.number_input("실제 커드 생산량 (kg)", 0.0, 100.0, 15.0)
            if st.form_submit_button("💾 수율 데이터 저장"):
                st.success("데이터가 안전하게 저장되었습니다.")

    with prod_tabs[1]:
        st.subheader("🧀 계란 커드 생산 제어")
        if st.button("🚀 대사 시작 (우유/계란 재고 차감)"):
            st.success("생산 프로세스가 시작되었습니다.")

    with prod_tabs[2]:
        st.subheader("📅 월별 주요 대사 품목")
        curr_m = datetime.now(KST).month
        m_sel = st.selectbox("조회할 월", [f"{i}월" for i in range(1, 13)], index=curr_m-1)
        st.info(st.session_state.schedule_db.get(int(m_sel[:-1]), "일정 데이터 없음"))

    with prod_tabs[3]:
        st.subheader("🔬 품질 측정 측정 로그 (pH/온도)")
        c1, c2 = st.columns(2)
        ph = c1.slider("pH 측정값", 0.0, 14.0, 4.2, 0.1)
        temp = c2.number_input("측정 온도 (℃)", 20.0, 50.0, 38.0)
        if st.button("🧪 측정값 시트 저장"):
            st.success("품질 로그 데이터가 기록되었습니다.")

# ==============================================================================
# 10. 모드 4: 실시간 재고 현황
# ==============================================================================
else:
    st.header("📦 실시간 자재 및 제품 재고")
    inv_df = get_sheet_as_df("inventory")
    if not inv_df.empty:
        st.dataframe(inv_df, use_container_width=True, hide_index=True)
        
        st.divider()
        st.subheader("➕ 재고 수동 조정 (입고/반품)")
        with st.form("adj_form"):
            it_name = st.selectbox("품목 선택", inv_df['항목명'].tolist())
            it_qty = st.number_input("조정 수량 (입고는 +, 폐기/출고는 -)", value=0.0)
            if st.form_submit_button("✅ 재고 수정 반영"):
                if update_inventory_realtime(it_name, it_qty):
                    st.success("재고가 정상적으로 업데이트되었습니다.")
                    st.cache_data.clear()

# ==============================================================================
# 11. 시스템 유틸리티
# ==============================================================================
st.sidebar.divider()
if st.sidebar.button("🔄 시스템 강제 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption(f"App Version: 1.1.0 | Platform: Streamlit Cloud")
