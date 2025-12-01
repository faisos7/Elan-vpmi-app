import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials

# 1. 페이지 설정
st.set_page_config(page_title="엘랑비탈 정기배송", page_icon="🏥", layout="wide")

# [중요] 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))

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
            st.title("🔒 엘랑비탈 ERP v.5.2 (DB연동)")
            with st.form("login"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

# ----------------------------------------------------
# 3. 구글 시트 데이터 로딩 (핵심 엔진) 🚀
# ----------------------------------------------------
@st.cache_data(ttl=60) # 60초마다 갱신
def load_data_from_sheet():
    try:
        # 스트림릿 시크릿에서 열쇠 꺼내기
        secrets = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(secrets, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(creds)
        
        # 엑셀 파일 열기
        sheet = client.open("vpmi_data").sheet1
        data = sheet.get_all_records()
        
        # 데이터 변환 (엑셀 -> 앱 형식)
        db = {}
        for row in data:
            name = row['이름']
            if not name: continue # 빈 줄 건너뛰기
            
            # 주문내역 파싱 (예: "시원한 것:21, 커드:7")
            items_list = []
            raw_items = str(row['주문내역']).split(',')
            for item in raw_items:
                if ':' in item:
                    p_name, p_qty = item.split(':')
                    items_list.append({
                        "제품": p_name.strip(), 
                        "수량": int(p_qty.strip()),
                        "용량": "표준" # 엑셀에 용량이 없으면 기본값
                    })
            
            db[name] = {
                "group": row['그룹'],
                "note": row['비고'],
                "default": True if str(row['기본발송']).upper() == 'O' else False,
                "items": items_list
            }
        return db
    except Exception as e:
        st.error(f"❌ 구글 시트 연결 실패: {e}")
        return {}

# 4. 세션 초기화
def init_session_state():
    # (1) 날짜
    if 'target_date' not in st.session_state:
        st.session_state.target_date = datetime.now(KST)
    
    # (2) 뷰 모드
    if 'view_month' not in st.session_state:
        st.session_state.view_month = st.session_state.target_date.month

    # (3) 환자 DB (구글 시트에서 불러오기!)
    if 'patient_db' not in st.session_state:
        with st.spinner('구글 장부에서 데이터를 가져오는 중...'):
            st.session_state.patient_db = load_data_from_sheet()

    # (4) 연간 일정 DB
    if 'schedule_db' not in st.session_state:
        st.session_state.schedule_db = {
            1: {"title": "1월 (JAN)", "main": ["동백꽃 (대사/필터링)", "인삼사이다 (병입)", "유기농 우유 커드"], "note": "동백꽃 pH 3.8~4.0 도달 시 종료"},
            2: {"title": "2월 (FEB)", "main": ["갈대뿌리 (채취/건조/대사)", "당근 (대사)"], "note": "갈대뿌리 세척 후 건조 수율 약 37%"},
            3: {"title": "3월 (MAR)", "main": ["봄꽃 대사 (장미, 프리지아, 카네이션 등)", "표고버섯", "커피콩(실험)"], "note": "꽃:줄기 비율 1:1 테스트"},
            4: {"title": "4월 (APR)", "main": ["애기똥풀 (채취 시작)", "등나무꽃", "머위", "산마늘"], "note": "애기똥풀 전초 사용"},
            5: {"title": "5월 (MAY)", "main": ["개망초꽃+아카시아잎 합제 대사 (계란커드용 8:1)", "아카시아꽃 (대량 생산)", "뽕잎", "구찌뽕"], "note": "계란커드 스타터용 합제 대사 시작"},
            6: {"title": "6월 (JUN)", "main": ["매실 (청 제조)", "개망초 (채취/대사)", "완두콩"], "note": "매실 씨 제거 후 으깨거나 채썰기"},
            7: {"title": "7월 (JUL)", "main": ["연꽃 / 연잎", "무궁화", "목백일홍", "풋고추"], "note": "여름철 대사 속도 빠름 주의"},
            8: {"title": "8월 (AUG)", "main": ["풋사과 (대사)", "각종 대사체 필터링/소포장"], "note": "풋사과 1:6 비율"},
            9: {"title": "9월 (SEP)", "main": ["청귤 (대사)", "장미꽃 (가을)", "대파"], "note": "추석 선물세트 준비 기간"},
            10: {"title": "10월 (OCT)", "main": ["송이버섯 (북한산/울진산)", "표고버섯", "산자나무(비타민열매)"], "note": "송이 등외품 활용"},
            11: {"title": "11월 (NOV)", "main": ["무염김치 (대량 김장)", "생지황", "인삼(수삼/새싹삼)"], "note": "김치소+육수 배합 중요"},
            12: {"title": "12월 (DEC)", "main": ["동백꽃 (채취 시작)", "메주콩(백태)", "한 해 마감"], "note": "동백꽃 1:6, 1:9, 1:12 비율 실험"}
        }

    # (5) 레시피 DB
    if 'recipe_db' not in st.session_state:
        r_db = {}
        r_db["계란커드 스타터 [혼합]"] = {"desc": "대사체 단순 혼합", "batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}}
        r_db["계란커드 스타터 [합제]"] = {"desc": "원물 8:1 혼합 대사 (내년 5월~)", "batch_size": 9, "materials": {"개망초꽃(원물)": 8, "아카시아잎(원물)": 1, "EX": 36}}
        r_db["혼합 [E.R.P.V.P]"] = {"desc": "6배수 혼합/14병", "batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용 (50ml)": 12, "송이대사체 (50ml)": 6, "장미꽃 대사체 (50ml)": 6, "Vitamin C (3000mg)": 14, "SiO2 (1ml)": 14, "EX": 900}}
        r_db["혼합 [P.V.E]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"인삼대사체(PAGI) 항암용 (50ml)": 1, "Vitamin C (3000mg)": 1, "EX": 100}}
        r_db["혼합 [P.P.E]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"송이대사체 (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "EX": 50}}
        r_db["혼합 [Ex.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"인삼대사체(PAGI) 항암용 (50ml)": 1, "EX": 100}}
        r_db["혼합 [R.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"장미꽃 대사체 (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "인삼사이다": 50}}
        r_db["혼합 [Edf.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"개망초(EDF) (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "인삼사이다": 50}}
        r_db["혼합 [P.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"송이대사체 (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "EX": 50}}
        st.session_state.recipe_db = r_db
    
    # (6) 처방전 DB
    if 'regimen_db' not in st.session_state:
        st.session_state.regimen_db = {
            "울산 자궁근종": """1. 아침: 장미꽃 대사체 + 생수 350ml (격일)
2. 취침 전: 인삼 전체 대사체 + 생수 1.8L 혼합물 500ml
3. 식사 대용: 시원한 것 1병 + 계란-우유 대사체 1/2병
4. 생활 습관: 자궁 보온, 기상 직후 골반 스트레칭
5. 관리: 2주 단위 초음파 검사"""
        }

init_session_state()

# 5. 메인 화면
st.title("🏥 엘랑비탈 ERP v.5.2 (Live DB)")
col1, col2 = st.columns(2)

def on_date_change():
    if 'target_date' in st.session_state:
        st.session_state.view_month = st.session_state.target_date.month

with col1: 
    target_date = st.date_input("발송일", value=datetime.now(KST), key="target_date", on_change=on_date_change)

def get_week_info(date_obj):
    month = date_obj.month
    week = (date_obj.day - 1) // 7 + 1
    return f"{month}월 {week}주"

week_str = get_week_info(target_date)
month_str = f"{target_date.month}월"

st.divider()

# DB 연결 상태 확인 및 데이터 로드
if st.button("🔄 데이터 새로고침 (구글 시트)"):
    st.cache_data.clear()
    st.session_state.patient_db = load_data_from_sheet()
    st.success("최신 데이터로 갱신되었습니다!")
    st.rerun()

db = st.session_state.patient_db
sel_p = {}

c1, c2 = st.columns(2)
with c1:
    st.subheader("🚛 남양주 / 기타")
    if db:
        for k, v in db.items():
            if v['group'] != "유방암" and v['group'] != "울산":
                if st.checkbox(k, v['default'], help=v['note']): sel_p[k] = v['items']
    else:
        st.warning("데이터를 불러오는 중이거나 연결에 실패했습니다.")

with c2:
    st.subheader("🚛 유방암")
    if db:
        for k, v in db.items():
            if v['group'] == "유방암":
                if st.checkbox(k, v['default'], help=v['note']): sel_p[k] = v['items']
    
    st.divider()
    st.subheader("🚛 울산 (자궁근종)")
    if db:
        for k, v in db.items():
            if v['group'] == "울산":
                if st.checkbox(k, v['default'], help=v['note']): sel_p[k] = v['items']

st.divider()
t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🏷️ 라벨", "🎁 장연구원", "🧪 한책임", "📊 원자재", f"🏭 생산 관리 ({week_str})", f"🗓️ 연간 일정 ({month_str})", "💊 임상/처방 관리"])

# [이하 탭 로직은 v.5.1.1과 동일하므로 그대로 유지 - 생략 없이 전체 포함]
with t1:
    st.header("🖨️ 라벨 출력")
    if not sel_p: st.warning("환자를 선택하세요")
    else:
        cols = st.columns(2)
        for i, (name, items) in enumerate(sel_p.items()):
            with cols[i%2]:
                with st.container(border=True):
                    st.markdown(f"### 🧊 {name}")
                    st.caption(f"📅 {target_date.strftime('%Y-%m-%d')}")
                    st.markdown("---")
                    for x in items:
                        chk = "✅" if "혼합" in str(x['제품']) else "□"
                        # 엑셀에서 불러온 데이터는 '비고'가 없을 수 있음
                        note = f"👉 {st.session_state.patient_db[name]['note']}" if 'note' in st.session_state.patient_db[name] and st.session_state.patient_db[name]['note'] else ""
                        st.markdown(f"**{chk} {x['제품']}** {x['수량']}개 ({x['용량']})")
                    st.markdown("---")
                    st.write("🏥 **엘랑비탈바이오**")

with t2:
    st.header("🎁 장연구원 (개별 포장)")
    tot = {}
    for items in sel_p.values():
        for x in items:
            if "혼합" not in str(x['제품']):
                k = f"{x['제품']} ({x['용량']})"
                tot[k] = tot.get(k, 0) + x['수량']
    df = pd.DataFrame(list(tot.items()), columns=["제품", "수량"]).sort_values("수량", ascending=False)
    st.dataframe(df, use_container_width=True)

with t3:
    st.header("🧪 한책임 (혼합 제조)")
    req = {}
    for items in sel_p.values():
        for x in items:
            if "혼합" in str(x['제품']): req[x['제품']] = req.get(x['제품'], 0) + x['수량']
    recipes = st.session_state.recipe_db
    total_mat = {}
    if not req: st.info("혼합 제품 없음")
    else:
        for p, q in req.items():
            if p in recipes:
                with st.expander(f"📌 {p}", expanded=True):
                    c1, c2 = st.columns([1,2])
                    in_q = c1.number_input(f"{p} 수량", 0, value=q, key=f"{p}_{q}")
                    r = recipes[p]
                    c2.markdown(f"**{r['desc']}**")
                    ratio = in_q / r['batch_size'] if r['batch_size'] > 1 else in_q
                    for m, mq in r['materials'].items():
                        if isinstance(mq, (int, float)):
                            calc = mq * ratio
                            if "(50ml)" in m:
                                vol = calc * 50
                                c2.write(f"- {m}: **{calc:g}** (50*{calc:g}={vol:g} ml)")
                            elif "EX" in m or "사이다" in m:
                                c2.write(f"- {m}: **{calc:g} ml**")
                            else:
                                c2.write(f"- {m}: **{calc:g} 개**")
                            total_mat[m] = total_mat.get(m, 0) + calc
                        else: c2.write(f"- {m}: {mq}")
    st.divider()
    st.subheader("∑ 재료 총합")
    for k, v in sorted(total_mat.items(), key=lambda x: x[1], reverse=True):
        if "PAGI" in k or "인삼대사체" in k:
            vol_ml = v * 50
            st.info(f"💧 **{k}**: {v:g}개 (총 {vol_ml:,.0f} ml)")
        elif "사이다" in k:
            bottles = v / 300
            st.info(f"🥤 **{k}**: {v:,.0f} ml (약 {bottles:.1f}병)")
        elif "EX" in k:
            st.info(f"🛢️ **{k}**: {v:,.0f} ml (약 {v/1000:.1f} L)")
        else:
            st.success(f"📦 **{k}**: {v:g} 개")

with t4:
    st.header("📊 원자재 예측")
    curd_pure = 0
    curd_cool = 0
    for items in sel_p.values():
        for x in items:
            if x['제품'] == "커드" or x['제품'] == "계란 커드": curd_pure += x['수량']
            elif x['제품'] == "커드 시원한 것": curd_cool += x['수량']
    need_from_cool = curd_cool * 40
    need_from_pure = curd_pure * 150
    total_kg = (need_from_cool + need_from_pure) / 1000
    milk = (total_kg / 9) * 16
    c1, c2 = st.columns(2)
    c1.metric("커드 시원한 것 (40g)", f"{curd_cool}개")
    c2.metric("커드/계란커드 (150g)", f"{curd_pure}개")
    st.divider()
    st.info(f"🧀 **총 필요 커드:** 약 {total_kg:.2f} kg")
    st.success(f"🥛 **필요 우유:** 약 {math.ceil(milk)}통")

with t5:
    st.header(f"🏭 생산 관리 ({week_str})")
    st.markdown("---")
    st.markdown("#### 1️⃣ 원재료 투입")
    col_in1, col_in2, col_in3 = st.columns(3)
    with col_in1: in_kimchi = st.number_input("무염김치 (봉지)", 0, value=1)
    with col_in2: 
        in_milk_reg = st.number_input("일반커드 우유 (통)", 0, value=40)
        starter_15 = (in_milk_reg * 2.3) * 0.15
        oligo_for_cool = starter_15 * 0.028 
        total_starter_input = starter_15 + oligo_for_cool
        st.caption(f"🥣 **필요 스타터**")
        st.caption(f"- 냉동 시원한것 (15%):")
        st.caption(f"  └ 원액 {starter_15:.1f}kg + 올리고당 {oligo_for_cool:.3f}kg")
    with col_in3: 
        in_milk_egg = st.number_input("계란커드 우유 (통)", 0, value=0)
        egg_starter_pct = st.number_input("(개망초/아카시아) 스타터 투입비 (%)", 0, 100, 25)
    
    prod_cool_cnt = in_kimchi * 215 
    prod_cool_kg = prod_cool_cnt * 0.274 
    prod_reg_curd_kg = in_milk_reg * 2.3 * 0.217 
    total_milk_egg_kg = in_milk_egg * 2.3
    req_egg_kg = total_milk_egg_kg / 4
    req_egg_cnt = int(req_egg_kg / 0.045)
    req_starter_total = total_milk_egg_kg * (egg_starter_pct / 100)
    req_starter_daisy = req_starter_total * (8/9)
    req_starter_acacia = req_starter_total * (1/9)
    prod_egg_curd_kg = total_milk_egg_kg * 0.22 
    prod_egg_curd_cnt = int(prod_egg_curd_kg * 1000 / 150)
    req_cool_for_curd = prod_reg_curd_kg * 5.5 
    total_mix_kg = prod_reg_curd_kg + req_cool_for_curd
    mix_cnt = int(total_mix_kg * 1000 / 260)
    remain_cool_kg = prod_cool_kg - req_cool_for_curd
    remain_cool_cnt = int(remain_cool_kg * 1000 / 274)

    st.markdown("---")
    st.markdown("#### 2️⃣ 중간 생산물 & 배분 (Weight)")
    c_mid1, c_mid2, c_mid3 = st.columns(3)
    with c_mid1:
        st.info("🥬 **시원한 것 (총생산)**")
        st.metric("총 중량", f"{prod_cool_kg:.1f} kg")
        st.caption(f"무염김치 {in_kimchi}봉 기준")
    with c_mid2:
        st.warning("🥣 **중간 투입 (소모 시원한 것)**")
        st.metric("소모량", f"{req_cool_for_curd:.1f} kg")
        st.caption(f"※ 일반커드: {prod_reg_curd_kg:.1f} kg")
    with c_mid3:
        st.success("🥚 **계란 커드 (재료 계산)**")
        st.write(f"- 우유: **{total_milk_egg_kg:.1f} kg**")
        st.write(f"- 계란: **{req_egg_kg:.1f} kg** (약 {req_egg_cnt}개)")
        st.markdown("---")
        st.write(f"🧪 **스타터 ({egg_starter_pct}%)**: **{req_starter_total:.1f} kg**")
        st.caption(f"└ 개망초(8): {req_starter_daisy:.2f} kg")
        st.caption(f"└ 아카시아(1): {req_starter_acacia:.2f} kg")
    st.markdown("---")
    st.markdown("#### 3️⃣ 최종 완제품 (Final Count)")
    c_fin1, c_fin2, c_fin3 = st.columns(3)
    with c_fin1:
        st.info("🧴 **시원한 것 (최종 잔여)**")
        if remain_cool_kg < 0:
            st.metric("상태", "🚨 재료 부족")
            st.error(f"{abs(remain_cool_kg):.1f} kg 부족합니다!")
        else:
            st.metric("생산 수량 (274g)", f"{remain_cool_cnt} 병")
            st.caption(f"잔여 {remain_cool_kg:.1f} kg")
    with c_fin2:
        st.error("🥣 **커드 시원한 것**")
        st.metric("생산 수량 (260g)", f"{mix_cnt} 병")
        st.caption(f"총 {total_mix_kg:.1f} kg")
    with c_fin3:
        st.warning("🥚 **계란 커드**")
        st.metric("생산 수량 (150g)", f"{prod_egg_curd_cnt} 개")
        st.caption(f"총 {prod_egg_curd_kg:.1f} kg")
    
    st.markdown("---")
    with st.expander("🗓️ **월간 생산 계획 시뮬레이터** (유압기 사용)", expanded=False):
        st.info("💡 **유압기 사용 기준:** 1회 40~60통 대량 생산 (금요일 작업)")
        c_batch, c_cycle = st.columns(2)
        with c_batch:
            batch_milk = st.slider("1회 우유 투입량 (통)", 16, 80, 40)
        with c_cycle:
            st.write("🔄 **월간 사이클 (4주)**")
            st.write("- 1주: 일반 커드 (커드 시원한 것용)")
            st.write("- 3주: 계란 커드 (환자 공급용)")
        milk_kg_per_batch = batch_milk * 2.3
        curd_yield_kg = milk_kg_per_batch * 0.22 
        month_gen_curd = curd_yield_kg * 1
        month_egg_curd_kg = curd_yield_kg * 3
        month_egg_curd_cnt = int(month_egg_curd_kg * 1000 / 150)
        gen_mix_cnt = int((month_gen_curd * 6.5) * 1000 / 260)
        capacity_person = int(month_egg_curd_cnt / 30)
        st.markdown("---")
        c_res1, c_res2, c_res3 = st.columns(3)
        with c_res1:
            st.success("🧀 **월간 일반 커드 (1회)**")
            st.metric("총 생산량", f"{month_gen_curd:.1f} kg")
            st.caption(f"👉 커드 시원한 것 약 {gen_mix_cnt}병 생산 가능")
        with c_res2:
            st.warning("🥚 **월간 계란 커드 (3회)**")
            st.metric("총 생산량", f"{month_egg_curd_cnt} 개")
            st.caption(f"총 {month_egg_curd_kg:.1f} kg")
        with c_res3:
            st.error("👥 **수용 가능 인원**")
            st.metric("월간 케어", f"{capacity_person} 명")
            st.caption("1인 1일 1개 섭취 기준")

# Tab 6 & 7 (기존 로직 유지)
with t6:
    st.header(f"🗓️ 연간 생산 캘린더 ({st.session_state.view_month}월)")
    sel_month = st.selectbox("월 선택", list(range(1, 13)), key="view_month")
    current_sched = st.session_state.schedule_db[sel_month]
    st.subheader(f"📌 {current_sched['title']}")
    c_main, c_note = st.columns([2, 1])
    with c_main:
        st.success("🌱 **주요 생산 품목**")
        to_remove = st.multiselect("삭제할 항목 선택", current_sched['main'])
        if st.button("선택 항목 삭제", type="secondary"):
            for item in to_remove:
                st.session_state.schedule_db[sel_month]['main'].remove(item)
            st.rerun()
        for item in current_sched['main']:
            st.write(f"- {item}")
        with st.expander("➕ 일정 추가하기"):
            with st.form(f"add_sched_{sel_month}"):
                new_task = st.text_input("추가할 내용")
                if st.form_submit_button("추가"):
                    if new_task:
                        st.session_state.schedule_db[sel_month]['main'].append(new_task)
                        st.rerun()
    with c_note:
        st.info("💡 **비고 / 주의사항**")
        st.write(current_sched['note'])
        with st.expander("📝 비고 수정"):
            with st.form(f"edit_note_{sel_month}"):
                new_note = st.text_area("내용 수정", value=current_sched['note'])
                if st.form_submit_button("저장"):
                    st.session_state.schedule_db[sel_month]['note'] = new_note
                    st.rerun()

with t7:
    st.header("💊 환자별 맞춤 처방 관리")
    regimen_names = list(st.session_state.regimen_db.keys())
    selected_regimen = st.selectbox("처방전 선택", regimen_names + ["(신규 처방 등록)"])
    if selected_regimen == "(신규 처방 등록)":
        with st.form("new_regimen_form"):
            new_reg_name = st.text_input("처방명 (예: 울산 자궁근종 케어)")
            new_reg_content = st.text_area("처방 내용 (복용법, 주의사항 등)")
            if st.form_submit_button("등록"):
                if new_reg_name and new_reg_content:
                    st.session_state.regimen_db[new_reg_name] = new_reg_content
                    st.rerun()
    else:
        st.info(f"📋 **{selected_regimen}**")
        st.text_area("처방 내용", value=st.session_state.regimen_db[selected_regimen], height=200, disabled=True)
        with st.expander("✏️ 내용 수정"):
             with st.form("edit_regimen_form"):
                updated_content = st.text_area("내용 수정", value=st.session_state.regimen_db[selected_regimen])
                if st.form_submit_button("수정 저장"):
                    st.session_state.regimen_db[selected_regimen] = updated_content
                    st.rerun()
