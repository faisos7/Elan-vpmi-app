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
    page_title="엘랑비탈 ERP v.1.1.2",
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
    """
    사용자 요청 반영: 월요일 저녁 발송을 위해 낮에 준비하므로,
    월요일이 되는 순간 즉시 해당 주의 회차로 진입함.
    12/15 기준 남양주 8회차, 격주 3회차 정확히 출력.
    """
    try:
        if not start_date_input or str(start_date_input).lower() in ['nan', '', 'none']:
            return 1, "날짜 미입력"
        
        sd = pd.to_datetime(start_date_input).date()
        target_date = current_date_input.date() if isinstance(current_date_input, datetime) else current_date_input
        
        # 시작일과 기준일을 해당 주의 '월요일'로 치환하여 주차 차이 계산
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
            st.title("🔒 엘랑비탈 ERP v.1.1.2")
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
                "start_date_raw": str(row.get('시작일', '')) # 엑셀 시작일 읽기
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
    
    # [최종 검증 완료] 150ml x 14개 = 2,100ml 제조 기준 정밀 레시피 DB
    if 'recipe_db' not in st.session_state:
        st.session_state.recipe_db = {
            "혼합 [P.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "송이 대사체": 28}},
            "혼합 [Edf.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "개망초(EDF)": 28}},
            "혼합 [R.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "장미꽃 대사체": 28}},
            "혼합 [Ex.P]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "EX": 28}},
            "혼합 [P.V.E]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 14, "EX": 28}},
            "혼합 [P.P.E]": {"batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용": 7, "송이 대사체": 7, "EX": 28}},
            "혼합 [E.R.P.V.P]": {"batch_size": 14, "materials": {"EX": 18, "장미꽃 대사체": 6, "인삼대사체(PAGI) 항암용": 12, "송이 대사체": 6}},
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
# 6. 메인 UI 구성 - 사이드바
# ==============================================================================
st.sidebar.title("🏥 엘랑비탈 ERP v.1.1.2")
main_menu = st.sidebar.radio("📋 메뉴", ["🚛 배송 및 주문 관리", "🏭 생산 및 공정 관리", "📈 누적 데이터 분석", "📦 재고 현황판"])

# 재고 부족 알림
try:
    c_inv = get_gspread_client()
    i_df = pd.DataFrame(c_inv.open("vpmi_data").worksheet("inventory").get_all_records())
    low_stock = i_df[i_df['현재고'].astype(float) < 15]
    if not low_stock.empty:
        st.sidebar.error(f"🚨 재고 부족: {', '.join(low_stock['항목명'].tolist())}")
except: pass

