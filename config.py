import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# KAMIS API 설정
# 인증키 발급: https://www.kamis.or.kr/customer/reference/openapi_write.do
KAMIS_API_URL = "http://www.kamis.or.kr/service/price/xml.do"
KAMIS_CERT_KEY = ""  # 발급받은 인증키 입력
KAMIS_CERT_ID = ""   # 발급받은 인증 ID 입력

# 농림축산식품부
MAFRA_URL = "https://www.mafra.go.kr"

# 농식품유통정보센터
ATC_URL = "http://www.atc.go.kr"

# 데이터베이스
DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'prices.db')

# 주요 품목 코드 (KAMIS 실제 코드)
# item_category_code: 100(식량작물), 200(채소류), 300(특용작물), 400(과일류)
# item_code: 품목별 고유코드
# kind_code: 품종코드 (01=대표품종)
# rank_code: 등급코드 (04=상품)
PRODUCT_CODES = {
    '배추': {
        'item_category_code': '200',
        'item_code': '211',
        'kind_code': '01',
        'rank_code': '04',
        'category': '엽경채류',
        'unit': 'kg',
        'icon': '🥬',
    },
    '시금치': {
        'item_category_code': '200',
        'item_code': '214',
        'kind_code': '00',
        'rank_code': '04',
        'category': '엽경채류',
        'unit': 'kg',
        'icon': '🥬',
    },
    '상추': {
        'item_category_code': '200',
        'item_code': '252',
        'kind_code': '01',
        'rank_code': '04',
        'category': '엽경채류',
        'unit': 'kg',
        'icon': '🥬',
    },
    '고추': {
        'item_category_code': '200',
        'item_code': '213',
        'kind_code': '01',
        'rank_code': '04',
        'category': '과채류',
        'unit': 'kg',
        'icon': '🌶️',
    },
    '토마토': {
        'item_category_code': '200',
        'item_code': '225',
        'kind_code': '01',
        'rank_code': '04',
        'category': '과채류',
        'unit': 'kg',
        'icon': '🍅',
    },
    '오이': {
        'item_category_code': '200',
        'item_code': '223',
        'kind_code': '01',
        'rank_code': '04',
        'category': '과채류',
        'unit': 'kg',
        'icon': '🥒',
    },
    '무': {
        'item_category_code': '200',
        'item_code': '232',
        'kind_code': '01',
        'rank_code': '04',
        'category': '근채류',
        'unit': 'kg',
        'icon': '🥕',
    },
    '대파': {
        'item_category_code': '200',
        'item_code': '244',
        'kind_code': '01',
        'rank_code': '04',
        'category': '엽경채류',
        'unit': 'kg',
        'icon': '🧅',
    },
    '양파': {
        'item_category_code': '200',
        'item_code': '246',
        'kind_code': '01',
        'rank_code': '04',
        'category': '근채류',
        'unit': 'kg',
        'icon': '🧅',
    },
    '감자': {
        'item_category_code': '100',
        'item_code': '152',
        'kind_code': '01',
        'rank_code': '04',
        'category': '근채류',
        'unit': 'kg',
        'icon': '🥔',
    },
    '사과': {
        'item_category_code': '400',
        'item_code': '411',
        'kind_code': '01',
        'rank_code': '04',
        'category': '과일류',
        'unit': 'kg',
        'icon': '🍎',
    },
}

# 지역 코드 (KAMIS)
COUNTRY_CODES = {
    '서울': '1101',
    '부산': '2100',
    '대구': '2200',
    '인천': '2300',
    '광주': '2401',
    '대전': '2501',
    '울산': '2601',
}

# 예측 설정
FORECAST_DAYS = {
    '1주일': 7,
    '2주일': 14,
    '1개월': 30,
    '3개월': 90,
}

SECRET_KEY = 'vegetable-price-predictor-2021'
DEBUG = True
