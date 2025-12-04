import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
import holidays

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
            st.title("🔒 엘랑비탈 ERP v.7.0")
            with st.form("login"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

# 3. 구글 시트 데이터 로딩 및 저장 함수
def get_gspread_client():
    secrets = st.secrets["gcp_service_account"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(secrets, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=60) 
def load_data_from_sheet():
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").sheet1
        data = sheet.get_all_records()
        
        # [수정] 기본 용량 사전 (표준 용량이 정해진 것들)
        default_caps = {
            "시원한 것": "280ml",
            "마시는 것": "280ml",
            "커드 시원한 것": "280ml",
            "인삼 사이다": "280ml",
            "EX": "280ml",
            "인삼대사체(PAGI)": "50ml",
            "인삼대사체(PAGI) 항암용": "50ml",
            "인삼대사체(PAGI) 뇌질환용": "50ml",
            "개망초(EDF)": "50ml",
            "장미꽃 대사체": "50ml",
            "애기똥풀 대사체": "50ml",
            "송이 대사체": "50ml",
            "표고버섯 대사체": "50ml",
            "커드": "150g",
            "계란 커드": "150g"
        }

        db = {}
        for row in data:
            name = row['이름']
            if not name: continue
            
            items_list = []
            raw_items = str(row['주문내역']).split(',')
            for item in raw_items:
                if ':' in item:
                    p_name, p_qty = item.split(':')
                    clean_name = p_name.strip()
                    
                    if clean_name == "PAGI 희석액": clean_name = "인삼대사체(PAGI) 항암용"
                    
                    # [v.7.0 수정] 용량 매칭: 없으면 빈칸("")으로 둠 (더이상 '표준' 안씀)
                    cap = default_caps.get(clean_name, "")
                    
                    items_list.append({
                        "제품": clean_name, 
                        "수량": int(p_qty.strip()),
                        "용량": cap 
                    })
            
            round_val = row.get('회차')
            if round_val is None or str(round_val).strip() == "":
                round_num = 1 
            else:
                try:
                    round_num = int(str(round_val).replace('회', '').replace('주', '').strip())
                except:
                    round_num = 1

            start_date_str = str(row.get('시작일', '')).strip()

            db[name] = {
                "group": row['그룹'],
                "note": row['비고'],
                "default": True if str(row['기본발송']).upper() == 'O' else False,
                "items": items_list,
                "round": round_num,
                "start_date_raw": start_date_str
            }
        return db
    except Exception as e:
        st.error(f"❌ 데이터 로딩 실패: {e}")
        return {}

# [v.6.5] 발송 이력 저장
def save_to_history(record_list):
    try:
        client = get_gspread_client()
        try:
            sheet = client.open("vpmi_data").worksheet("history")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="history", rows="1000", cols="10")
            sheet.append_row(["발송일", "이름", "그룹", "회차", "발송내역"])
        
        for record in record_list:
            sheet.append_row(record)
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# [v.7.0] 생산 이력 저장 함수
def save_production_record(record):
    try:
        client = get_gspread_client()
        try:
            sheet = client.open("vpmi_data").worksheet("production")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="production", rows="1000", cols="10")
            sheet.append_row(["생산일", "종류", "원재료", "투입량(kg)", "비율", "스타터총량", "정제수", "조성액", "올리고당", "비고"])
            
        sheet.append_row(record)
        return True
    except Exception as e:
        st.error(f"생산 이력 저장 실패: {e}")
        return False

# 이력 조회 함수
def load_history_data(sheet_name):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except:
        return pd.DataFrame()