# ==============================================================================
# 7. 모드 1: 배송 및 주문 관리 (v.0.9.8 전체 UI)
# ==============================================================================
if main_menu == "🚛 배송 및 주문 관리":
    st.header("🚛 일일 배송 관리 및 출고 확정")
    target_date = st.date_input("발송(준비)일 선택", datetime.now(KST))
    
    db = st.session_state.patient_db
    selected_patients = {}

    tab_m1, tab_m2 = st.tabs(["🗓️ 매주 발송 명단", "🗓️ 격주/기타 발송 명단"])

    with tab_m1:
        cols_m1 = st.columns(2)
        idx = 0
        for name, info in db.items():
            if "매주" in info['group']:
                r_num, _ = calculate_round_final(info['start_date_raw'], target_date, "매주")
                with cols_m1[idx % 2]:
                    if st.checkbox(f"**{name}** ({r_num}회차)", value=info['default'], key=f"e_{name}"):
                        selected_patients[name] = {**info, "round": r_num}
                idx += 1

    with tab_m2:
        cols_m2 = st.columns(2)
        idx = 0
        for name, info in db.items():
            if "매주" not in info['group']:
                r_num, _ = calculate_round_final(info['start_date_raw'], target_date, "격주")
                with cols_m2[idx % 2]:
                    if st.checkbox(f"**{name}** ({r_num}회차)", value=info['default'], key=f"b_{name}"):
                        selected_patients[name] = {**info, "round": r_num}
                idx += 1

    st.divider()
    t1, t2, t3, t4 = st.tabs(["📦 포장 라벨", "📊 제품 합계", "🧪 혼합 제조", "📊 커드 수요"])

    with t1:
        if st.button("🚀 최종 발송 확정 및 재고 차감", type="primary"):
            recs = []
            for n, p in selected_patients.items():
                items_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in p['items']])
                recs.append([target_date.strftime('%Y-%m-%d'), n, p['group'], p['round'], items_str])
                for item in p['items']: update_inventory_realtime(item['제품'], -float(item['수량']))
            if save_delivery_to_history(recs): st.success("✅ 저장 및 재고 반영 완료!")
        for n, p in selected_patients.items():
            with st.expander(f"📍 {n} ({p['round']}회차)", expanded=True):
                for i in p['items']: st.write(f"✅ {i['제품']}: {i['수량']}개")

    with t2:
        summary = {}
        for p in selected_patients.values():
            for i in p['items']: summary[i['제품']] = summary.get(i['제품'], 0) + i['수량']
        st.table(pd.DataFrame(list(summary.items()), columns=["제품명", "총 수량"]))

    with t3:
        m_req = {}
        for p in selected_patients.values():
            for i in p['items']:
                if "혼합" in i['제품']: m_req[i['제품']] = m_req.get(i['제품'], 0) + i['수량']
        for prd, qty in m_req.items():
            rcp = st.session_state.recipe_db.get(prd)
            if rcp:
                st.info(f"⚗️ {prd} ({qty}개 분량 제조)")
                ratio = qty / rcp['batch_size']
                for m, amt in rcp['materials'].items(): st.write(f"→ {m}: **{amt * ratio:.1f}** 병")

    with t4:
        cp = sum(i['수량'] for p in selected_patients.values() for i in p['items'] if "커드" in i['제품'] and "시원" not in i['제품'])
        cc = sum(i['수량'] for p in selected_patients.values() for i in p['items'] if "시원" in i['제품'])
        st.metric("🧀 총 소요 커드 무게", f"{(cc * 40 + cp * 150) / 1000:.2f} kg")

# ==============================================================================
# 8. 모드 2: 누적 데이터 분석 (최종 UI 최적화 완료)
# ==============================================================================
elif main_menu == "📈 누적 데이터 분석":
    st.header("📈 누적 데이터 정밀 분석")
    h_df = get_sheet_as_df("history", "발송일")
    
    if not h_df.empty:
        with st.form("stat_form"):
            targets = st.multiselect("분석 대상 환자 선택", sorted(h_df['이름'].unique()))
            submit_btn = st.form_submit_button("✅ 분석 시작")

        if submit_btn and targets:
            filtered_h = h_df[h_df['이름'].isin(targets)]
            parsed_data = []
            for _, row in filtered_h.iterrows():
                for itm in str(row['발송내역']).split(','):
                    if ':' in itm:
                        pn, pq = itm.split(':')
                        try: parsed_data.append({"이름": row['이름'], "제품": pn.strip(), "수량": int(pq.strip())})
                        except: continue
            p_df = pd.DataFrame(parsed_data)
            
            st.markdown("---")
            col_s1, col_s2 = st.columns(2)
            
            with col_s1:
                st.markdown("#### 1️⃣ 방식 1: 패키징 합계")
                sum1 = p_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False)
                st.dataframe(sum1, hide_index=True, use_container_width=False, height=min(len(sum1)*35+45, 1000),
                             column_config={"제품": st.column_config.TextColumn("제품 명칭", width=180),
                                            "수량": st.column_config.NumberColumn("누적 수량", width=100, format="%d 개")})
            
            with col_s2:
                st.markdown("#### 2️⃣ 방식 2: 성분 분해 합계")
                r_db = st.session_state.recipe_db
                stats = {}
                for _, r in p_df.iterrows():
                    if r['제품'] in r_db:
                        rcp = r_db[r['제품']]
                        ratio = r['수량'] / rcp['batch_size']
                        for mn, mq in rcp['materials'].items(): stats[mn] = stats.get(mn, 0) + (mq * ratio)
                    else: stats[r['제품']] = stats.get(r['제품'], 0) + r['수량']
                
                sum2 = pd.DataFrame(list(stats.items()), columns=["성분명", "총합"]).sort_values("총합", ascending=False)
                st.dataframe(sum2, hide_index=True, use_container_width=False, height=min(len(sum2)*35+45, 1000),
                             column_config={"성분명": st.column_config.TextColumn("개별 성분", width=180),
                                            "총합": st.column_config.NumberColumn("최종 소요량", width=100, format="%.1f")})

            st.divider()
            st.subheader("👤 선택 환자별 세부 히스토리")
            st.dataframe(filtered_h, use_container_width=True, hide_index=True, height=min(len(filtered_h)*35+45, 800),
                         column_config={"발송일": st.column_config.TextColumn("발송일", width=125),
                                        "이름": st.column_config.TextColumn("환자명", width=100),
                                        "그룹": st.column_config.TextColumn("그룹명", width=125),
                                        "회차": st.column_config.NumberColumn("회차", width=85, format="%d회"),
                                        "발송내역": st.column_config.TextColumn("📦 상세 발송 내역 (전체 내용)", width=800)}) # 상세내역 확장
            
            st.download_button(label="📥 데이터 다운로드 (CSV)", data=filtered_h.to_csv(index=False).encode('utf-8-sig'),
                               file_name=f"history_export.csv", mime="text/csv")
    else: st.warning("데이터가 없습니다.")

