import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
import holidays
import uuid
import json

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
            st.title("🔒 엘랑비탈 ERP v.8.0")
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
            if round_val is None or str(round_val).strip() == "": round_num = 1 
            else:
                try: round_num = int(str(round_val).replace('회', '').replace('주', '').strip())
                except: round_num = 1

            start_date_str = str(row.get('시작일', '')).strip()

            db[name] = {
                "group": row.get('그룹', ''), "note": row.get('비고', ''),
                "default": True if str(row.get('기본발송', '')).upper() == 'O' else False,
                "items": items_list, "round": round_num, "start_date_raw": start_date_str
            }
        return db
    except Exception as e:
        return {}

def save_to_history(record_list):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("history")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="history", rows="1000", cols="10")
            sheet.append_row(["발송일", "이름", "그룹", "회차", "발송내역"])
        for record in record_list: sheet.append_row(record)
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

def save_production_record(record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("production")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="production", rows="1000", cols="12")
            sheet.append_row(["배치ID", "생산일", "종류", "원재료", "투입량(kg)", "비율", "스타터총량", "정제수", "조성액", "올리고당", "비고", "상태"])
        sheet.append_row(record)
        return True
    except Exception as e:
        st.error(f"생산 이력 저장 실패: {e}")
        return False

def save_ph_log(record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("ph_logs")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="ph_logs", rows="1000", cols="10")
            sheet.append_row(["배치ID", "측정일시", "pH", "온도", "비고"])
        sheet.append_row(record)
        return True
    except Exception as e:
        st.error(f"pH 기록 저장 실패: {e}")
        return False

# [v.8.0] 상태 업데이트 함수 강화 (커드 공정 추적용)
def update_production_status(batch_id, new_status, note_append=None):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("production")
        cell = sheet.find(batch_id)
        if cell:
            sheet.update_cell(cell.row, 12, new_status) # 상태 업데이트
            if note_append:
                current_note = sheet.cell(cell.row, 11).value # 비고란
                new_note = f"{current_note} | {note_append}" if current_note else note_append
                sheet.update_cell(cell.row, 11, new_note)
            return True
        return False
    except Exception as e:
        return False

