import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
import holidays
import uuid

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
            st.title("🔒 엘랑비탈 ERP v.7.3")
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
        
        # 기본 용량 사전
        default_caps = {
            "시원한 것": "280ml", "마시는 것": "280ml", "커드 시원한 것": "280ml",
            "인삼 사이다": "300ml", "EX": "280ml",
            "인삼대사체(PAGI)": "50ml", "인삼대사체(PAGI) 항암용": "50ml", "인삼대사체(PAGI) 뇌질환용": "50ml",
            "개망초(EDF)": "50ml", "장미꽃 대사체": "50ml", "애기똥풀 대사체": "50ml",
            "송이 대사체": "50ml", "표고버섯 대사체": "50ml", "철원산삼 대사체": "50ml",
            "커드": "150g", "계란 커드": "150g"
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
                    cap = default_caps.get(clean_name, "")
                    items_list.append({"제품": clean_name, "수량": int(p_qty.strip()), "용량": cap})
            
            round_val = row.get('회차')
            if round_val is None or str(round_val).strip() == "": round_num = 1 
            else:
                try: round_num = int(str(round_val).replace('회', '').replace('주', '').strip())
                except: round_num = 1

            start_date_str = str(row.get('시작일', '')).strip()

            db[name] = {
                "group": row['그룹'], "note": row['비고'],
                "default": True if str(row['기본발송']).upper() == 'O' else False,
                "items": items_list, "round": round_num, "start_date_raw": start_date_str
            }
        return db
    except Exception as e:
        st.error(f"❌ 데이터 로딩 실패: {e}")
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

# [v.7.3] 생산 이력 저장 (Batch ID 포함)
def save_production_record(record):
    try:
        client = get_gspread_client()
        try: sheet = client.open("vpmi_data").worksheet("production")
        except:
            sheet = client.open("vpmi_data").add_worksheet(title="production", rows="1000", cols="12")
            # [헤더] 배치ID 추가, 상태 추가
            sheet.append_row(["배치ID", "생산일", "종류", "원재료", "투입량(kg)", "비율", "스타터총량", "정제수", "조성액", "올리고당", "비고", "상태"])
        sheet.append_row(record)
        return True
    except Exception as e:
        st.error(f"생산 이력 저장 실패: {e}")
        return False

# [v.7.3] pH 로그 저장 (Batch ID 포함)
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

# [v.7.3] 생산 상태 업데이트 (진행중 -> 종료)
def update_production_status(batch_id, new_status):
    try:
        client = get_gspread_client()
        sheet = client.open("vpmi_data").worksheet("production")
        # 배치ID가 있는 행 찾기
        cell = sheet.find(batch_id)
        if cell:
            # 상태 컬럼(L열, 12번째) 업데이트
            sheet.update_cell(cell.row, 12, new_status)
            return True
        return False
    except Exception as e:
        st.error(f"상태 업데이트 실패: {e}")
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

    if 'product_list' not in st.session_state:
        plist = [
            "시원한 것", "마시는 것", "커드 시원한 것", "커드", "계란 커드", "EX",
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
        st.session_state.regimen_db = {"울산 자궁근종": "..."}

init_session_state()

# 5. 메인 화면
st.title("🏥 엘랑비탈 ERP v.7.3 (pH Integration)")
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
    week = (date_obj.day - 1) // 7 + 1
    return f"{date_obj.month}월 {week}주"

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
t1, t2, t3, t4, t5, t6, t7, t8, t9 = st.tabs(["🏷️ 라벨", "🎁 장연구원", "🧪 한책임", "📊 커드 수요량", f"🏭 생산 관리 ({week_str})", f"🗓️ 연간 일정 ({month_str})", "💊 임상/처방", "📂 발송 이력", "🏭 생산/대사 관리"])

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

# Tab 2~7 생략 (기존 유지)

# Tab 8
with t8:
    st.header("📂 발송 이력")
    if st.button("🔄 이력 새로고침", key="ref_hist"): st.rerun()
    hist_df = load_sheet_data("history")
    if not hist_df.empty:
        st.dataframe(hist_df, use_container_width=True)
        csv = hist_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 다운로드", csv, f"history_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")

# [v.7.3] Tab 9: 생산 및 대사 관리
with t9:
    st.header("🏭 생산 및 대사 관리")
    
    # 1. 신규 생산 입력
    with st.container(border=True):
        st.subheader("📝 신규 생산 시작 (Start)")
        c1, c2, c3 = st.columns(3)
        p_date = c1.date_input("생산일", datetime.now(KST))
        p_type = c2.selectbox("종류", ["일반 식물 대사체", "무염김치", "커드(일반)", "계란 커드", "철원산삼", "기타"])
        p_name = c3.text_input("원재료명")
        
        c4, c5, c6 = st.columns(3)
        p_weight = c4.number_input("원재료(kg)", 0.0, 1000.0, 1.0)
        p_ratio = c5.selectbox("비율", ["1:4", "1:6", "1:8", "1:10", "1:12"])
        p_note = c6.text_input("비고 (특이사항)")
        
        try: r_val = int(p_ratio.split(':')[1])
        except: r_val = 4
        total = p_weight * r_val
        st.caption(f"🧪 배합: 물 {total/106.3*100:.1f}kg, EX {total/106.3*3.5:.1f}kg, 당 {total/106.3*2.8:.1f}kg")
        
        if st.button("💾 생산 시작 (DB저장)"):
            # 배치ID 생성 (날짜 + 랜덤)
            batch_id = f"{p_date.strftime('%y%m%d')}-{p_name}-{uuid.uuid4().hex[:4]}"
            rec = [batch_id, p_date.strftime("%Y-%m-%d"), p_type, p_name, p_weight, p_ratio, f"{total:.1f}", 
                   f"{total/106.3*100:.1f}", f"{total/106.3*3.5:.1f}", f"{total/106.3*2.8:.1f}", p_note, "진행중"]
            if save_production_record(rec): st.success(f"[{batch_id}] 생산 등록 완료!")

    st.divider()

    # 2. 대사 관리 (진행 중인 항목)
    st.subheader("🔬 대사 관리 (pH Monitoring)")
    if st.button("🔄 목록 새로고침"): st.rerun()
    
    prod_df = load_sheet_data("production")
    if not prod_df.empty:
        # 진행 중인 것만 필터링
        ongoing_df = prod_df[prod_df['상태'] == '진행중']
        
        if not ongoing_df.empty:
            # 선택 박스 (배치ID + 이름)
            batch_options = ongoing_df.apply(lambda x: f"{x['배치ID']} ({x['원재료']})", axis=1).tolist()
            sel_batch_str = st.selectbox("관리할 대사체 선택", batch_options)
            sel_batch_id = sel_batch_str.split(' ')[0]
            
            # pH 입력 폼
            with st.form("ph_input_form"):
                st.markdown(f"**{sel_batch_str}** 의 상태를 기록합니다.")
                c_p1, c_p2, c_p3 = st.columns(3)
                ph_val = c_p1.number_input("현재 pH", 0.0, 14.0, 5.0, step=0.01)
                ph_temp = c_p2.number_input("온도 (℃)", 0.0, 50.0, 30.0)
                is_finish = c_p3.checkbox("대사 종료 (완료 처리)")
                ph_memo = st.text_input("메모")
                
                if st.form_submit_button("기록 저장"):
                    dt_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
                    # pH 로그 저장
                    save_ph_log([sel_batch_id, dt_str, ph_val, ph_temp, ph_memo])
                    
                    # 종료 체크 시 상태 업데이트
                    if is_finish:
                        if update_production_status(sel_batch_id, "완료"):
                            st.success("🎉 대사 종료 처리되었습니다!")
                        else:
                            st.error("상태 업데이트 실패")
                    else:
                        st.success("pH 기록이 저장되었습니다.")
                        
            # 과거 기록 차트
            st.markdown("📉 **pH 변화 추이**")
            ph_logs = load_sheet_data("ph_logs")
            if not ph_logs.empty:
                my_logs = ph_logs[ph_logs['배치ID'] == sel_batch_id]
                if not my_logs.empty:
                    st.line_chart(my_logs.set_index('측정일시')['pH'])
                    st.dataframe(my_logs)
        else:
            st.info("현재 진행 중인 대사가 없습니다.")
    else:
        st.info("생산 기록이 없습니다.")