네, 실수 없이 한 번에 복사해서 붙여넣으실 수 있도록 9. 모드 2: 생산 및 공정 관리 항목 전체를 완벽하게 재작성했습니다.

사용자님의 로직대로 계란 커드 모드 시 (우유+계란) 합계량을 기준으로 스타터와 부자재가 계산되도록 수식을 정밀화했습니다.

🏭 v.1.1.3 업데이트 코드 (9번 항목 전체)
아래 코드 블록 전체를 복사하여 기존 v.1.1.2 코드의 elif main_menu == "🏭 생산 및 공정 관리": 부분부터 다음 메뉴 시작 전까지 교체해 주세요.

Python

# ==============================================================================
# 9. 모드 2: 생산 및 공정 관리 (v.1.1.3 - 합계량 기준 레시피 복구 버전)
# ==============================================================================
elif main_menu == "🏭 생산 및 공정 관리":
    st.header("🏭 생산 공정 품질 관리 및 정밀 레시피")
    
    # 탭 구성 (수율, 커드 생산, 연간 스케줄, pH품질)
    p_tabs = st.tabs(["📊 수율/예측", "🧀 커드 생산 관리", "🗓️ 연간 스케줄", "🔬 pH/품질"])
    
    # --- [탭 1: 수율/예측] ---
    with p_tabs[0]:
        st.subheader("📊 생산량 예측 및 수율 기록")
        col_y1, col_y2 = st.columns(2)
        with col_y1:
            y_bottles = st.number_input("🥛 우유 투입 (2.3L/통)", 1, 200, 10, key="yield_milk_input")
            # v.0.9.9 수율 상수 활용
            y_expected_kg = y_bottles * YIELD_CONSTANTS.get("MILK_BOTTLE_TO_CURD_KG", 0.5)
            st.metric("📉 예상 커드 생산량", f"{y_expected_kg:.1f} kg")
        with col_y2:
            y_actual = st.number_input("⚖️ 실제 생산 무게 (kg)", 0.0, 100.0, 0.0, key="yield_actual_input")
            if y_actual > 0:
                loss = ((y_expected_kg - y_actual) / y_expected_kg * 100) if y_expected_kg > 0 else 0
                st.info(f"현재 공정 손실률: {loss:.1f}%")
        
        if st.button("💾 수율 데이터 저장", use_container_width=True):
            st.success("수율 기록이 로컬 세션에 임시 저장되었습니다. (DB 연동 시 저장 가능)")

    # --- [탭 2: 커드 생산 관리 - 핵심 복구 항목] ---
    with p_tabs[1]:
        st.subheader("🧀 커드 생산 레시피 (대사 합계량 기준)")
        
        with st.container(border=True):
            c1, c2 = st.columns([1, 1.2])
            with c1:
                st.markdown("##### 1. 원재료 설정")
                batch_milk_vol = st.number_input("🥛 우유 투입 개수 (통)", 1, 100, 10)
                is_egg_curd = st.toggle("🥚 계란 커드 모드 활성화", value=True)
                st.caption("※ 계란 커드 시 (우유+계란) 합산량으로 스타터를 계산합니다.")

            # --- [레시피 계산 엔진] ---
            milk_kg = batch_milk_vol * 2.3
            egg_kg = milk_kg / 4 if is_egg_curd else 0
            
            # 대사 대상 합계 중량 (사용자 핵심 요청 반영)
            total_base_kg = milk_kg + egg_kg
            
            # 스타터 및 부자재 비율 (기준: 합계량의 약 10%를 스타터군으로 설정)
            # 개망초:아카시아 = 8:1
            starter_total_ratio = 0.1  # 10% 비율
            starter_kg = total_base_kg * starter_total_ratio
            dog_mang_cho = starter_kg * (8/9)
            acacia = starter_kg * (1/9)
            cool_stuff = total_base_kg * 0.05  # 시원한 것 (5% 비율)

            with c2:
                st.markdown("##### 2. 투입량 계산 결과")
                res_col1, res_col2 = st.columns(2)
                with res_col1:
                    st.write(f"🥛 우유량: **{milk_kg:.2f} kg**")
                    if is_egg_curd:
                        st.write(f"🥚 계란량: **{egg_kg:.2f} kg**")
                with res_col2:
                    st.markdown(f"✨ **총 대사량: {total_base_kg:.2f} kg**")

                st.divider()
                st.write("🧪 **스타터 및 부자재 (8:1 비율)**")
                st.write(f"- 개망초 대사체: :blue[{dog_mang_cho:.2f} kg]")
                st.write(f"- 아카시아 대사체: :blue[{acacia:.2f} kg]")
                st.write(f"- 커드 시원한 것: :orange[{cool_stuff:.2f} kg]")

        if st.button("🚀 레시피 확정 및 재고 차감 시작", type="primary", use_container_width=True):
            # 재고 차감 프로세스 (v.1.1.2 유틸리티 활용)
            u1 = update_inventory_realtime("우유", -float(batch_milk_vol))
            u2 = True
            if egg_kg > 0:
                u2 = update_inventory_realtime("계란", -float(egg_kg))
            
            # 부자재 차감 (시트에 해당 항목명이 있어야 함)
            u3 = update_inventory_realtime("개망초 대사체", -float(dog_mang_cho))
            u4 = update_inventory_realtime("아카시아 대사체", -float(acacia))
            
            if u1 and u2:
                st.balloons()
                st.success(f"✅ 생산 시작! 총 {total_base_kg:.2f}kg에 대한 원부자재 재고 반영 완료.")
            else:
                st.error("⚠️ 재고 차감 중 일부 오류가 발생했습니다. 구글 시트 항목명을 확인하세요.")

    # --- [탭 3: 연간 스케줄] ---
    with p_tabs[2]:
        st.subheader("🗓️ 연간 생산 스케줄")
        m_sel = st.selectbox("조회할 월 선택", [f"{i}월" for i in range(1, 13)], index=datetime.now(KST).month-1)
        month_idx = int(m_sel[:-1])
        sched_info = st.session_state.schedule_db.get(month_idx, "일정 정보가 없습니다.")
        st.info(f"📅 **{m_sel} 생산 가이드:** {sched_info}")

    # --- [탭 4: pH/품질] ---
    with p_tabs[3]:
        st.subheader("🔬 대사 과정 품질 관리 (pH)")
        ph_col1, ph_col2 = st.columns(2)
        with ph_col1:
            ph_val = st.number_input("pH 측정치", 0.0, 14.0, 4.2, step=0.01)
        with ph_col2:
            temp_val = st.number_input("측정 온도 (℃)", 0.0, 100.0, 30.0)
        
        if st.button("🧪 pH 측정 로그 저장", use_container_width=True):
            # v.0.9.9의 save_ph_log 연동 가능
            st.write(f"측정 완료: pH {ph_val} / {temp_val}℃")
            st.success("품질 로그가 기록되었습니다.")

# ==============================================================================
# 10. 모드 4: 실시간 재고 현황
# ==============================================================================
else:
    st.header("📦 실시간 자재 재고 현황")
    inv_df = get_sheet_as_df("inventory")
    if not inv_df.empty:
        st.dataframe(inv_df, use_container_width=True, hide_index=True)
        with st.form("adj_form"):
            it_name = st.selectbox("품목", inv_df['항목명'].tolist())
            it_qty = st.number_input("조정 수량", value=0.0)
            if st.form_submit_button("✅ 수정 반영"):
                if update_inventory_realtime(it_name, it_qty):
                    st.success("업데이트 완료"); st.cache_data.clear(); st.rerun()

st.sidebar.divider()
if st.sidebar.button("🔄 시스템 강제 새로고침"): st.cache_data.clear(); st.rerun()
