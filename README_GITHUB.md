# Nemo Real Estate Analysis Dashboard

NemoApp 상가 매물 데이터를 시각화하고 분석하는 Streamlit 대시보드입니다.

## 배포 구성 파일
1. `app.py`: 메인 대시보드 실행 파일 (기존 `final_dashboard.py`)
2. `requirements.txt`: 의존성 라이브러리 목록
3. `data_json_html.md`: 상세 파싱용 데이터 소스
4. `data/nemo_items.sqlite`: 수집된 매물 데이터베이스

## 로컬 실행 방법
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud 배포 방법
1. GitHub 리포지토리에 위 파일들을 업로드합니다.
2. [Streamlit Cloud](https://share.streamlit.io/)에 접속하여 해당 리포지토리를 연결합니다.
3. Main file path를 `app.py`로 설정하여 배포합니다.
