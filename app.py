import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
import holidays
import uuid
import json
import io

# ==============================================================================
# 1. 시스템 설정 및 상수 (Config)
# ==============================================================================
st.set_page_config(page_title="엘랑비탈 ERP v.1.0.0", page_icon="🏥", layout="wide")

# [중요] 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))

# 수율 관리 상수 정의
YIELD_CONSTANTS = {
    "MILK_BOTTLE_TO_CURD_KG": 0.5,
    "PACK_UNIT_KG": 0.15,
    "DRINK_RATIO": 6.5
}

# ==============================================================================
# 2. 재고 관리 및 대시보드 함수
# ==============================================================================
def update_inventory(item_name, change_qty):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("inventory")
        cell = sheet.find(item_name)
        if cell:
            current_val = sheet.cell(cell.row, 2).value
            current_val = float(current_val) if current_val else 0.0
            new_val = current_val + change_qty
            sheet.update_cell(cell.row, 2, new_val)
            sheet.update_cell(cell.row, 4, datetime.now(KST).strftime("%Y-%m-%d %H:%M"))
            return True
        return False
    except:
        return False

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
                    st.error(f"🚨 **재고 부족 알림**: {row['항목명']} ({row['현재고']} {row['단위']} 남음)")
            with st.expander("📦 실시간 재고 현황판 (클릭하여 열기)"):
                st.dataframe(df_inv, use_container_width=True)
    except:
        pass

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
            st.title("🔒 엘랑비탈 ERP v.1.0.0")
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
# 4. 데이터 초기화 및 세션 상태
# ==============================================================================
def init_session_state():
    if 'target_date' not in st.session_state:
        st.session_state.target_date = datetime.now(KST)
    if 'view_month' not in st.session_state:
        st.session_state.view_month = st.session_state.target_date.month
    if 'patient_db' not in st.session_state:
        st.session_state.patient_db = load_data_from_sheet()
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
    if 'yearly_memos' not in st.session_state: st.session_state.yearly_memos = []
    if 'raw_material_list' not in st.session_state:
        priority_list = ["우유", "계란", "배추", "무", "마늘", "대파", "양파", "생강", "배", "고춧가루", "찹쌀가루", "새우젓", "멸치액젓", "올리고당", "조성액", "EX", "정제수", "인삼", "동백꽃", "표고버섯", "개망초", "아카시아 꽃"]
        full_list = ["개망초", "개망초잎", "개망초꽃", "개망초가루", "아카시아 꽃", "아카시아 잎", "아카시아 꽃/잎", "애기똥풀 꽃", "애기똥풀 꽃/줄기", "동백꽃", "메주콩", "백태", "인삼", "수삼-5년근", "산양유", "우유", "철원 산삼", "인삼vpl", "갈대뿌리", "당근", "표고버섯", "등나무꽃", "등나무줄기", "등나무꽃/줄기", "개망초꽃8+아카시아잎1", "뽕잎", "뽕잎가루", "매실", "매실꽃", "매화꽃", "토종홉 꽃", "토종홉 꽃/잎", "연꽃", "무궁화꽃", "무궁화잎", "무궁화꽃/잎", "풋사과", "청귤", "장미꽃", "송이버섯", "산자나무열매", "싸리버섯", "무염김치", "생지황", "무염김칫물", "마늘", "대파", "부추", "저염김치", "유기농수삼", "명태머리", "굵은멸치", "흑새우", "다시마", "냉동블루베리", "슈가", "원당", "이소말토 올리고당", "프락토 올리고당", "고운 고춧가루", "굵은 고춧가루", "상황버섯", "영지버섯", "꽁치젓", "메가리젓", "어성초가루", "당두충가루"]
        sorted_others = sorted(list(set(full_list) - set(priority_list)))
        st.session_state.raw_material_list = priority_list + sorted_others
    if 'recipe_db' not in st.session_state:
        r_db = {}
        r_db["계란커드 스타터 [혼합]"] = {"desc": "대사체 단순 혼합", "batch_size": 9, "materials": {"개망초 대사체": 8, "아카시아잎 대사체": 1}}
        r_db["계란커드 스타터 [합제]"] = {"desc": "원물 8:1 혼합 대사", "batch_size": 9, "materials": {"개망초꽃(원물)": 8, "아카시아잎(원물)": 1, "EX": 36}}
        r_db["철원산삼 대사체"] = {"desc": "1:8 비율", "batch_size": 9, "materials": {"철원산삼": 1, "EX": 8}}
        st.session_state.recipe_db = r_db
    if 'regimen_db' not in st.session_state:
        st.session_state.regimen_db = {"울산 자궁근종": """1. 아침: 장미꽃 대사체 + 생수 350ml (격일)\n2. 취침 전: 인삼 전체 대사체 + 생수 1.8L 혼합물 500ml\n3. 식사 대용: 시원한 것 1병 + 계란-우유 대사체 1/2병\n4. 생활 습관: 자궁 보온, 기상 직후 골반 스트레칭\n5. 관리: 2주 단위 초음파 검사"""}