def load_sheet_data(sheet_name):
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
        st.session_state.patient_db = loaded_db if loaded_db else {}

    if 'schedule_db' not in st.session_state:
        st.session_state.schedule_db = {
            1: {"title": "1월 (JAN)", "main": ["동백꽃", "인삼사이다", "유기농 우유 커드"], "note": "동백꽃 pH 3.8~4.0 도달 시 종료"},
            2: {"title": "2월 (FEB)", "main": ["갈대뿌리", "당근"], "note": "갈대뿌리 수율 약 37%"},
            3: {"title": "3월 (MAR)", "main": ["봄꽃 대사", "표고버섯"], "note": "꽃:줄기 1:1"},
            4: {"title": "4월 (APR)", "main": ["애기똥풀", "등나무꽃"], "note": "애기똥풀 전초"},
            5: {"title": "5월 (MAY)", "main": ["개망초+아카시아 합제", "아카시아꽃", "뽕잎"], "note": "계란커드 스타터용"},
            6: {"title": "6월 (JUN)", "main": ["매실", "개망초"], "note": "매실 씨 제거"},
            7: {"title": "7월 (JUL)", "main": ["토종홉 꽃", "연꽃", "무궁화"], "note": "여름철 대사 속도 주의"},
            8: {"title": "8월 (AUG)", "main": ["풋사과"], "note": "1:6 비율"},
            9: {"title": "9월 (SEP)", "main": ["청귤", "장미꽃"], "note": "추석 준비"},
            10: {"title": "10월 (OCT)", "main": ["송이버섯", "표고버섯", "산자나무"], "note": "송이 등외품"},
            11: {"title": "11월 (NOV)", "main": ["무염김치", "생지황", "인삼"], "note": "김장"},
            12: {"title": "12월 (DEC)", "main": ["동백꽃", "메주콩"], "note": "마감"}
        }

    if 'yearly_memos' not in st.session_state:
        st.session_state.yearly_memos = []

    if 'raw_material_list' not in st.session_state:
        priority_list = [
            "우유", "계란", "배추", "무", "마늘", "대파", "양파", "생강", "배", 
            "고춧가루", "찹쌀가루", "새우젓", "멸치액젓", "올리고당", "조성액", "EX", "정제수",
            "인삼", "동백꽃", "표고버섯", "개망초", "아카시아 꽃"
        ]
        full_list = [
            "개망초", "개망초잎", "개망초꽃", "개망초가루", "아카시아 꽃", "아카시아 잎", "아카시아 꽃/잎", 
            "애기똥풀 꽃", "애기똥풀 꽃/줄기", "동백꽃", "메주콩", "백태", "인삼", "수삼-5년근", "산양유", "우유", 
            "철원 산삼", "인삼vpl", "갈대뿌리", "당근", "표고버섯", "등나무꽃", "등나무줄기", "등나무꽃/줄기", 
            "개망초꽃8+아카시아잎1", "뽕잎", "뽕잎가루", "매실", "매실꽃", "매화꽃", "토종홉 꽃", "토종홉 꽃/잎", 
            "연꽃", "무궁화꽃", "무궁화잎", "무궁화꽃/잎", "풋사과", "청귤", "장미꽃", "송이버섯", 
            "산자나무열매", "싸리버섯", "무염김치", "생지황", "무염김칫물", "마늘", "대파", "부추", "저염김치", "유기농수삼",
            "명태머리", "굵은멸치", "흑새우", "다시마", "냉동블루베리", "슈가", "원당", "이소말토 올리고당", "프락토 올리고당",
            "고운 고춧가루", "굵은 고춧가루", "상황버섯", "영지버섯", "꽁치젓", "메가리젓", "어성초가루", "당두충가루"
        ]
        sorted_others = sorted(list(set(full_list) - set(priority_list)))
        st.session_state.raw_material_list = priority_list + sorted_others

    if 'product_list' not in st.session_state:
        plist = [
            "시원한 것", "마시는 것", "커드 시원한 것", "계란 커드", "EX",
            "철원산삼 대사체", "인삼대사체(PAGI) 항암용", "인삼대사체(PAGI) 뇌질환용",
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
        r_db["철원산삼 대사체"] = {"desc": "1:8 비율", "batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}}
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
st.title("🏥 엘랑비탈 ERP v.8.0 (Curd Lifecycle)")
col1, col2 = st.columns(2)

def calculate_round_v4(start_date_input, current_date_input, group_type):
    try:
        if not start_date_input or str(start_date_input) == 'nan': return 0, "날짜없음"
        start_date = pd.to_datetime(start_date_input).date()
        curr_date = current_date_input.date() if isinstance(current_date_input, datetime) else current_date_input
        delta = (curr_date - start_date).days
        if delta < 0: return 0, start_date.strftime('%Y-%m-%d')
        weeks_passed = round(delta / 7)
        r = weeks_passed + 1 if group_type == "매주 발송" else (weeks_passed // 2) + 1
        return r, start_date.strftime('%Y-%m-%d')
    except: return 1, "오류"

def on_date_change():
    if 'target_date' in st.session_state:
        st.session_state.view_month = st.session_state.target_date.month

kr_holidays = holidays.KR()
def check_delivery_date(date_obj):
    weekday = date_obj.weekday()
    if weekday == 4: return False, "⛔ **금요일 발송 금지**"
    if weekday >= 5: return False, "⛔ **주말 발송 불가**"
    if date_obj in kr_holidays: return False, f"⛔ **휴일({kr_holidays.get(date_obj)})**"
    next_day = date_obj + timedelta(days=1)
    if next_day in kr_holidays: return False, f"⛔ **익일 휴일**"
    return True, "✅ **발송 가능**"

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
    st.info(f"📅 **{target_date.year}년 {target_date.month}월 휴무일**")
    month_holidays = [f"• {d.day}일: {n}" for d, n in kr_holidays.items() if d.year == target_date.year and d.month == target_date.month]
    if month_holidays:
        for h in month_holidays: st.write(h)
    else: st.write("• 휴일 없음")

st.divider()

if st.button("🔄 데이터 새로고침"):
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
                info = f" ({r_num}/12회)" 
                if r_num > 12: info += " 🚨"
                if st.checkbox(f"{k}{info}", v.get('default'), help=f"시작: {s_date_disp}"): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r_num}
with c2:
    st.subheader("🚚 격주 발송")
    if db:
        for k, v in db.items():
            if v.get('group') in ["격주 발송", "유방암", "울산"]:
                r_num, s_date_disp = calculate_round_v4(v.get('start_date_raw'), target_date, "격주 발송")
                info = f" ({r_num}/6회)"
                if r_num > 6: info += " 🚨"
                if st.checkbox(f"{k}{info}", v.get('default'), help=f"시작: {s_date_disp}"): sel_p[k] = {'items': v['items'], 'group': v['group'], 'round': r_num}

st.divider()
t1, t2, t3, t4, t5, t6, t7, t8, t9, t10 = st.tabs(["🏷️ 라벨", "🎁 장연구원", "🧪 한책임", "📊 커드 수요량", f"🧀 커드 생산 관리", f"🗓️ 연간 일정 ({month_str})", "💊 임상/처방", "📂 발송 이력", "🏭 기타 생산 이력", "🔬 대사/pH 관리"])

# Tab 1~4 (기존 유지)
with t1:
    c_head, c_btn = st.columns([2, 1])
    with c_head: st.header("🖨️ 라벨 출력")
    with c_btn:
        if st.button("📝 발송 내역 저장"):
            if not sel_p: st.warning("선택된 환자 없음")
            else:
                records = []
                today_str = target_date.strftime('%Y-%m-%d')
                for p_name, p_data in sel_p.items():
                    content_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in p_data['items']])
                    records.append([today_str, p_name, p_data['group'], p_data['round'], content_str])
                if save_to_history(records): st.success("저장 완료!")
    
    if not sel_p: st.warning("환자를 선택하세요")
    else:
        cols = st.columns(2)
        for i, (name, data_info) in enumerate(sel_p.items()):
            with cols[i%2]:
                with st.container(border=True):
                    r_num = data_info['round']
                    st.markdown(f"### 🧊 {name} [{r_num}회차]")
                    st.caption(f"📅 {target_date.strftime('%Y-%m-%d')}")
                    st.markdown("---")
                    for x in data_info['items']:
                        chk = "✅" if "혼합" in str(x['제품']) else "□"
                        disp = x['제품'].replace(" 항암용", "")
                        vol = f" ({x['용량']})" if x.get('용량') else ""
                        st.markdown(f"**{chk} {disp}** {x['수량']}개{vol}")
                    st.markdown("---")
                    st.write("🏥 **엘랑비탈바이오**")

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
            if x['제품'] == "계란 커드" or x['제품'] == "커드": 
                curd_pure += x['수량']
            elif x['제품'] == "커드 시원한 것": 
                curd_cool += x['수량']
    
    need_from_cool = curd_cool * 40
    need_from_pure = curd_pure * 150
    total_kg = (need_from_cool + need_from_pure) / 1000
    milk = (total_kg / 9) * 16
    
    c1, c2 = st.columns(2)
    c1.metric("커드 시원한 것 (40g)", f"{curd_cool}개")
    c2.metric("계란 커드 (150g)", f"{curd_pure}개")
    st.divider()
    st.info(f"🧀 **총 필요 커드:** 약 {total_kg:.2f} kg")
    st.success(f"🥛 **필요 우유:** 약 {math.ceil(milk)}통")

