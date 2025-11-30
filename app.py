import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta, timezone

# 1. 페이지 설정
st.set_page_config(page_title="엘랑비탈 정기배송", page_icon="🏥", layout="wide")

# [수정] 한국 시간(KST) 전역 변수 설정 (여기 있어야 에러가 안 납니다!)
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
            st.title("🔒 엘랑비탈 정기배송 v.4.4.3")
            with st.form("login"):
                st.text_input("비밀번호:", type="password", key="password")
                st.form_submit_button("로그인", on_click=password_entered)
        return False
    return True

if not check_password():
    st.stop()

# 3. 데이터 초기화
def add_patient(db, name, group, note, default, items):
    db[name] = {"group": group, "note": note, "default": default, "items": items}

def init_session_state():
    # (1) 날짜 초기화 (한국 시간 기준)
    if 'target_date' not in st.session_state:
        st.session_state.target_date = datetime.now(KST)
    
    # (2) 연간 일정 DB
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
    
    # (3) 뷰 모드
    if 'view_month' not in st.session_state:
        st.session_state.view_month = st.session_state.target_date.month

    if 'product_list' not in st.session_state:
        plist = [
            "시원한 것", "마시는 것", "커드 시원한 것", "커드", "EX",
            "인삼대사체(PAGI) 항암용", "인삼대사체(PAGI) 뇌질환용",
            "표고버섯 대사체", "개망초(EDF)", "장미꽃 대사체",
            "애기똥풀 대사체", "인삼 사이다", "송이 대사체",
            "PAGI 희석액", "Vitamin C", "SiO2", "계란커드 스타터",
            "혼합 [E.R.P.V.P]", "혼합 [P.V.E]", "혼합 [P.P.E]",
            "혼합 [Ex.P]", "혼합 [R.P]", "혼합 [Edf.P]", "혼합 [P.P]"
        ]
        st.session_state.product_list = plist

    if 'patient_db' not in st.session_state:
        db = {}