init_session_state()

# ==============================================================================
# 5. 메인 화면 구성 및 보조 함수
# ==============================================================================
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

show_inventory_dashboard()

st.sidebar.title("📌 메뉴 선택")
app_mode = st.sidebar.radio("작업 모드를 선택하세요", ["🚛 배송/주문 관리", "🏭 생산/공정 관리"])

st.title(f"🏥 엘랑비탈 ERP v.1.0.0 ({app_mode})")

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
    t1, t2, t3, t4, t5 = st.tabs(["📦 개인별 포장", "📊 제품별 총합", "🧪 혼합 제조", "📊 커드 수요량", "📂 발송 이력/분석"])

    with t1:
        c_head, c_btn = st.columns([2, 1])
        with c_head: st.header("📦 개인별 포장 목록 (라벨)")
        with c_btn:
            if st.button("📝 발송 내역 저장 및 재고 차감"):
                if not sel_p: st.warning("선택된 환자 없음")
                else:
                    records = []
                    today_str = target_date.strftime('%Y-%m-%d')
                    for p_name, p_data in sel_p.items():
                        content_str = ", ".join([f"{i['제품']}:{i['수량']}" for i in p_data['items']])
                        records.append([today_str, p_name, p_data['group'], p_data['round'], content_str])
                        for i in p_data['items']:
                            update_inventory(i['제품'], -float(i['수량']))
                    if save_to_history(records): st.success("발송 기록 및 재고 반영 완료!")
        
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
        st.header("📊 제품별 총합 (개별 포장)")
        tot = {}
        for data_info in sel_p.values():
            for x in data_info['items']:
                if "혼합" not in str(x['제품']):
                    k = f"{x['제품']} {x['용량']}" if x.get('용량') else x['제품']
                    tot[k] = tot.get(k, 0) + x['수량']
        st.dataframe(pd.DataFrame(list(tot.items()), columns=["제품", "수량"]).sort_values("수량", ascending=False), use_container_width=True)

    with t3:
        st.header("🧪 혼합 제조 (Batch Mixing)")
        req = {}
        for data_info in sel_p.values():
            for x in data_info['items']:
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
                        ratio = in_q / r['batch_size'] if r['batch_size'] > 1 else in_q
                        for m, mq in r['materials'].items():
                            if isinstance(mq, (int, float)):
                                calc = mq * ratio
                                c2.write(f"- {m}: **{calc:.1f}**")
                                total_mat[m] = total_mat.get(m, 0) + calc
            st.divider()
            st.subheader("∑ 원료 총 필요량")
            for k, v in sorted(total_mat.items(), key=lambda x: x[1], reverse=True):
                st.info(f"📦 **{k}**: {v:.1f}")

    with t4:
        st.header("📊 커드 수요량")
        curd_pure = sum(x['수량'] for d in sel_p.values() for x in d['items'] if x['제품'] in ["계란 커드", "커드"])
        curd_cool = sum(x['수량'] for d in sel_p.values() for x in d['items'] if x['제품'] == "커드 시원한 것")
        total_kg = (curd_cool * 40 + curd_pure * 150) / 1000
        milk = (total_kg / 9) * 16
        c1, c2 = st.columns(2)
        c1.metric("시원한 것 (40g)", f"{curd_cool}개")
        c2.metric("계란 커드 (150g)", f"{curd_pure}개")
        st.info(f"🧀 **총 필요 커드:** 약 {total_kg:.2f} kg | 🥛 **필요 우유:** 약 {math.ceil(milk)}통")

    with t5:
        st.header("📂 발송 이력 및 누적 분석")
        hist_df = load_sheet_data("history", "발송일")
        
        if not hist_df.empty:
            # --- [지능형 데이터 분석] ---
            parsed_list = []
            for _, row in hist_df.iterrows():
                items = str(row['발송내역']).split(',')
                for it in items:
                    if ':' in it:
                        try:
                            p_name, p_qty = it.split(':')
                            parsed_list.append({
                                "발송일": row['발송일'], "이름": row['이름'],
                                "그룹": row['그룹'], "제품": p_name.strip(), "수량": int(p_qty.strip())
                            })
                        except: continue
            
            p_df = pd.DataFrame(parsed_list)
            
            # --- [필터 UI] ---
            st.subheader("🔍 분석 대상 선택")
            all_patients = sorted(p_df['이름'].unique())
            selected_names = st.multiselect("분석할 환자를 선택하세요 (다중 선택 가능)", all_patients, help="원하는 사람들을 선택하면 그들의 개별 및 합계 데이터가 나옵니다.")
            
            if selected_names:
                # 선택된 환자 데이터 필터링
                filtered_df = p_df[p_df['이름'].isin(selected_names)]
                
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.markdown("##### 👤 선택 환자별 누적 총합")
                    # 개인별-제품별 피벗 테이블
                    pivot_each = filtered_df.pivot_table(index="이름", columns="제품", values="수량", aggfunc="sum", fill_value=0)
                    pivot_each["인당 총합"] = pivot_each.sum(axis=1)
                    st.dataframe(pivot_each, use_container_width=True)
                
                with c2:
                    st.markdown("##### 📊 선택 그룹 전체 제품 총합")
                    group_sum = filtered_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False)
                    st.dataframe(group_sum.rename(columns={"수량": "전체 합계"}), use_container_width=True)
                
                # 금액 합산 (추후 단가 반영용)
                with st.container(border=True):
                    st.write("💰 **추후 단가 결정 시 예상 매출 합산 구역**")
                    st.caption("현재는 수량 합산만 표시됩니다. 단가 로직 추가 시 자동 계산 가능합니다.")
            
            st.divider()
            
            # --- [전체 통계] ---
            st.subheader("🌐 전체 누적 통계")
            col_stat1, col_stat2 = st.columns(2)
            with col_stat1:
                st.markdown("**[전체 환자 제품 총합]**")
                st.dataframe(p_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False), use_container_width=True)
            with col_stat2:
                st.markdown("**['울산' 제외 환자 제품 총합]**")
                non_ulsan = p_df[~p_df['이름'].str.contains("울산", na=False) & (p_df['그룹'] != "울산")]
                st.dataframe(non_ulsan.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False), use_container_width=True)
            
            st.divider()
            st.subheader("📂 발송 원본 로그")
            st.dataframe(hist_df, use_container_width=True)
        else:
            st.info("발송 이력이 없습니다.")