# [v.8.0] Tab 5: 커드 생산 관리 (대사, 분리, 포장)
with t5:
    st.header(f"🧀 커드 생산 관리 ({week_str})")
    
    # 1. 생산 시작 (Mixing)
    with st.expander("🥛 **1단계: 배합 및 대사 시작 (Mixing)**", expanded=True):
        c_mix1, c_mix2 = st.columns(2)
        with c_mix1:
            batch_milk_vol = st.number_input("우유 투입 (통)", 1, 100, 30)
            target_product = st.radio("종류", ["계란 커드 (완제품)", "일반 커드 (중간재)"], horizontal=True)
        
        # 8L 유리병 계산 (2통 = 1병)
        jars_count = batch_milk_vol // 2
        milk_kg = batch_milk_vol * 2.3
        
        with c_mix2:
            st.metric("🍾 예상 유리병 수", f"{jars_count} 병")
            if target_product == "계란 커드 (완제품)":
                egg_kg = milk_kg / 4
                req_egg_cnt = int(egg_kg / 0.045)
                st.write(f"- 계란(깐 것): **{egg_kg:.1f} kg** (약 {req_egg_cnt}알)")
                
                # 스타터 계산
                st.markdown("**스타터 배합**")
                c_s1, c_s2 = st.columns(2)
                d_pct = c_s1.number_input("개망초/아카시아(%)", 0, 50, 20)
                c_pct = c_s2.number_input("시원한/마시는것(%)", 0, 50, 5)
                
                total_base = milk_kg + egg_kg
                s_d_kg = total_base * (d_pct/100)
                s_c_kg = total_base * (c_pct/100)
                st.caption(f"개망초: {s_d_kg:.1f}kg / 시원한: {s_c_kg:.1f}kg")
                if s_c_kg > 0: st.warning(f"❄️ 냉동 시원한 것 사용 시 올리고당 {s_c_kg*28:.0f}g 추가 후 하루 대사")

        if st.button("🚀 대사 시작 (항온실 입고)"):
            # 배치 상태 생성: JSON 형태의 문자열로 저장
            # {"total": 15, "meta": 15, "sep": 0, "fail": 0, "done": 0}
            status_json = json.dumps({"total": jars_count, "meta": jars_count, "sep": 0, "fail": 0, "done": 0})
            batch_id = f"{datetime.now(KST).strftime('%y%m%d')}-{target_product}-{uuid.uuid4().hex[:4]}"
            
            # DB 저장
            rec = [batch_id, datetime.now(KST).strftime("%Y-%m-%d"), target_product, "우유+스타터", f"{milk_kg:.1f}", "-", "-", "-", "-", "-", "커드생산", status_json]
            if save_production_record(rec):
                st.success(f"[{batch_id}] 대사 시작! 유리병 {jars_count}개 입고됨.")
                st.rerun()

    st.divider()

    # 2. 대사 관리 및 분리 (Process Control)
    st.subheader("🌡️ 2단계: 대사 관리 및 분리 (Metabolism & Separation)")
    if st.button("🔄 상태 새로고침"): st.rerun()
    
    prod_df = load_sheet_data("production")
    if not prod_df.empty:
        # 커드 관련 배치만 필터링 (상태에 JSON이 있는 것들)
        curd_df = prod_df[prod_df['종류'].str.contains("커드", na=False)]
        
        for idx, row in curd_df.iterrows():
            try:
                # 상태 JSON 파싱
                status = json.loads(row['상태'])
                if status.get('done') >= status.get('total'): continue # 완료된 건 스킵
            except: continue # JSON 아니면 스킵
            
            with st.container(border=True):
                c_info, c_action = st.columns([2, 3])
                with c_info:
                    st.markdown(f"**[{row['배치ID']}] {row['종류']}** ({row['생산일']})")
                    st.progress(1 - (status['meta'] / status['total']), text=f"진행률 (잔여 대사중: {status['meta']}병)")
                    st.write(f"🍾 총 {status['total']}병 | 🔥 대사중 {status['meta']} | 💧 분리중 {status['sep']} | 🗑️ 폐기 {status['fail']}")
                
                with c_action:
                    c_act1, c_act2 = st.columns(2)
                    # 대사 -> 분리 이동
                    if status['meta'] > 0:
                        move_sep = c_act1.number_input(f"분리실 이동 (병)", 0, status['meta'], 0, key=f"sep_{row['배치ID']}")
                        if c_act1.button("💧 분리 시작", key=f"btn_sep_{row['배치ID']}"):
                            status['meta'] -= move_sep
                            status['sep'] += move_sep
                            update_production_status(row['배치ID'], json.dumps(status))
                            st.rerun()
                            
                        # 대사 실패 (폐기)
                        fail_cnt = c_act2.number_input(f"망침/폐기 (병)", 0, status['meta'], 0, key=f"fail_{row['배치ID']}")
                        if c_act2.button("🗑️ 폐기 처리", key=f"btn_fail_{row['배치ID']}"):
                            status['meta'] -= fail_cnt
                            status['fail'] += fail_cnt
                            update_production_status(row['배치ID'], json.dumps(status))
                            st.rerun()
                    
                    # 분리 -> 포장 완료
                    if status['sep'] > 0:
                        st.markdown("---")
                        c_pack1, c_pack2 = st.columns(2)
                        pack_cnt = c_pack1.number_input(f"포장 완료 (병)", 0, status['sep'], 0, key=f"pack_{row['배치ID']}")
                        final_prod_cnt = c_pack2.number_input("생산된 소포장(150g) 개수", 0, 1000, 0, key=f"final_{row['배치ID']}")
                        
                        if st.button("🎁 포장 및 완료", key=f"btn_pack_{row['배치ID']}"):
                            status['sep'] -= pack_cnt
                            status['done'] += pack_cnt
                            # 완료 기록을 비고에 추가
                            note = f"완료({datetime.now(KST).strftime('%m/%d')}):{final_prod_cnt}개"
                            update_production_status(row['배치ID'], json.dumps(status), note)
                            st.success(f"{final_prod_cnt}개 생산 완료!")
                            st.rerun()