# 4. 데이터 초기화
def init_session_state():
    if 'target_date' not in st.session_state:
        st.session_state.target_date = datetime.now(KST)
    if 'view_month' not in st.session_state:
        st.session_state.view_month = st.session_state.target_date.month

    if 'patient_db' not in st.session_state:
        loaded_db = load_data_from_sheet()
        if loaded_db:
            st.session_state.patient_db = loaded_db
        else:
            st.session_state.patient_db = {} 

    if 'schedule_db' not in st.session_state:
        st.session_state.schedule_db = {
            1: {"title": "1월 (JAN)", "main": ["동백꽃 (대사/필터링)", "인삼사이다 (병입)", "유기농 우유 커드"], "note": "동백꽃 pH 3.8~4.0 도달 시 종료"},
            2: {"title": "2월 (FEB)", "main": ["갈대뿌리 (채취/건조/대사)", "당근 (대사)"], "note": "갈대뿌리 세척 후 건조 수율 약 37%"},
            3: {"title": "3월 (MAR)", "main": ["봄꽃 대사", "표고버섯"], "note": "꽃:줄기 비율 1:1 테스트"},
            4: {"title": "4월 (APR)", "main": ["애기똥풀 (채취 시작)", "등나무꽃"], "note": "애기똥풀 전초 사용"},
            5: {"title": "5월 (MAY)", "main": ["개망초꽃+아카시아잎 합제", "아카시아꽃", "뽕잎"], "note": "계란커드 스타터용 합제 대사 시작"},
            6: {"title": "6월 (JUN)", "main": ["매실 (청 제조)", "개망초"], "note": "매실 씨 제거"},
            7: {"title": "7월 (JUL)", "main": ["토종홉 꽃 (개화/관리)", "연꽃 / 연잎", "무궁화"], "note": "여름철 대사 속도 빠름 주의"},
            8: {"title": "8월 (AUG)", "main": ["풋사과 (대사)"], "note": "풋사과 1:6 비율"},
            9: {"title": "9월 (SEP)", "main": ["청귤", "장미꽃 (가을)"], "note": "추석 선물세트 준비"},
            10: {"title": "10월 (OCT)", "main": ["송이버섯", "표고버섯", "산자나무"], "note": "송이 등외품 활용"},
            11: {"title": "11월 (NOV)", "main": ["무염김치", "생지황", "인삼"], "note": "김치소+육수 배합 중요"},
            12: {"title": "12월 (DEC)", "main": ["동백꽃", "메주콩"], "note": "한 해 마감"}
        }

    if 'yearly_memos' not in st.session_state:
        st.session_state.yearly_memos = []

    if 'product_list' not in st.session_state:
        plist = [
            "시원한 것", "마시는 것", "커드 시원한 것", "커드", "계란 커드", "EX",
            "인삼대사체(PAGI) 항암용", "인삼대사체(PAGI) 뇌질환용",
            "표고버섯 대사체", "개망초(EDF)", "장미꽃 대사체",
            "애기똥풀 대사체", "인삼 사이다", "송이 대사체",
            "PAGI 희석액", "Vitamin C", "SiO2", "계란커드 스타터",
            "혼합 [E.R.P.V.P]", "혼합 [P.V.E]", "혼합 [P.P.E]",
            "혼합 [Ex.P]", "혼합 [R.P]", "혼합 [Edf.P]", "혼합 [P.P]"
        ]
        st.session_state.product_list = plist

    if 'recipe_db' not in st.session_state:
        r_db = {}
        r_db["계란커드 스타터 [혼합]"] = {"desc": "대사체 단순 혼합", "batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}}
        r_db["계란커드 스타터 [합제]"] = {"desc": "원물 8:1 혼합 대사", "batch_size": 9, "materials": {"개망초꽃(원물)": 8, "아카시아잎(원물)": 1, "EX": 36}}
        st.session_state.recipe_db = r_db
    
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
st.title("🏥 엘랑비탈 ERP v.7.0 (Production)")
col1, col2 = st.columns(2)

# 회차 계산 함수
def calculate_round_v4(start_date_input, current_date_input, group_type):
    try:
        if not start_date_input or str(start_date_input) == 'nan':
            return 0, "날짜없음"
        start_date = pd.to_datetime(start_date_input).date()
        if isinstance(current_date_input, datetime):
            curr_date = current_date_input.date()
        else:
            curr_date = current_date_input
        delta = (curr_date - start_date).days
        if delta < 0: return 0, start_date.strftime('%Y-%m-%d')
        weeks_passed = round(delta / 7)
        if group_type == "매주 발송":
            r = weeks_passed + 1
        else: 
            r = (weeks_passed // 2) + 1
        return r, start_date.strftime('%Y-%m-%d')
    except Exception as e:
        return 1, "오류"

def on_date_change():
    if 'target_date' in st.session_state:
        st.session_state.view_month = st.session_state.target_date.month

# 공휴일 체크
kr_holidays = holidays.KR()
def check_delivery_date(date_obj):
    weekday = date_obj.weekday()
    if weekday == 4: return False, "⛔ **금요일 발송 금지:** 월요일 도착 위험 (냉장식품 변질 우려)"
    if weekday == 5: return False, "⛔ **토요일 발송 불가:** 휴무일"
    if weekday == 6: return False, "⛔ **일요일 발송 불가:** 휴무일"
    if date_obj in kr_holidays:
        return False, f"⛔ **휴일 발송 불가:** {kr_holidays.get(date_obj)}"
    next_day = date_obj + timedelta(days=1)
    if next_day in kr_holidays:
        return False, f"⛔ **익일 휴일({kr_holidays.get(next_day)}):** 택배 하역장 방치 위험!"
    for i in range(1, 4): 
        future_day = date_obj + timedelta(days=i)
        if future_day in kr_holidays:
            hol_name = kr_holidays.get(future_day)
            if 'Seollal' in hol_name or 'Chuseok' in hol_name or '설날' in hol_name or '추석' in hol_name:
                return False, f"⛔ **명절 물류 대란 예방:** {hol_name} 연휴 {i}일 전입니다."
    return True, "✅ **발송 가능:** 안전한 날짜입니다."

with col1: 
    target_date = st.date_input("발송일", value=datetime.now(KST), key="target_date", on_change=on_date_change)
    is_ok, msg = check_delivery_date(target_date)
    if is_ok: st.success(msg)
    else: st.error(msg)

def get_week_info(date_obj):
    month = date_obj.month
    week = (date_obj.day - 1) // 7 + 1
    return f"{month}월 {week}주"

week_str = get_week_info(target_date)
month_str = f"{target_date.month}월"

with col2:
    st.info(f"📅 **{target_date.year}년 {target_date.month}월 휴무일 정보**")
    month_holidays = []
    for date, name in kr_holidays.items():
        if date.year == target_date.year and date.month == target_date.month:
            month_holidays.append(f"• {date.day}일({date.strftime('%a')}): {name}")
    if month_holidays:
        for h in month_holidays:
            st.write(h)
    else:
        st.write("• 이 달은 공휴일이 없습니다.")

st.divider()

if st.button("🔄 데이터 새로고침 (구글 시트)"):
    st.cache_data.clear()
    st.session_state.patient_db = load_data_from_sheet()
    st.success("갱신 완료!")
    st.rerun()

db = st.session_state.patient_db
sel_p = {}

c1, c2 = st.columns(2)
with c1:
    st.subheader("🚛 매주 발송")
    if db:
        for k, v in db.items():
            if v.get('group') == "매주 발송":
                r_num, s_date_disp = calculate_round_v4(v.get('start_date_raw'), target_date, "매주 발송")
                round_info = f" ({r_num}/12회)" 
                if r_num > 12: round_info += " 🚨"
                note_display = f" 📌{v['note']}" if v.get('note') else ""
                if st.checkbox(f"{k}{round_info}{note_display}", v.get('default'), help=f"시작일: {s_date_disp}"): 
                    sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r_num}
    else:
        st.info("데이터 로딩 중...")

with c2:
    st.subheader("🚚 격주 발송")
    if db:
        for k, v in db.items():
            if v.get('group') in ["격주 발송", "유방암", "울산"]:
                r_num, s_date_disp = calculate_round_v4(v.get('start_date_raw'), target_date, "격주 발송")
                round_info = f" ({r_num}/6회)"
                if r_num > 6: round_info += " 🚨"
                note_display = f" 📌{v['note']}" if v.get('note') else ""
                if st.checkbox(f"{k}{round_info}{note_display}", v.get('default'), help=f"시작일: {s_date_disp}"): 
                    sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r_num}