# ==============================================================================
# [MODE 2] 생산/공정 관리
# ==============================================================================
elif app_mode == "🏭 생산/공정 관리":
    t_yield, t6, t7, t8, t9, t10 = st.tabs(["📊 수율/예측", "🧀 커드 생산 관리", "🗓️ 연간 일정", "💊 임상/처방", "🏭 기타 생산 이력", "🔬 대사/pH 관리"])

    with t_yield:
        st.header("📊 생산량 예측 및 수율 관리")
        col_pred, col_record = st.columns(2)
        with col_pred:
            with st.container(border=True):
                y_bottles = st.number_input("🥛 우유 투입 (통)", 0, value=10, step=1, key="y_bottles")
                y_mode = st.radio("생산 제품", ["계란커드", "일반커드"], key="y_mode")
                y_expected_kg = y_bottles * YIELD_CONSTANTS["MILK_BOTTLE_TO_CURD_KG"]
                st.markdown(f"**📉 총 예상 무게: :blue[{y_expected_kg:.1f} kg]**")
        with col_record:
            with st.container(border=True):
                y_actual = st.number_input("⚖️ 실제 무게 (kg)", 0.0, format="%.2f", key="y_actual")
                if y_actual > 0:
                    loss_rate = ((y_expected_kg - y_actual) / y_expected_kg * 100) if y_expected_kg > 0 else 0
                    st.success(f"✅ 손실률: {loss_rate:.1f}%")
                    if st.button("💾 수율 기록 저장"):
                        rec = [datetime.now(KST).strftime("%Y-%m-%d %H:%M"), y_mode, y_bottles, y_expected_kg, y_actual, round(loss_rate, 2), ""]
                        if save_yield_log(rec): st.success("저장 완료!")

    with t6:
        st.header("🧀 커드 생산 관리")
        with st.expander("🥛 1단계: 배합 및 대사 시작", expanded=True):
            batch_milk_vol = st.number_input("우유 개수 (통)", 1, 200, 30)
            target_product = st.radio("종류", ["계란 커드 (완제품)", "일반 커드 (중간재)"])
            milk_kg = batch_milk_vol * 2.3
            egg_kg = milk_kg / 4 if "계란" in target_product else 0
            st.metric("🥛 우유", f"{milk_kg:.2f} kg")
            if egg_kg > 0: st.metric("🥚 계란", f"{egg_kg:.2f} kg")

            if st.button("🚀 대사 시작 (재고 차감)"):
                batch_id = f"{datetime.now(KST).strftime('%y%m%d')}-{target_product[:2]}-{uuid.uuid4().hex[:4]}"
                status_json = json.dumps({"total": 15, "meta": 15, "sep": 0, "fail": 0, "done": 0})
                rec = [batch_id, datetime.now(KST).strftime("%Y-%m-%d"), target_product, "우유+스타터", f"{milk_kg:.1f}", "기본비율", 0, 0, "", status_json]
                if save_production_record("curd_prod", rec):
                    update_inventory("우유", -float(batch_milk_vol))
                    if egg_kg > 0: update_inventory("계란", -float(egg_kg))
                    st.success("대사 시작 및 재고 반영 완료!")
                    st.rerun()

    with t7:
        st.header(f"🗓️ 연간 생산 캘린더")
        sel_month = st.selectbox("월 선택", list(range(1, 13)), index=datetime.now(KST).month-1)
        current_sched = st.session_state.schedule_db[sel_month]
        st.success(f"🌱 {current_sched['title']} 주요 품목: {', '.join(current_sched['main'])}")

    with t8:
        st.header("💊 환자별 맞춤 처방 관리")
        regimen_names = list(st.session_state.regimen_db.keys())
        selected_regimen = st.selectbox("처방전 선택", regimen_names + ["(신규)"])
        if selected_regimen != "(신규)":
            st.info(st.session_state.regimen_db[selected_regimen])

    with t9:
        st.header("🏭 기타 생산 이력")
        p_date = st.date_input("생산일", datetime.now(KST))
        p_name = st.selectbox("원재료", st.session_state.raw_material_list)
        if st.button("💾 저장"):
            st.success("기타 생산 기록 저장 로직 작동")

    with t10:
        st.header("🔬 대사 관리 및 pH 측정")
        ph_val = st.number_input("pH 값", 0.0, 14.0, 5.0, step=0.01)
        if st.button("💾 pH 저장"):
            if save_ph_log(["DIRECT", datetime.now(KST).strftime("%Y-%m-%d %H:%M"), ph_val, 30.0, ""]):
                st.success("저장 완료!")
