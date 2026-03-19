import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import json
import os
import re
from bs4 import BeautifulSoup
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz

# --- [0. 전역 설정 및 경로] ---
st.set_page_config(page_title="Nemo 상가 매물 분석 랩", layout="wide")

SQLITE_PATH = os.path.join("data", "nemo_items.sqlite")
MD_FILE_PATH = "data_json_html.md"

# --- [1. 유틸리티 함수] ---

def format_currency_kr(man_won):
    """만원 단위를 한국식(억/만)으로 변환"""
    if pd.isna(man_won) or man_won == 0:
        return "0"
    if man_won >= 10000:
        uk = int(man_won // 10000)
        man = int(man_won % 10000)
        return f"{uk}억 {man:,}만" if man > 0 else f"{uk}억"
    return f"{int(man_won):,}만"

def parse_subway_info(station_str):
    """지하철역 문자열에서 역명과 분(minutes) 추출"""
    if not station_str or pd.isna(station_str):
        return "정보없음", 99
    parts = station_str.split(',')
    name = parts[0].strip()
    minutes = 99
    if len(parts) > 1:
        match = re.search(r'(\d+)', parts[1])
        if match:
            minutes = int(match.group(1))
    return name, minutes

# --- [2. 데이터 로드 및 파싱] ---

@st.cache_data
def load_combined_data():
    # A. SQLite 데이터 로드 (기본 데이터셋)
    db_items = pd.DataFrame()
    if os.path.exists(SQLITE_PATH):
        try:
            conn = sqlite3.connect(SQLITE_PATH)
            db_items = pd.read_sql_query("SELECT * FROM Items", conn)
            conn.close()
        except:
            pass
            
    # B. MD 파일 파싱 (JSON + HTML)
    md_items = []
    html_extra = {}
    
    if os.path.exists(MD_FILE_PATH):
        with open(MD_FILE_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # JSON부와 HTML부 분할
        parts = re.split(r'위 정보에 매핑되는 데이터는 다음 html에 들어 있습니다.*?\n+', content)
        if len(parts) >= 1:
            try:
                json_data = json.loads(parts[0])
                md_items = json_data.get('items', [])
            except:
                pass
        
        if len(parts) >= 2:
            soup = BeautifulSoup(parts[1], 'lxml')
            
            # HTML 상세 데이터 추출
            # 1. 중개사 코멘트
            cmt = soup.find('div', class_='comment')
            html_extra['comment'] = cmt.get_text(separator="\n").replace("더보기", "").strip() if cmt else ""
            
            # 2. 임대 상세 정보
            features = {}
            for li in soup.find_all('li', class_='flex flex-row w-1/2 gap-2 mt-4'):
                h6 = li.find('h6')
                p = li.find('p')
                if h6 and p: features[h6.text.strip()] = p.text.strip()
            html_extra['rental_info'] = features
            
            # 3. 건축물 대장
            reg = {}
            reg_table = soup.find('div', class_='detail-table head-line')
            if reg_table:
                for tr in reg_table.find_all('tr'):
                    th = tr.find('th').text.strip()
                    td = tr.find('td').text.strip()
                    reg[th] = td
            html_extra['building_reg'] = reg
            
            # 4. 특징 태그
            html_extra['tags'] = [t.text.strip() for t in soup.select('.feature-list h6')]
            
            # 5. 주변 시설 (버스정류장 등 샘플)
            facilities = []
            for item in soup.select('.around-facility-content'):
                f_name = item.find('p', class_='font-14').text.strip()
                f_dist = item.find('p', class_='text-gray-60').text.strip()
                facilities.append({"명칭": f_name, "거리/시간": f_dist})
            html_extra['facilities'] = facilities
            
            # 6. 이미지 URL
            html_extra['images'] = [img['src'] for img in soup.find_all('img', class_='slide-image')]

    # 데이터 통합
    md_df = pd.DataFrame(md_items)
    combined_df = pd.concat([db_items, md_df], ignore_index=True).drop_duplicates(subset=['id'])
    
    # 전처리 및 파생 변수
    if not combined_df.empty:
        # 금액 변환
        for c in ['deposit', 'monthlyRent', 'premium', 'maintenanceFee']:
            if c in combined_df.columns:
                combined_df[f'{c}_display'] = combined_df[c].apply(format_currency_kr)
        
        # 날짜
        combined_df['created_date'] = pd.to_datetime(combined_df['createdDateUtc'], errors='coerce', format='ISO8601').dt.date
        combined_df['edited_date'] = pd.to_datetime(combined_df['editedDateUtc'], errors='coerce', format='ISO8601').dt.date
        
        # 지하철
        sub_info = combined_df['nearSubwayStation'].apply(parse_subway_info)
        combined_df['subway_name'] = [x[0] for x in sub_info]
        combined_df['subway_min'] = [x[1] for x in sub_info]
        
        # 파생
        combined_df['is_first_floor'] = combined_df['floor'] == 1
        combined_df['is_station_area'] = combined_df['subway_min'] <= 10
        combined_df['has_premium'] = combined_df['premium'] > 0
        combined_df['total_monthly'] = combined_df['monthlyRent'] + combined_df.get('maintenanceFee', 0)
        combined_df['size_py'] = combined_df['size'] / 3.3058
        
        # 면적 그룹
        combined_df['size_group'] = pd.cut(combined_df['size'], bins=[0, 33, 66, 100, 9999], labels=['소형(10평↓)', '중소형(20평↓)', '중형(30평↓)', '대형(30평↑)'])

    return combined_df, html_extra

# --- [3. 메인 대시보드 UI] ---

df, html_info = load_combined_data()

st.sidebar.title("🧪 Nemo Lab")
st.sidebar.markdown("---")
section = st.sidebar.radio("메뉴 이동", ["홈 / 요약 대시보드", "데이터 파싱 현황", "EDA 분석", "검색 / 필터 탐색", "매물 상세 페이지", "인사이트 리포트"])

if df.empty:
    st.warning("데이터 소스를 찾을 수 없습니다. 경로를 확인해주세요.")
else:
    if section == "홈 / 요약 대시보드":
        st.title("🏡 상가 매물 요약 대시보드")
        
        # 상단 KPIs
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 매물 수", f"{len(df)} 건")
        m2.metric("업종 수", f"{df['businessMiddleCodeName'].nunique()} 개")
        m3.metric("평균 보증금", format_currency_kr(df['deposit'].mean()))
        m4.metric("평균 월세", format_currency_kr(df['monthlyRent'].mean()))
        
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("평균 전용면적", f"{df['size'].mean():.1f} ㎡")
        m6.metric("평균 평당가 (areaPrice)", f"{df['areaPrice'].mean():.0f}")
        m7.metric("역세권 비중", f"{(df['is_station_area'].mean()*100):.1f} %")
        m8.metric("1층 매물 비중", f"{(df['is_first_floor'].mean()*100):.1f} %")
        
        st.markdown("---")
        st.subheader("📍 지역 상권 요약")
        st.write("지하철역 기준 매물 분포")
        st.bar_chart(df['subway_name'].value_counts().head(10))

    elif section == "데이터 파싱 현황":
        st.title("⚙️ 데이터 전처리 및 파싱 통계")
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("데이터 수집 요약")
            st.info(f"SQLite DB: {len(df)-1 if len(df)>0 else 0} items / MD(JSON): 1 item")
            st.write("HTML 상세 파싱 성공 리스트:", list(html_info.keys()))
            
        with col2:
            st.subheader("결측치 현황")
            st.dataframe(df.isnull().sum().to_frame(name="Missing Counts"))
            
        st.subheader("금액 단위 변환 검증 (Raw vs Display)")
        st.table(df[['title', 'deposit', 'deposit_display', 'monthlyRent', 'monthlyRent_display']].head(5))

    elif section == "EDA 분석":
        st.title("📊 상가 매물 시장 분석 (EDA)")
        
        tab_price, tab_loc, tab_corr = st.tabs(["💰 가격 분포", "📍 위치 및 층수", "🔗 상관관계 분석"])
        
        with tab_price:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.histogram(df, x="deposit", title="보증금 분포 히스토그램", color_discrete_sequence=['deepskyblue']), use_container_width=True)
            c2.plotly_chart(px.histogram(df, x="monthlyRent", title="월세 분포 히스토그램", color_discrete_sequence=['tomato']), use_container_width=True)
            st.plotly_chart(px.histogram(df, x="premium", title="권리금 분포 히스토그램", color_discrete_sequence=['gold']), use_container_width=True)
            
        with tab_loc:
            c1, c2 = st.columns(2)
            floor_df = df['floor'].value_counts().sort_index().reset_index()
            c1.plotly_chart(px.bar(floor_df, x='index', y='floor', title="층별 매물 건수", labels={'index':'층', 'floor':'건수'}), use_container_width=True)
            c2.plotly_chart(px.pie(df, names='businessLargeCodeName', title="업종 대분류 비중"), use_container_width=True)

        with tab_corr:
            st.plotly_chart(px.scatter(df, x="size", y="monthlyRent", size="deposit", color="businessLargeCodeName", hover_name="title", title="면적 vs 월세 산점도 (원 크기=보증금)"), use_container_width=True)
            st.caption("면적이 넓어질수록 고정 임대료(월세)가 상승하는 경향이 뚜렷하며, 업종별로 가격대가 다르게 형성됩니다.")

    elif section == "검색 / 필터 탐색":
        st.title("🔍 조건별 매물 필터링")
        
        # Filter Logic
        with st.expander("필터 옵션 설정", expanded=True):
            f1, f2, f3 = st.columns(3)
            search_query = f1.text_input("매물 제목/키워드 검색", "")
            sel_biz = f2.multiselect("업종 분류", options=df['businessMiddleCodeName'].unique())
            sel_floor = f3.multiselect("층수", options=sorted(df['floor'].unique()))
            
            f4, f5 = st.columns(2)
            range_dep = f4.slider("보증금 (만)", 0, int(df['deposit'].max()), (0, int(df['deposit'].max())))
            range_rent = f5.slider("월세 (만)", 0, int(df['monthlyRent'].max()), (0, int(df['monthlyRent'].max())))

        # Apply
        filtered = df[
            (df['deposit'].between(range_dep[0], range_dep[1])) &
            (df['monthlyRent'].between(range_rent[0], range_rent[1]))
        ]
        if search_query: filtered = filtered[filtered['title'].str.contains(search_query, case=False)]
        if sel_biz: filtered = filtered[filtered['businessMiddleCodeName'].isin(sel_biz)]
        if sel_floor: filtered = filtered[filtered['floor'].isin(sel_floor)]
        
        st.subheader(f"총 {len(filtered)} 개의 매물이 발견되었습니다.")
        
        sort_col = st.selectbox("정렬", ["월세 낮은 순", "보증금 낮은 순", "면적 큰 순", "조회수 높은 순"])
        if sort_col == "월세 낮은 순": filtered = filtered.sort_values("monthlyRent")
        elif sort_by == "보증금 낮은 순": filtered = filtered.sort_values("deposit")
        elif sort_by == "면적 큰 순": filtered = filtered.sort_values("size", ascending=False)
        else: filtered = filtered.sort_values("viewCount", ascending=False)
        
        st.dataframe(filtered[['number', 'title', 'businessMiddleCodeName', 'deposit_display', 'monthlyRent_display', 'floor', 'size', 'nearSubwayStation', 'viewCount']], use_container_width=True)

    elif section == "매물 상세 페이지":
        st.title("📱 매물 상세 브리핑")
        
        # Select item
        item_id = st.selectbox("조회할 매물을 선택하세요", options=df['id'].tolist(), format_func=lambda x: df[df['id']==x]['title'].iloc[0])
        item = df[df['id'] == item_id].iloc[0]
        
        # MD 파일의 데이터인지 확인 (데모용 HTML 상세 연결)
        is_md_demo = (item['id'] == "05bfdb5f-0471-45d4-b7fc-dd8edceae38a")
        
        # UI
        if is_md_demo and 'images' in html_info:
            cols = st.columns(min(len(html_info['images']), 4))
            for i, img in enumerate(html_info['images'][:4]):
                cols[i].image(img, use_container_width=True)
        else:
            st.image(item['previewPhotoUrl'], width=300)
            
        col_main, col_sub = st.columns([2, 1])
        
        with col_main:
            st.header(item['title'])
            st.subheader(f"📍 {item['nearSubwayStation']}")
            
            with st.expander("🛠️ 매물 상세 특징 및 코멘트", expanded=True):
                if is_md_demo:
                    st.write(html_info.get('comment', "정보 없음"))
                    if 'tags' in html_info:
                        st.write("---")
                        st.markdown(" ".join([f":blue-background[{t}]" for t in html_info['tags']]))
                else:
                    st.info("이 매물은 기본 정보만 수집되었습니다.")
            
            if is_md_demo and 'building_reg' in html_info:
                st.subheader("🏗️ 건축물 대장 요약")
                st.table(pd.DataFrame(html_info['building_reg'].items(), columns=["항목", "내용"]))
                
            if is_md_demo and 'facilities' in html_info:
                st.subheader("🏪 주변 500m 인프라")
                st.dataframe(pd.DataFrame(html_info['facilities']), use_container_width=True)

        with col_sub:
            st.warning(f"💰 **입대 조건**\n\n- **보증금**: {item['deposit_display']}\n- **월세**: {item['monthlyRent_display']}\n- **권리금**: {item['premium_display']}\n- **관리비**: {int(item.get('maintenanceFee', 0))}만")
            st.success(f"📏 **면적/층수**\n\n- **전용면적**: {item['size']:.1f} ㎡ (약 {item['size_py']:.1f}평)\n- **해당층**: {item['floor']}층 / {item['groundFloor']}층")
            
            if is_md_demo:
                st.write("### 🏠 임대 세부 정보")
                st.write(html_info.get('rental_info', {}))

    elif section == "인사이트 리포트":
        st.title("💡 데이터 기반 시장 인사이트")
        
        most_common_biz = df['businessMiddleCodeName'].mode()[0]
        avg_rent_biz = df.groupby('businessMiddleCodeName')['monthlyRent'].mean().idxmax()
        
        st.markdown(f"""
        - **최다 공급 업종**: 현재 시장에 가장 많은 매물은 **{most_common_biz}** (전체의 {len(df[df['businessMiddleCodeName']==most_common_biz])/len(df)*100:.1f}%) 입니다.
        - **임대료 리더**: 평균 월세가 가장 높은 업종은 **{avg_rent_biz}** 입니다.
        - **역세권 가치**: 역세권 매물은 비역세권 대비 평균 보증금이 약 **{((df[df['is_station_area']]['deposit'].mean()/df[~df['is_station_area']]['deposit'].mean())-1)*100:.1f}%** 높게 형성되어 있습니다.
        - **1층 프리미엄**: 지상 1층 매물은 타 층 대비 권리금이 존재할 확률이 **{((df[df['is_first_floor']]['has_premium'].mean()/df[~df['is_first_floor']]['has_premium'].mean())-1)*100:.1f}%** 높습니다.
        """)
        
        st.info("본 리포트는 수집된 데이터를 실시간으로 통계 처리하여 생성되었습니다.")
        st.balloons()
