%%writefile app.py
import streamlit as st
import pandas as pd
import math

# 1. 페이지 설정
st.set_page_config(page_title="엘랑비탈 정기배송", page_icon="🏥", layout="wide")

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
            st.title("🔒 엘랑비탈 정기배송 v.4.0")
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
    if 'product_list' not in st.session_state:
        plist = [
            "시원한 것", "마시는 것", "커드 시원한 것", "커드", "EX",
            "인삼대사체(PAGI) 항암용", "인삼대사체(PAGI) 뇌질환용",
            "표고버섯 대사체", "개망초(EDF)", "장미꽃 대사체",
            "애기똥풀 대사체", "인삼 사이다", "송이 대사체",
            "PAGI 희석액", "Vitamin C", "SiO2",
            "혼합 [E.R.P.V.P]", "혼합 [P.V.E]", "혼합 [P.P.E]",
            "혼합 [Ex.P]", "혼합 [R.P]", "혼합 [Edf.P]", "혼합 [P.P]"
        ]
        st.session_state.product_list = plist

    if 'patient_db' not in st.session_state:
        db = {}
        # -- 남양주 --
        items = [
            {"제품": "시원한 것", "용량": "280ml", "수량": 21},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 14},
            {"제품": "EX", "용량": "280ml", "수량": 3},
            {"제품": "인삼대사체(PAGI) 항암용", "용량": "50ml", "수량": 7, "비고": "원액"},
            {"제품": "표고버섯 대사체", "용량": "50ml", "수량": 7}
        ]
        add_patient(db, "남양주 1", "남양주", "매주 발송", True, items)

        items = [
            {"제품": "마시는 것", "용량": "280ml", "수량": 14},
            {"제품": "시원한 것", "용량": "280ml", "수량": 14},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 14},
            {"제품": "커드", "용량": "150ml", "수량": 7},
            {"제품": "인삼대사체(PAGI) 항암용", "용량": "50ml", "수량": 14},
            {"제품": "개망초(EDF)", "용량": "50ml", "수량": 7},
            {"제품": "장미꽃 대사체", "용량": "50ml", "수량": 3}
        ]
        add_patient(db, "남양주 2", "남양주", "⚠️ 신장 투석 (매주)", True, items)

        items = [
            {"제품": "시원한 것", "용량": "280ml", "수량": 14},
            {"제품": "마시는 것", "용량": "280ml", "수량": 7},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 7},
            {"제품": "인삼대사체(PAGI) 항암용", "용량": "50ml", "수량": 7},
            {"제품": "애기똥풀 대사체", "용량": "50ml", "수량": 7}
        ]
        add_patient(db, "남양주 4", "남양주", "매주 발송", True, items)

        # -- 유방암 --
        items = [
            {"제품": "혼합 [E.R.P.V.P]", "용량": "150ml", "수량": 14, "타입": "혼합"},
            {"제품": "시원한 것", "용량": "280ml", "수량": 42},
            {"제품": "마시는 것", "용량": "280ml", "수량": 14},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 14}
        ]
        add_patient(db, "김동민 부인", "유방암", "2주 간격", True, items)

        items = [
            {"제품": "인삼 사이다", "용량": "280ml", "수량": 14},
            {"제품": "마시는 것", "용량": "280ml", "수량": 28},
            {"제품": "시원한 것", "용량": "280ml", "수량": 28},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 14},
            {"제품": "인삼대사체(PAGI) 항암용", "용량": "50ml", "수량": 14},
            {"제품": "송이 대사체", "용량": "50ml", "수량": 14}
        ]
        add_patient(db, "김귀례", "유방암", "2주 간격", True, items)

        items = [
            {"제품": "혼합 [P.V.E]", "용량": "150ml", "수량": 14, "타입": "혼합"},
            {"제품": "혼합 [P.P.E]", "용량": "150ml", "수량": 14, "타입": "혼합"},
            {"제품": "인삼대사체(PAGI) 항암용", "용량": "50ml", "수량": 42},
            {"제품": "시원한 것", "용량": "280ml", "수량": 42},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 28}
        ]
        add_patient(db, "김성기", "유방암", "2주 간격", True, items)

        items = [
            {"제품": "마시는 것", "용량": "280ml", "수량": 28},
            {"제품": "시원한 것", "용량": "280ml", "수량": 28},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 28},
            {"제품": "인삼 사이다", "용량": "280ml", "수량": 14},
            {"제품": "인삼대사체(PAGI) 항암용", "용량": "50ml", "수량": 14}
        ]
        add_patient(db, "최은찬", "유방암", "2주 간격", True, items)

        items = [
            {"제품": "혼합 [Ex.P]", "용량": "150ml", "수량": 14, "타입": "혼합"},
            {"제품": "혼합 [R.P]", "용량": "150ml", "수량": 14, "타입": "혼합"},
            {"제품": "혼합 [Edf.P]", "용량": "150ml", "수량": 14, "타입": "혼합"},
            {"제품": "혼합 [P.P]", "용량": "150ml", "수량": 14, "타입": "혼합"},
            {"제품": "커드 시원한 것", "용량": "280ml", "수량": 14},
            {"제품": "인삼대사체(PAGI) 항암용", "용량": "50ml", "수량": 14}
        ]
        add_patient(db, "하혜숙", "유방암", "2주 간격", True, items)

        st.session_state.patient_db = db

    if 'recipe_db' not in st.session_state:
        r_db = {}
        r_db["혼합 [E.R.P.V.P]"] = {"desc": "6배수 혼합/14병", "batch_size": 14, "materials": {"인삼대사체(PAGI) 항암용 (50ml)": 12, "송이대사체 (50ml)": 6, "장미꽃 대사체 (50ml)": 6, "Vitamin C (3000mg)": 14, "SiO2 (1ml)": 14, "EX": 900}}
        r_db["혼합 [P.V.E]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"인삼대사체(PAGI) 항암용 (50ml)": 1, "Vitamin C (3000mg)": 1, "EX": 100}}
        r_db["혼합 [P.P.E]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"송이대사체 (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "EX": 50}}
        r_db["혼합 [Ex.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"인삼대사체(PAGI) 항암용 (50ml)": 1, "EX": 100}}
        r_db["혼합 [R.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"장미꽃 대사체 (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "인삼사이다": 50}}
        r_db["혼합 [Edf.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"개망초(EDF) (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "인삼사이다": 50}}
        r_db["혼합 [P.P]"] = {"desc": "1:1 개별 채움", "batch_size": 1, "materials": {"송이대사체 (50ml)": 1, "인삼대사체(PAGI) 항암용 (50ml)": 1, "EX": 50}}
        st.session_state.recipe_db = r_db

init_session_state()

# ==========================================
# 🛠️ 사이드바
# ==========================================
with st.sidebar:
    st.header("📌 메뉴 선택")
    mode = st.radio("", ["📊 계산기 모드", "👤 신규 환자 등록", "🧪 신규 레시피 등록"])
    st.divider()
    st.info(f"User: faisos")

if mode == "👤 신규 환자 등록" or mode == "🧪 신규 레시피 등록":
    st.title(mode)
    st.info("이전 코드를 사용하거나 필요시 요청해주세요.")

# ==========================================
# 3. 계산기 모드
# ==========================================
elif mode == "📊 계산기 모드":
    st.title("🏥 엘랑비탈 정기배송 v.4.0")
    col1, col2 = st.columns(2)
    with col1: target_date = st.date_input("발송일", value=pd.to_datetime("2025-11-25"))
    st.divider()

    db = st.session_state.patient_db
    sel_p = {}
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🚛 남양주 / 기타")
        for k, v in db.items():
            if v['group'] != "유방암":
                if st.checkbox(k, v['default'], help=v['note']): sel_p[k] = v['items']
    with c2:
        st.subheader("🚛 유방암")
        for k, v in db.items():
            if v['group'] == "유방암":
                if st.checkbox(k, v['default'], help=v['note']): sel_p[k] = v['items']
    
    st.divider()
    t1, t2, t3, t4, t5 = st.tabs(["🏷️ 라벨", "🎁 장연구원", "🧪 한책임", "📊 원자재", "🏭 생산 관리"])
    
    # 탭 1~4 (기존 로직 동일)
    with t1:
        st.header("🖨️ 라벨 출력")
        if not sel_p: st.warning("환자를 선택하세요")
        else:
            cols = st.columns(2)
            for i, (name, items) in enumerate(sel_p.items()):
                with cols[i%2]:
                    with st.container(border=True):
                        st.markdown(f"### 🧊 {name}")
                        st.caption(f"📅 {target_date}")
                        st.markdown("---")
                        for x in items:
                            chk = "✅" if "혼합" in str(x['제품']) else "□"
                            note = f"👉 {x['비고']}" if "비고" in x else ""
                            st.markdown(f"**{chk} {x['제품']}** {x['수량']}개 ({x['용량']}){note}")
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
                                if "EX" in m or "사이다" in m: c2.write(f"- {m}: **{calc:g} ml**")
                                else: c2.write(f"- {m}: **{calc:g} 개**")
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
                if x['제품'] == "커드": curd_pure += x['수량']
                elif x['제품'] == "커드 시원한 것": curd_cool += x['수량']
        
        need_from_cool = curd_cool * 40
        need_from_pure = curd_pure * 150
        total_kg = (need_from_cool + need_from_pure) / 1000
        milk = (total_kg / 9) * 16
        c1, c2 = st.columns(2)
        c1.metric("커드 시원한 것 (40g)", f"{curd_cool}개")
        c2.metric("커드 (150g)", f"{curd_pure}개")
        st.divider()
        st.info(f"🧀 **총 필요 커드:** 약 {total_kg:.2f} kg")
        st.success(f"🥛 **필요 우유:** 약 {math.ceil(milk)}통")

    # ----------------------------------------
    # [수정됨] 탭 5: 생산 관리 (3단 / 좌우 3열)
    # ----------------------------------------
    with t5:
        st.header("🏭 생산 공정 관리")
        st.markdown("---")
        
        # 1️⃣ [상단] 투입량 (Inputs)
        st.markdown("### 1️⃣ 원재료 투입")
        col_in1, col_in2, col_in3 = st.columns(3)
        with col_in1: in_kimchi = st.number_input("무염김치 (봉지)", 0, value=1)
        with col_in2: in_milk_reg = st.number_input("일반커드 우유 (통)", 0, value=16)
        with col_in3: in_milk_egg = st.number_input("계란커드 우유 (통)", 0, value=0)
        
        st.divider()
        
        # 2️⃣ [중단] 중간재 흐름 (무게 중심)
        st.markdown("### 2️⃣ 중간 생산물 & 배분 (Weight)")
        c_mid1, c_mid2, c_mid3 = st.columns(3)
        
        # 계산 로직
        prod_cool_cnt = in_kimchi * 215 
        prod_cool_kg = prod_cool_cnt * 0.274 # 총 시원한 것 (kg)
        
        prod_reg_curd_kg = in_milk_reg * 2.3 * 0.217 # 총 일반 커드 (kg)
        
        # (임시) 계란 커드용 시원한 것 소모량 (0으로 설정)
        req_cool_for_egg = 0
        
        req_cool_for_curd = prod_reg_curd_kg * 5.5 # 커드 혼합용 시원한 것
        
        # 잔여 시원한 것
        remain_cool_kg = prod_cool_kg - req_cool_for_curd - req_cool_for_egg
        remain_cool_cnt = int(remain_cool_kg * 1000 / 274)
        
        with c_mid1:
            st.info("🥬 **시원한 것 (총생산)**")
            st.metric("총 중량", f"{prod_cool_kg:.1f} kg")
            st.caption(f"무염김치 {in_kimchi}봉 기준")
            
        with c_mid2:
            st.warning("🥣 **중간 투입 (소모)**")
            st.write(f"- 커드 혼합용: **{req_cool_for_curd:.1f} kg**")
            st.write(f"- 계란커드용: **{req_cool_for_egg:.1f} kg** (미정)")
            st.write(f"- 계란 투입: **(미정)**")
            st.caption(f"※ 일반커드 총량: {prod_reg_curd_kg:.1f} kg")
            
        with c_mid3:
            st.success("🥚 **계란 커드 (생산)**")
            prod_egg_curd_kg = in_milk_egg * 2.3 * 0.22
            st.metric("총 중량", f"{prod_egg_curd_kg:.1f} kg")
            st.caption(f"우유 {in_milk_egg}통 기준")
            
        st.divider()
        
        # 3️⃣ [하단] 최종 완제품 (병수 중심)
        st.markdown("### 3️⃣ 최종 완제품 (Final Count)")
        c_fin1, c_fin2, c_fin3 = st.columns(3)
        
        with c_fin1:
            st.info("🧴 **시원한 것 (최종 잔여)**")
            if remain_cool_kg < 0:
                st.error(f"🚨 재료 부족! ({abs(remain_cool_kg):.1f} kg)")
            else:
                st.metric("생산 수량 (274g)", f"{remain_cool_cnt} 병")
                st.caption(f"잔여 {remain_cool_kg:.1f} kg")
                
        with c_fin2:
            st.error("🥣 **커드 시원한 것**")
            total_mix_kg = prod_reg_curd_kg + req_cool_for_curd
            mix_cnt = int(total_mix_kg * 1000 / 260)
            st.metric("생산 수량 (260g)", f"{mix_cnt} 병")
            st.caption(f"총 {total_mix_kg:.1f} kg")
            
        with c_fin3:
            st.warning("🥚 **계란 커드**")
            out_egg_cnt = int(prod_egg_curd_kg * 1000 / 150)
            st.metric("생산 수량 (150g)", f"{out_egg_cnt} 개")
            st.caption(f"총 {prod_egg_curd_kg:.1f} kg")
