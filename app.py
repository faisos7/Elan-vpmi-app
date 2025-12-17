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
st.set_page_config(page_title="엘랑비탈 ERP v.0.9.8", page_icon="🏥", layout="wide")

# [중요] 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))

# [v.0.9.8] 수율 관리 상수 정의
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,  # 우유 1통(2.3L)당 예상 커드 0.5kg
    "PACK_UNIT_KG": 0.15,           # 소포장 단위 150g
    "DRINK_RATIO": 6.5              # 일반커드 -> 커드시원한것 희석 배수
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
            st.title("🔒 엘랑비탈 ERP v.0.9.8")
            st.markdown("---")
            with st.form("login"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

# ==============================================================================
# 3. 구글 시트 연동 함수 (Gspread)
# ==============================================================================
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
        
        for record in reversed(record_list):
            sheet.insert_row(record, 2)
            
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

def save_production_record(sheet_name, record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet(sheet_name)
        except:
            sheet = client.open("vpmi_data").add_worksheet(title=sheet_name, rows="1000", cols="10")
            sheet.append_row(["배치ID", "생산일", "종류", "원재료", "투입량(kg)", "비율", "완성(개)", "폐기(병)", "비고", "상태"])
        
        sheet.insert_row(record, 2)
        return True
    except Exception as e:
        st.error(f"생산 이력 저장 실패 ({sheet_name}): {e}")
        return False

# [v.0.9.8] 수율/손실 기록 저장 함수
def save_yield_log(record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("yield_logs")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="yield_logs", rows="1000", cols="10")
            sheet.append_row(["기록일시", "생산모드", "투입(통)", "예상(kg)", "실제(kg)", "손실률(%)", "비고"])
        
        sheet.insert_row(record, 2)
        return True
    except Exception as e:
        st.error(f"수율 기록 저장 실패: {e}")
        return False

def save_ph_log(record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("ph_logs")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="ph_logs", rows="1000", cols="10")
            sheet.append_row(["배치ID", "측정일시", "pH", "온도", "비고"])
            
        sheet.insert_row(record, 2)
        return True
    except Exception as e:
        st.error(f"pH 기록 저장 실패: {e}")
        return False

def update_production_status(sheet_name, batch_id, new_status, add_done=0, add_fail=0):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        cell = sheet.find(batch_id)
        if cell:
            sheet.update_cell(cell.row, 10, new_status)
            if add_done > 0:
                current_done = sheet.cell(cell.row, 7).value
                try: current_done = int(current_done)
                except: current_done = 0
                sheet.update_cell(cell.row, 7, current_done + add_done)
                current_note = sheet.cell(cell.row, 9).value
                log_msg = f"[{datetime.now(KST).strftime('%m/%d')}]+{add_done}"
                new_note = f"{current_note}, {log_msg}" if current_note else log_msg
                sheet.update_cell(cell.row, 9, new_note)
            if add_fail > 0:
                current_fail = sheet.cell(cell.row, 8).value
                try: current_fail = int(current_fail)
                except: current_fail = 0
                sheet.update_cell(cell.row, 8, current_fail + add_fail)
            return True
        return False
    except Exception as e:
        return False

@st.cache_data(ttl=60)
def load_sheet_data(sheet_name, sort_col=None):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet(sheet_name)
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and sort_col and sort_col in df.columns:
            try: df = df.sort_values(by=sort_col, ascending=False)
            except: pass
        return df
    except:
        return pd.DataFrame()

# ==============================================================================
# 4. 데이터 초기화 및 세션 상태
# ==============================================================================
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

    if 'recipe_db' not in st.session_state:
        r_db = {}
        r_db["계란커드 스타터 [혼합]"] = {"desc": "대사체 단순 혼합", "batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}}
        r_db["계란커드 스타터 [합제]"] = {"desc": "원물 8:1 혼합 대사", "batch_size": 9, "materials": {"개망초꽃(원물)": 8, "아카시아잎(원물)": 1, "EX": 36}}
        r_db["철원산삼 대사체"] = {"desc": "1:8 비율", "batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}}
        r_db["혼합 [E.R.P.V.P]"] = {"desc": "다종 혼합 (1:1:1:1:1)", "batch_size": 5, "materials": {"애기똥풀 대사체": 1, "장미꽃 대사체": 1, "인삼대사체(PAGI) 항암용": 1, "송이 대사체": 1, "표고버섯 대사체": 1}}
        r_db["혼합 [P.V.E]"] = {"desc": "PAGI/표고/EX 기본", "batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 3, "표고버섯 대사체": 2, "EX": 5}}
        r_db["혼합 [P.P.E]"] = {"desc": "PAGI/PAGI뇌/EX", "batch_size": 10, "materials": {"인삼대사체(PAGI) 항암용": 4, "인삼대사체(PAGI) 뇌질환용": 1, "EX": 5}}
        r_db["혼합 [Ex.P]"] = {"desc": "EX 기반 희석", "batch_size": 10, "materials": {"EX": 8, "인삼대사체(PAGI) 항암용": 2}}
        r_db["혼합 [R.P]"] = {"desc": "장미/PAGI 혼합", "batch_size": 4, "materials": {"장미꽃 대사체": 3, "인삼대사체(PAGI) 항암용": 1}}
        r_db["혼합 [Edf.P]"] = {"desc": "개망초/PAGI 혼합", "batch_size": 4, "materials": {"개망초(EDF)": 3, "인삼대사체(PAGI) 항암용": 1}}
        r_db["혼합 [P.P]"] = {"desc": "PAGI 기본", "batch_size": 1, "materials": {"인삼대사체(PAGI) 항암용": 1}}
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

# 5. 메인 화면 구성
st.sidebar.title("📌 메뉴 선택")
app_mode = st.sidebar.radio("작업 모드를 선택하세요", ["🚛 배송/주문 관리", "🏭 생산/공정 관리"])

st.title(f"🏥 엘랑비탈 ERP v.0.9.8 ({app_mode})")

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

kr_holidays = holidays.KR()
def check_delivery_date(date_obj):
    weekday = date_obj.weekday()
    if weekday == 4: return False, "⛔ **금요일 발송 금지**"
    if weekday >= 5: return False, "⛔ **주말 발송 불가**"
    if date_obj in kr_holidays: return False, f"⛔ **휴일({kr_holidays.get(date_obj)})**"
    next_day = date_obj + timedelta(days=1)
    if next_day in kr_holidays: return False, f"⛔ **익일 휴일**"
    return True, "✅ **발송 가능**"

# ==============================================================================
# [MODE 1] 배송/주문 관리
# ==============================================================================
if app_mode == "🚛 배송/주문 관리":
    col1, col2 = st.columns(2)
    def on_date_change():
        if 'target_date' in st.session_state:
            st.session_state.view_month = st.session_state.target_date.month

    with col1: 
        target_date = st.date_input("발송일", value=datetime.now(KST), key="target_date", on_change=on_date_change)
        is_ok, msg = check_delivery_date(target_date)
        if is_ok: st.success(msg)
        else: st.error(msg)

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
    
    t1, t2, t3, t4, t5 = st.tabs(["📦 개인별 포장", "📊 제품별 총합", "🧪 혼합 제조", "📊 커드 수요량", "📂 발송 이력"])

    # Tab 1: 라벨
    with t1:
        c_head, c_btn = st.columns([2, 1])
        with c_head: st.header("📦 개인별 포장 목록 (라벨)")
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

    # Tab 2: 장연구원
    with t2:
        st.header("📊 제품별 총합 (개별 포장)")
        tot = {}
        for data_info in sel_p.values():
            items = data_info['items']
            for x in items:
                if "혼합" not in str(x['제품']):
                    k = f"{x['제품']} {x['용량']}" if x.get('용량') else x['제품']
                    tot[k] = tot.get(k, 0) + x['수량']
        df = pd.DataFrame(list(tot.items()), columns=["제품", "수량"]).sort_values("수량", ascending=False)
        st.dataframe(df, use_container_width=True)

    # Tab 3: 한책임
    with t3:
        st.header("🧪 혼합 제조 (Batch Mixing)")
        req = {}
        for data_info in sel_p.values():
            items = data_info['items']
            for x in items:
                if "혼합" in str(x['제품']): req[x['제품']] = req.get(x['제품'], 0) + x['수량']
        
        recipes = st.session_state.recipe_db
        total_mat = {}
        
        if not req: st.info("혼합 제품 주문이 없습니다.")
        else:
            for p, q in req.items():
                if p in recipes:
                    with st.expander(f"📌 {p} (총 {q}개)", expanded=True):
                        c1, c2 = st.columns([1,2])
                        in_q = c1.number_input(f"{p} 제조 수량", 0, value=q, key=f"{p}_{q}")
                        r = recipes[p]
                        c2.markdown(f"**{r['desc']}**")
                        
                        ratio = in_q / r['batch_size'] if r['batch_size'] > 1 else in_q
                        
                        for m, mq in r['materials'].items():
                            if isinstance(mq, (int, float)):
                                calc = mq * ratio
                                if "(50ml)" in m or "대사체" in m:
                                    vol = calc * 50
                                    c2.write(f"- {m}: **{calc:.1f}** (50*{calc:.1f}={vol:.0f} ml)")
                                elif "EX" in m or "사이다" in m:
                                    c2.write(f"- {m}: **{calc:.0f} ml**")
                                else:
                                    c2.write(f"- {m}: **{calc:.1f} 개**")
                                total_mat[m] = total_mat.get(m, 0) + calc
                            else: c2.write(f"- {m}: {mq}")
            
            st.divider()
            st.subheader("∑ 원료 총 필요량")
            for k, v in sorted(total_mat.items(), key=lambda x: x[1], reverse=True):
                if "PAGI" in k or "인삼대사체" in k or "송이" in k or "장미" in k or "개망초" in k or "EDF" in k or "대사체" in k:
                    vol_ml = v * 50
                    st.info(f"💧 **{k}**: {v:.1f}개 (총 {vol_ml:,.0f} ml)")
                elif "사이다" in k:
                    bottles = v / 300
                    st.info(f"🥤 **{k}**: {v:,.0f} ml (약 {bottles:.1f}병)")
                elif "EX" in k:
                    st.info(f"🛢️ **{k}**: {v:,.0f} ml (약 {v/1000:.1f} L)")
                else:
                    st.success(f"📦 **{k}**: {v:.1f} 개")

    # Tab 4: 커드 수요량
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

    # Tab 5: 발송 이력
    with t5:
        st.header("📂 발송 이력 (Shipping Log)")
        if st.button("🔄 이력 새로고침", key="ref_hist_prod"): st.rerun()
        hist_df = load_sheet_data("history", "발송일")
        if not hist_df.empty:
            st.dataframe(hist_df, use_container_width=True)
            csv = hist_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 다운로드", csv, f"history.csv", "text/csv")

# ==============================================================================
# [MODE 2] 생산/공정 관리
# ==============================================================================
elif app_mode == "🏭 생산/공정 관리":
    
    # [v.0.9.8] '수율/예측' 탭 추가
    t_yield, t6, t7, t8, t9, t10 = st.tabs(["📊 수율/예측", "🧀 커드 생산 관리", "🗓️ 연간 일정", "💊 임상/처방", "🏭 기타 생산 이력", "🔬 대사/pH 관리"])

    # [NEW] Tab Yield: 생산량 예측 및 수율 관리
    with t_yield:
        st.header("📊 생산량 예측 및 수율 관리 (Yield Manager)")
        st.info("💡 우유 투입량에 따른 **예상 결과**를 확인하고, 실제 생산 후 **손실률(Loss)**을 기록하세요.")

        col_pred, col_record = st.columns([1, 1])

        # 1. 생산 예측 (Calculator)
        with col_pred:
            with st.container(border=True):
                st.subheader("1. 생산 예측 (Calculator)")
                
                # 입력 (수정됨: 제품명 간소화)
                y_bottles = st.number_input("🥛 우유 투입 (통/Bottle)", min_value=0, value=10, step=1, key="y_bottles")
                y_mode = st.radio("생산 제품 선택", ["계란커드", "일반커드"], key="y_mode")
                
                # 계산
                y_expected_kg = y_bottles * YIELD_CONSTANTS["MILK_BOTTLE_TO_CURD_KG"]
                
                st.markdown("---")
                st.markdown(f"**📉 총 예상 커드 무게: :blue[{y_expected_kg:.1f} kg]**")
                
                # 출력 로직 수정
                if y_mode == "계란커드":
                    y_packs = int(y_expected_kg / YIELD_CONSTANTS["PACK_UNIT_KG"])
                    y_rem = (y_expected_kg % YIELD_CONSTANTS["PACK_UNIT_KG"]) * 1000
                    st.success(f"📦 예상 포장: **{y_packs} 팩**")
                    st.caption(f"└ 자투리 잔여: {y_rem:.0f} g")
                else:
                    y_drink = y_expected_kg * YIELD_CONSTANTS["DRINK_RATIO"]
                    st.success(f"🥤 커드시원한것 환산: **{y_drink:.1f} kg**") # 수정됨
                    st.caption(f"└ 희석비 1:{YIELD_CONSTANTS['DRINK_RATIO']-1} 적용 시")

        # 2. 수율 기록 (Actual Record)
        with col_record:
            with st.container(border=True):
                st.subheader("2. 작업 완료 및 수율 체크")
                
                y_actual = st.number_input("⚖️ 실제 생산된 커드 무게 (kg)", min_value=0.0, format="%.2f", key="y_actual")
                y_note = st.text_input("비고 (특이사항)", key="y_note")
                
                if y_actual > 0:
                    loss_kg = y_expected_kg - y_actual
                    loss_rate = (loss_kg / y_expected_kg * 100) if y_expected_kg > 0 else 0
                    
                    st.markdown("---")
                    if loss_rate > 10:
                        st.error(f"🚨 손실률: {loss_rate:.1f}% (주의 필요)")
                    elif loss_rate < 0:
                        st.warning(f"❓ 수율 오버: {abs(loss_rate):.1f}% (예상보다 무거움)")
                    else:
                        st.success(f"✅ 손실률: {loss_rate:.1f}% (양호)")
                    
                    if st.button("💾 수율 기록 저장"):
                        now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
                        # 모드명은 이미 간소화되었으므로 그대로 사용
                        rec = [now_str, y_mode, y_bottles, y_expected_kg, y_actual, round(loss_rate, 2), y_note]
                        
                        if save_yield_log(rec):
                            st.success("수율 데이터 저장 완료!")
                        else:
                            st.error("저장 실패")
                
        # 기록 표시
        st.divider()
        st.subheader("📋 최근 수율 기록")
        if st.button("🔄 기록 새로고침", key="ref_yield"): st.rerun()
        y_df = load_sheet_data("yield_logs", "기록일시")
        if not y_df.empty:
            st.dataframe(y_df, use_container_width=True)

    # Tab 6: 커드 생산 관리 (기존 유지)
    with t6:
        st.header(f"🧀 커드 생산 관리")
        
        # 1. 생산 시작 (Mixing)
        with st.expander("🥛 **1단계: 배합 및 대사 시작 (Mixing)**", expanded=True):
            st.markdown("##### 🥛 우유 투입량 설정")
            
            calc_mode = st.radio("계산 모드 선택", ["🥛 우유 투입량 기준 (정방향)", "🫙 용기 용량 기준 (역방향/맞춤)"], horizontal=True)
            
            c_u1, c_u2 = st.columns(2)
            
            if "우유 투입량" in calc_mode:
                with c_u1:
                    milk_unit = st.radio("우유 단위", ["통 (2.3kg 기준)", "kg (직접 입력)"], horizontal=True)
                
                with c_u2:
                    if "통" in milk_unit:
                        batch_milk_vol = st.number_input("우유 개수 (통)", 1, 200, 30)
                        milk_kg = batch_milk_vol * 2.3
                        jars_count = int(batch_milk_vol // 2)
                    else:
                        milk_kg = st.number_input("우유 무게 (kg)", 1.0, 500.0, 69.0, step=0.1)
                        jars_count = st.number_input("사용 용기 수 (개)", 1, 100, 1, help="비규격 용기일 경우 실제 사용한 용기 갯수를 입력하세요.")
                        
            else:
                with c_u1:
                    target_vol_l = st.number_input("용기 1개당 용량 (L)", 1.0, 100.0, 7.0, step=0.5, help="사용할 용기의 크기를 입력하세요.")
                    jars_count = st.number_input("작업할 용기 수 (개)", 1, 100, 1)
                
                with c_u2:
                    st.info(f"💡 {target_vol_l}L 용기 {jars_count}개를 채우기 위한 레시피를 계산합니다.")
                    target_total_weight = target_vol_l * 0.9 * jars_count

            st.markdown("---")
            c_mix1, c_mix2 = st.columns(2)
            with c_mix1:
                target_product = st.radio("종류", ["계란 커드 (완제품)", "일반 커드 (중간재)"], horizontal=True)
            
            with c_mix2:
                if "우유 투입량" in calc_mode:
                    if target_product == "계란 커드 (완제품)":
                        egg_kg = milk_kg / 4
                        total_base = milk_kg + egg_kg
                    else:
                        total_base = milk_kg
                else:
                    temp_d_pct = 20
                    temp_c_pct = 5
                    temp_starter_ratio = (temp_d_pct + temp_c_pct) / 100
                    
                    if target_product == "계란 커드 (완제품)":
                        pass

                st.metric("🫙 작업 용기 수", f"{jars_count} 개")

                st.markdown("**🧪 스타터 배합 (Total %)**")
                c_s1, c_s2 = st.columns(2)
                d_pct = c_s1.number_input("개망아카(%)", 0, 50, 20)
                c_pct = c_s2.number_input("시원한/마시는것(%)", 0, 50, 5)
                
                starter_ratio = (d_pct + c_pct) / 100
                
                if "우유 투입량" in calc_mode:
                    if target_product == "계란 커드 (완제품)":
                        egg_kg = milk_kg / 4
                        req_egg_cnt = int(egg_kg / 0.045)
                        total_base = milk_kg + egg_kg
                    else:
                        total_base = milk_kg
                else:
                    total_base = target_total_weight / (1 + starter_ratio)
                    
                    if target_product == "계란 커드 (완제품)":
                        milk_kg = total_base * 0.8
                        egg_kg = total_base * 0.2
                        req_egg_cnt = int(egg_kg / 0.045)
                    else:
                        milk_kg = total_base
                        
                s_d_kg = total_base * (d_pct/100)
                s_c_kg = total_base * (c_pct/100)
                req_daisy = s_d_kg * (8/9)
                req_acacia = s_d_kg * (1/9)
                
                total_mix_weight = total_base + s_d_kg + s_c_kg
                per_jar = total_mix_weight / jars_count if jars_count > 0 else 0

                st.markdown("##### 🥛 주원료 (Base)")
                c_base1, c_base2 = st.columns(2)
                c_base1.metric("🥛 우유", f"{milk_kg:.2f} kg")
                
                if target_product == "계란 커드 (완제품)":
                     c_base2.metric("🥚 계란 (깐 것)", f"{egg_kg:.2f} kg", f"약 {req_egg_cnt}알")
                
                st.markdown("---")
                
                st.warning(f"⚖️ **총 배합 중량 (대사 전): {total_mix_weight:.2f} kg** (한 병당 약 {per_jar:.2f} kg)")
                
                with st.container(border=True):
                    st.markdown("##### 🧪 스타터 배합 지시서")
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("개망초(8)", f"{req_daisy:.2f} kg")
                    cc2.metric("아카시아(1)", f"{req_acacia:.2f} kg")
                    cc3.metric("시원한 것", f"{s_c_kg:.2f} kg")
                        
                if s_c_kg > 0: st.warning(f"❄️ 냉동 시원한 것 사용 시 올리고당 {s_c_kg*28:.0f}g 추가 후 하루 대사")

            if st.button("🚀 대사 시작 (항온실 입고)"):
                ratio_str = f"개망아카{d_pct}%/시원{c_pct}%" if target_product == "계란 커드 (완제품)" else "일반 15%"
                status_json = json.dumps({"total": jars_count, "meta": jars_count, "sep": 0, "fail": 0, "done": 0})
                batch_id = f"{datetime.now(KST).strftime('%y%m%d')}-{target_product}-{uuid.uuid4().hex[:4]}"
                
                rec = [batch_id, datetime.now(KST).strftime("%Y-%m-%d"), target_product, "우유+스타터", f"{milk_kg:.1f}", ratio_str, 0, 0, "커드생산", status_json]
                
                if save_production_record("curd_prod", rec):
                    st.cache_data.clear()
                    st.success(f"[{batch_id}] 대사 시작! 유리병 {jars_count}개 입고됨.")
                    st.rerun()

        st.divider()

        # 2. 대사 관리
        st.subheader("🌡️ 2단계: 대사 관리 및 분리 (Metabolism & Separation)")
        if st.button("🔄 상태 새로고침"): st.rerun()
        
        prod_df = load_sheet_data("curd_prod", "생산일")
        
        if not prod_df.empty:
            for idx, row in prod_df.iterrows():
                try:
                    status = json.loads(row['상태'])
                    if status.get('meta', 0) == 0 and status.get('sep', 0) == 0: continue
                except: continue
                
                with st.container(border=True):
                    c_info, c_action = st.columns([2, 3])
                    with c_info:
                        st.markdown(f"**[{row['배치ID']}] {row['종류']}** ({row['생산일']})")
                        st.progress(1 - (status['meta'] / status['total']), text=f"진행률 (잔여 대사중: {status['meta']}병)")
                        st.write(f"🫙 총 {status['total']} | 🔥 대사중 {status['meta']} | 💧 분리중 {status['sep']} | 🗑️ 폐기 {status['fail']}")
                    
                    with c_action:
                        with st.form(key=f"form_{row['배치ID']}"):
                            c_act1, c_act2 = st.columns(2)
                            move_sep = 0
                            fail_cnt = 0
                            pack_cnt = 0
                            final_prod_cnt = 0

                            if status['meta'] > 0:
                                move_sep = c_act1.number_input(f"분리실 이동 (병)", 0, status['meta'], 0, key=f"sep_{row['배치ID']}")
                                fail_cnt = c_act2.number_input(f"망침/폐기 (병)", 0, status['meta'], 0, key=f"fail_{row['배치ID']}")
                            
                            if status['sep'] > 0:
                                st.markdown("---")
                                pack_cnt = st.number_input(f"포장 완료 (병)", 0, status['sep'], 0, key=f"pack_{row['배치ID']}")
                                final_prod_cnt = st.number_input("금일 생산된 소포장(150g) 개수 (추가)", 0, 1000, 0, key=f"final_{row['배치ID']}")

                            if st.form_submit_button("상태 및 결과 업데이트"):
                                updated = False
                                if move_sep > 0:
                                    status['meta'] -= move_sep
                                    status['sep'] += move_sep
                                    updated = True
                                if fail_cnt > 0:
                                    status['meta'] -= fail_cnt
                                    status['fail'] += fail_cnt
                                    updated = True
                                if pack_cnt > 0:
                                    status['sep'] -= pack_cnt
                                    status['done'] += pack_cnt
                                    updated = True
                                
                                if updated:
                                    update_production_status("curd_prod", row['배치ID'], json.dumps(status), final_prod_cnt, fail_cnt)
                                    st.cache_data.clear()
                                    st.success("업데이트 완료!")
                                    st.rerun()

    # Tab 7: 연간 일정
    with t7:
        st.header(f"🗓️ 연간 생산 캘린더")
        sel_month = st.selectbox("월 선택", list(range(1, 13)), index=datetime.now(KST).month-1)
        current_sched = st.session_state.schedule_db[sel_month]
        with st.container(border=True):
            st.subheader("📝 연간 주요 메모")
            c_memo, c_m_tool = st.columns([2, 1])
            with c_memo:
                if not st.session_state.yearly_memos: st.info("등록된 메모 없음")
                else: 
                    for memo in st.session_state.yearly_memos: st.warning(f"📌 {memo}")
            with c_m_tool:
                with st.popover("메모 관리"):
                    new_memo = st.text_input("새 메모")
                    if st.button("추가"):
                        if new_memo: st.session_state.yearly_memos.append(new_memo); st.rerun()
                    del_memo = st.multiselect("삭제할 메모", st.session_state.yearly_memos)
                    if st.button("삭제"):
                        for d in del_memo: st.session_state.yearly_memos.remove(d)
                        st.rerun()
        st.divider()
        st.subheader(f"📅 {current_sched['title']}")
        st.success("🌱 **주요 생산 품목**")
        for item in current_sched['main']: st.write(f"- {item}")
        st.info(f"💡 {current_sched['note']}")

    # Tab 8: 임상/처방
    with t8:
        st.header("💊 환자별 맞춤 처방 관리")
        regimen_names = list(st.session_state.regimen_db.keys())
        selected_regimen = st.selectbox("처방전 선택", regimen_names + ["(신규 처방 등록)"])
        if selected_regimen == "(신규 처방 등록)":
            with st.form("new_regimen_form"):
                new_reg_name = st.text_input("처방명")
                new_reg_content = st.text_area("처방 내용")
                if st.form_submit_button("등록"):
                    if new_reg_name: st.session_state.regimen_db[new_reg_name] = new_reg_content; st.rerun()
        else:
            st.info(f"📋 **{selected_regimen}**")
            st.text_area("처방 내용", value=st.session_state.regimen_db[selected_regimen], height=200, disabled=True)
            with st.expander("✏️ 내용 수정"):
                with st.form("edit_regimen_form"):
                    updated_content = st.text_area("내용 수정", value=st.session_state.regimen_db[selected_regimen])
                    if st.form_submit_button("수정 저장"):
                        st.session_state.regimen_db[selected_regimen] = updated_content; st.rerun()

    # Tab 9: 기타 생산 이력
    with t9:
        st.header("🏭 기타 생산 이력")
        with st.container(border=True):
            st.subheader("📝 생산 기록 입력")
            
            c1, c2, c3 = st.columns(3)
            p_date = c1.date_input("생산일", datetime.now(KST))
            p_type = c2.selectbox("종류", ["저염김치(0.3%)", "무염김치(0%)", "일반 식물 대사체", "철원산삼", "기타"])
            
            rm_list = st.session_state.raw_material_list + ["(직접 입력)"]
            p_name_sel = c3.selectbox("원재료명", rm_list)
            p_name = c3.text_input("직접 입력") if p_name_sel == "(직접 입력)" else p_name_sel
            
            c4, c5, c6 = st.columns(3)
            p_weight = c4.number_input("원재료 무게 (kg)", 0.0, 1000.0, 100.0 if "김치" in p_type else 1.0, step=0.1)
            p_ratio = c5.selectbox("배합 비율", ["저염김치(배추10:속6)", "1:4", "1:6", "1:8", "1:10", "1:12", "기타"])
            p_note = c6.text_input("비고 (특이사항, pH 등)")

            if p_type == "저염김치(0.3%)":
                st.info(f"🥬 **저염김치 배합 (배추 {p_weight}kg)**")
                ratio = p_weight / 100 
                rc1, rc2, rc3 = st.columns(3)
                rc1.write(f"물 {20*ratio:.1f}, 찹쌀죽 {16*ratio:.1f}")
                rc2.write(f"고춧가루 {9*ratio:.1f}, 젓갈 {4*ratio:.1f}")
                rc3.write(f"**조성액 {7.6*ratio:.2f}**, 당류 {3.8*ratio:.1f}")
                st.success(f"👉 총 김치소: {60*ratio:.1f}kg")

            if st.button("💾 생산 기록 저장", key="btn_save_prod"):
                batch_id = f"{p_date.strftime('%y%m%d')}-{p_name}-{uuid.uuid4().hex[:4]}"
                rec = [batch_id, p_date.strftime("%Y-%m-%d"), p_type, p_name, p_weight, p_ratio, 0, 0, p_note, "진행중"]
                if save_production_record("other_prod", rec): 
                    st.cache_data.clear()
                    st.success("저장 완료!")
                    st.rerun()

        if st.button("🔄 이력 새로고침"): st.rerun()
        prod_df = load_sheet_data("other_prod", "생산일")
        if not prod_df.empty: st.dataframe(prod_df, use_container_width=True)

    # Tab 10: 대사/pH 관리
    with t10:
        st.header("🔬 대사 관리 및 pH 측정")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            ph_date = c1.date_input("측정일", datetime.now(KST), key="ph_date")
            ph_time = c2.time_input("측정시간", datetime.now(KST).time())
            
            curd_df = load_sheet_data("curd_prod")
            other_df = load_sheet_data("other_prod")
            
            batch_options = ["(직접입력)"]
            active_batches = []
            
            if not curd_df.empty:
                for idx, row in curd_df.iterrows():
                    try:
                        status = json.loads(row['상태'])
                        if status.get('meta', 0) > 0:
                             active_batches.append(f"{row['배치ID']} (커드)")
                    except: pass
            
            if not other_df.empty:
                ongoing = other_df[other_df['상태'] == '진행중']
                if not ongoing.empty:
                    active_batches += ongoing.apply(lambda x: f"{x['배치ID']} ({x['원재료']})", axis=1).tolist()
            
            batch_options += active_batches
                
            c3, c4 = st.columns(2)
            sel_batch = c3.selectbox("진행 중인 배치 선택", batch_options)
            
            if '(' in sel_batch and sel_batch != "(직접입력)":
                batch_id_val = sel_batch.rsplit(' (', 1)[0]
            else:
                batch_id_val = ""
            
            ph_item = c4.text_input("제품명 (자동/수동)", value=batch_id_val if batch_id_val else "")
            
            c5, c6, c7 = st.columns(3)
            ph_val = c5.number_input("pH 값", 0.0, 14.0, 5.0, step=0.01)
            ph_temp = c6.number_input("온도 (℃)", 0.0, 50.0, 30.0)
            is_end = c7.checkbox("대사 종료 (완료 처리)")
            ph_memo = st.text_input("비고")
            
            if st.button("💾 pH 저장"):
                final_batch_id = batch_id_val if batch_id_val else "DIRECT"
                dt_str = f"{ph_date.strftime('%Y-%m-%d')} {ph_time.strftime('%H:%M')}"
                
                save_ph_log([final_batch_id, dt_str, ph_val, ph_temp, ph_memo])
                
                if is_end and final_batch_id != "DIRECT":
                    if "커드" in sel_batch:
                        st.warning("커드 배치는 [커드 생산 관리] 탭에서 단계별(분리/폐기)로 처리해주세요.")
                    else:
                        update_production_status("other_prod", final_batch_id, "완료")
                        st.cache_data.clear()
                        st.success("기타 생산 대사 종료 처리됨!")
                else: 
                    st.success("저장됨!")

        if st.button("🔄 pH 새로고침"): st.rerun()
        ph_df = load_sheet_data("ph_logs", "측정일시")
        if not ph_df.empty: st.dataframe(ph_df, use_container_width=True)
