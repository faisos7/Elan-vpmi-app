# ==============================================================================
# 8. 모드 2: 누적 데이터 분석 (에러 수정 및 가독성 최종 최적화)
# ==============================================================================
elif main_menu == "📈 누적 데이터 분석":
    st.header("📈 누적 데이터 정밀 분석")
    
    h_df = get_sheet_as_df("history", "발송일")
    
    if not h_df.empty:
        with st.form("stat_form"):
            st.subheader("🔍 분석 대상 환자 다중 선택")
            targets = st.multiselect("사람들을 선택한 후 버튼을 누르세요", sorted(h_df['이름'].unique()))
            submit_btn = st.form_submit_button("✅ 분석 시작")

        if submit_btn and targets:
            filtered_h = h_df[h_df['이름'].isin(targets)]
            
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
            
            # 방식 1: 패키징 합계 (에러 해결 및 높이 최적화)
            with col_s1:
                st.markdown("#### 1️⃣ 방식 1: 패키징 합계")
                summary1 = p_df.groupby("제품")["수량"].sum().reset_index().sort_values("수량", ascending=False)
                # 에러 방지를 위해 height를 명시적인 큰 값으로 설정하거나 제거
                st.dataframe(
                    summary1, 
                    hide_index=True,
                    use_container_width=False,
                    height=min(len(summary1) * 35 + 40, 800), # 데이터 개수에 비례해 늘어나되 최대 800px
                    column_config={
                        "제품": st.column_config.TextColumn("제품 명칭", width=180),
                        "수량": st.column_config.NumberColumn("누적 수량", width=100, format="%d 개")
                    }
                )
            
            # 방식 2: 성분 분해 합계 (에러 해결 및 높이 최적화)
            with col_s2:
                st.markdown("#### 2️⃣ 방식 2: 성분 분해 합계")
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
                st.dataframe(
                    summary2, 
                    hide_index=True,
                    use_container_width=False,
                    height=min(len(summary2) * 35 + 40, 800), # 데이터 개수에 비례해 늘어남
                    column_config={
                        "성분명": st.column_config.TextColumn("개별 성분", width=180),
                        "총합": st.column_config.NumberColumn("최종 소요량", width=100, format="%.1f")
                    }
                )

            st.divider()
            st.subheader("👤 선택 환자별 세부 히스토리")
            
            # 세부 히스토리 (상세 발송 내역 너비 확장 유지)
            st.dataframe(
                filtered_h, 
                use_container_width=True, 
                hide_index=True,
                height=500, # 세부 내역은 양이 많을 수 있으므로 적절한 고정 높이 제공
                column_config={
                    "발송일": st.column_config.TextColumn("발송일", width=120),
                    "이름": st.column_config.TextColumn("환자명", width=100),
                    "그룹": st.column_config.TextColumn("그룹명", width=120),
                    "회차": st.column_config.NumberColumn("회차", width=80, format="%d회"),
                    "발송내역": st.column_config.TextColumn("📦 상세 발송 내역 (전체 내용)", width=800)
                }
            )
            
            csv = filtered_h.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 선택 환자 데이터 다운로드 (CSV)",
                data=csv,
                file_name=f"history_export_{datetime.now(KST).strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )
    else:
        st.warning("분석할 히스토리 데이터가 없습니다.")