st.divider()
t1, t2, t3, t4, t5, t6, t7, t8, t9 = st.tabs(["🏷️ 라벨", "🎁 장연구원", "🧪 한책임", "📊 커드 수요량", f"🏭 생산 관리 ({week_str})", f"🗓️ 연간 일정 ({month_str})", "💊 임상/처방 관리", "📂 발송 이력", "🏭 생산 이력"])

# Tab 1: 라벨
with t1:
    c_head, c_btn = st.columns([2, 1])
    with c_head:
        st.header("🖨️ 라벨 출력")
    with c_btn:
        if st.button("📝 금일 발송 내역 저장하기", type="primary"):
            if not sel_p:
                st.warning("선택된 환자가 없습니다.")
            else:
                records = []
                today_str = target_date.strftime('%Y-%m-%d')
                for p_name, p_data in sel_p.items():
                    item_strs = []
                    for item in p_data['items']:
                         item_strs.append(f"{item['제품']}:{item['수량']}")
                    content_str = ", ".join(item_strs)
                    records.append([today_str, p_name, p_data['group'], p_data['round'], content_str])
                
                if save_to_history(records):
                    st.success(f"총 {len(records)}건 저장 완료!")
                else:
                    st.error("저장 실패")

    if not sel_p: st.warning("환자를 선택하세요")
    else:
        cols = st.columns(2)
        for i, (name, data_info) in enumerate(sel_p.items()):
            items = data_info['items']
            with cols[i%2]:
                with st.container(border=True):
                    r_num = data_info['round']
                    round_str = f" [{r_num}회차]" if r_num > 0 else ""
                    
                    st.markdown(f"### 🧊 {name}{round_str}")
                    st.caption(f"📅 {target_date.strftime('%Y-%m-%d')}")
                    st.markdown("---")
                    for x in items:
                        chk = "✅" if "혼합" in str(x['제품']) else "□"
                        display_prod = x['제품'].replace(" 항암용", "")
                        # [v.7.0 수정] 용량 정보가 있으면 표시, 없으면 생략
                        vol_str = f" ({x['용량']})" if x['용량'] else ""
                        st.markdown(f"**{chk} {display_prod}** {x['수량']}개{vol_str}")
                    st.markdown("---")
                    st.write("🏥 **엘랑비탈바이오**")