# Tab 6~10 (기존 유지)
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

with t8:
    st.header("📂 발송 이력")
    if st.button("🔄 이력 새로고침", key="ref_hist"): st.rerun()
    hist_df = load_sheet_data("history")
    if not hist_df.empty:
        st.dataframe(hist_df, use_container_width=True)
        csv = hist_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 다운로드", csv, f"history_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")

with t9:
    st.header("🏭 기타 생산 이력")
    with st.container(border=True):
        st.subheader("📝 생산 기록 입력")
        
        c1, c2, c3 = st.columns(3)
        p_date = c1.date_input("생산일", datetime.now(KST))
        p_type = c2.selectbox("종류", ["일반 식물 대사체", "무염김치", "철원산삼", "기타"])
        
        rm_list = st.session_state.raw_material_list + ["(직접 입력)"]
        p_name_sel = c3.selectbox("원재료명", rm_list)
        if p_name_sel == "(직접 입력)":
            p_name = c3.text_input("원재료명 직접 입력")
        else:
            p_name = p_name_sel
        
        c4, c5, c6 = st.columns(3)
        p_weight = c4.number_input("원재료 무게 (kg)", 0.0, 1000.0, 1.0, step=0.1)
        p_ratio = c5.selectbox("배합 비율", ["1:4", "1:6", "1:8", "1:10", "1:12", "기타"])
        p_note = c6.text_input("비고 (특이사항, pH 등)")

        try: r_val = int(p_ratio.split(':')[1])
        except: r_val = 4
        total = p_weight * r_val
        st.caption(f"🧪 일반 대사체 배합: 물 {total/106.3*100:.1f}kg, EX {total/106.3*3.5:.1f}kg, 당 {total/106.3*2.8:.1f}kg")

        if st.button("💾 생산 기록 저장"):
            batch_id = f"{p_date.strftime('%y%m%d')}-{p_name}-{uuid.uuid4().hex[:4]}"
            rec = [batch_id, p_date.strftime("%Y-%m-%d"), p_type, p_name, p_weight, p_ratio, f"{total:.1f}", 
                   f"{total/106.3*100:.1f}", f"{total/106.3*3.5:.1f}", f"{total/106.3*2.8:.1f}", p_note, "진행중"]

            if save_production_record(rec): st.success(f"[{batch_id}] 생산 등록 완료!")

    st.divider()
    if st.button("🔄 생산 이력 새로고침"): st.rerun()
    prod_df = load_sheet_data("production")
    if not prod_df.empty:
        st.dataframe(prod_df, use_container_width=True)