# Tab 2~7 (기존 유지)
with t2:
    st.header("🎁 장연구원 (개별 포장)")
    tot = {}
    for data_info in sel_p.values():
        items = data_info['items']
        for x in items:
            if "혼합" not in str(x['제품']):
                k = f"{x['제품']} {x['용량']}" if x.get('용량') else x['제품']
                tot[k] = tot.get(k, 0) + x['수량']
    df = pd.DataFrame(list(tot.items()), columns=["제품", "수량"]).sort_values("수량", ascending=False)
    st.dataframe(df, use_container_width=True)

with t3:
    st.header("🧪 한책임 (혼합 제조)")
    req = {}
    for data_info in sel_p.values():
        items = data_info['items']
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
    st.header("📊 커드 수요량")
    curd_pure = 0
    curd_cool = 0
    for data_info in sel_p.values():
        items = data_info['items']
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

# Tab 6: 연간 일정
with t6:
    st.header(f"🗓️ 연간 생산 캘린더 ({st.session_state.view_month}월)")
    sel_month = st.selectbox("월 선택", list(range(1, 13)), key="view_month")
    current_sched = st.session_state.schedule_db[sel_month]
    
    with st.container(border=True):
        st.subheader("📝 연간 주요 메모 (Yearly Memos)")
        c_memo, c_m_tool = st.columns([2, 1])
        with c_memo:
            if not st.session_state.yearly_memos:
                st.info("등록된 메모가 없습니다.")
            else:
                for memo in st.session_state.yearly_memos:
                    st.warning(f"📌 {memo}")
        with c_m_tool:
            with st.popover("메모 관리"):
                new_memo = st.text_input("새 메모 입력")
                if st.button("추가", key="add_memo"):
                    if new_memo:
                        st.session_state.yearly_memos.append(new_memo)
                        st.rerun()
                del_memo = st.multiselect("삭제할 메모", st.session_state.yearly_memos)
                if st.button("삭제", key="del_memo"):
                    for d in del_memo:
                        st.session_state.yearly_memos.remove(d)
                    st.rerun()
    st.divider()
    
    st.subheader(f"📅 {current_sched['title']}")
    col_main, col_note = st.columns([2, 1])
    with col_main:
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
    with col_note:
        st.info("💡 **비고 / 주의사항**")
        st.write(current_sched['note'])
        with st.expander("📝 비고 수정"):
            with st.form(f"edit_note_{sel_month}"):
                new_note = st.text_area("내용 수정", value=current_sched['note'])
                if st.form_submit_button("저장"):
                    st.session_state.schedule_db[sel_month]['note'] = new_note
                    st.rerun()