with t10:
    st.header("🔬 대사 관리 및 pH 측정")
    with st.container(border=True):
        st.subheader("📝 pH 측정 기록")
        c1, c2 = st.columns(2)
        ph_date = c1.date_input("측정일", datetime.now(KST), key="ph_date")
        ph_time = c2.time_input("측정시간", datetime.now(KST).time())
        
        prod_df = load_sheet_data("production")
        batch_options = ["(직접입력)"]
        if not prod_df.empty:
            ongoing = prod_df[prod_df['상태'] == '진행중']
            if not ongoing.empty:
                batch_options += ongoing.apply(lambda x: f"{x['배치ID']} ({x['원재료']})", axis=1).tolist()
            
        c3, c4 = st.columns(2)
        sel_batch = c3.selectbox("배치 선택", batch_options)
        ph_item = c4.text_input("제품명", value=sel_batch.split('(')[1][:-1] if '(' in sel_batch else "")
        
        c5, c6, c7 = st.columns(3)
        ph_val = c5.number_input("pH 값", 0.0, 14.0, 5.0, step=0.01)
        ph_temp = c6.number_input("온도 (℃)", 0.0, 50.0, 30.0)
        is_end = c7.checkbox("대사 종료")
        ph_memo = st.text_input("비고")
        
        if st.button("💾 pH 저장"):
            batch_id_val = sel_batch.split(' ')[0] if '(' in sel_batch else "DIRECT"
            dt_str = f"{ph_date.strftime('%Y-%m-%d')} {ph_time.strftime('%H:%M')}"
            save_ph_log([batch_id_val, dt_str, ph_val, ph_temp, ph_memo])
            if is_end and batch_id_val != "DIRECT":
                update_production_status(batch_id_val, "완료")
                st.success("대사 종료 처리됨!")
            else:
                st.success("저장됨!")

    if st.button("🔄 pH 기록 새로고침"): st.rerun()
    ph_df = load_sheet_data("ph_logs")
    if not ph_df.empty:
        st.dataframe(ph_df, use_container_width=True)