# Tab 7: 임상/처방 관리
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

# Tab 8: 발송 이력
with t8:
    st.header("📂 발송 이력 (History Archive)")
    if st.button("🔄 이력 새로고침"):
        st.rerun()
    
    history_df = load_history_data("history") # history 시트 로드
    
    if not history_df.empty:
        st.dataframe(history_df, use_container_width=True)
        csv = history_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 전체 이력 다운로드", csv, f"vpmi_history_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
    else:
        st.info("아직 저장된 이력이 없습니다.")

# [v.7.0] Tab 9: 생산 이력
with t9:
    st.header("🏭 생산 이력 (Production Archive)")
    
    # 1. 생산 기록 입력 폼
    with st.container(border=True):
        st.subheader("📝 생산 기록 입력")
        c1, c2, c3 = st.columns(3)
        
        p_date = c1.date_input("생산일", datetime.now(KST))
        p_type = c2.selectbox("종류", ["일반 식물 대사체", "무염김치", "커드(일반)", "계란 커드", "기타"])
        p_name = c3.text_input("원재료명 (예: 애기똥풀, 아카시아)")
        
        c4, c5, c6 = st.columns(3)
        p_weight = c4.number_input("원재료 무게 (kg)", 0.0, 1000.0, 1.0, step=0.1)
        p_ratio = c5.selectbox("배합 비율 (원물:액체)", ["1:4", "1:6", "1:8", "1:10", "1:12", "기타"])
        p_batch = c6.number_input("생산 수량 (통/개)", 1, 100, 1)
        
        # [자동 계산기]
        st.markdown("---")
        st.caption("🧪 **배합 시뮬레이션 (자동 계산)**")
        
        # 비율 파싱
        try:
            ratio_val = int(p_ratio.split(':')[1])
        except:
            ratio_val = 4 # 기본값
        
        total_liquid = p_weight * ratio_val
        
        # 정제수 100 : 조성액 3.5 : 올리고당 2.8 -> 총 106.3
        # 비율 계산
        base_unit = total_liquid / 106.3
        calc_water = base_unit * 100
        calc_vpmi = base_unit * 3.5
        calc_oligo = base_unit * 2.8
        
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("총 액체량", f"{total_liquid:.1f} kg")
        sc2.metric("💧 정제수", f"{calc_water:.2f} kg")
        sc3.metric("🧪 조성액(VPMI)", f"{calc_vpmi:.2f} kg")
        sc4.metric("🍯 올리고당", f"{calc_oligo:.2f} kg")
        
        p_note = st.text_input("비고 (특이사항, pH 등)")
        
        if st.button("💾 생산 기록 저장", type="primary"):
            # ["생산일", "종류", "원재료", "투입량(kg)", "비율", "스타터총량", "정제수", "조성액", "올리고당", "비고"]
            record = [
                p_date.strftime("%Y-%m-%d"),
                p_type,
                p_name,
                p_weight,
                p_ratio,
                f"{total_liquid:.2f}",
                f"{calc_water:.2f}",
                f"{calc_vpmi:.2f}",
                f"{calc_oligo:.2f}",
                p_note
            ]
            if save_production_record(record):
                st.success("생산 기록이 저장되었습니다!")

    st.divider()
    
    # 2. 이력 조회
    if st.button("🔄 생산 이력 새로고침"):
        st.rerun()
        
    prod_df = load_history_data("production") # production 시트 로드
    
    if not prod_df.empty:
        st.dataframe(prod_df, use_container_width=True)
        csv_prod = prod_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 생산 이력 다운로드", csv_prod, f"vpmi_production_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
    else:
        st.info("아직 저장된 생산 이력이 없습니다.")
