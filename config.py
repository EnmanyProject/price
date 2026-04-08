import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# KAMIS API 설정
# 인증키 발급: https://www.kamis.or.kr/customer/reference/openapi_write.do
KAMIS_API_URL = "http://www.kamis.or.kr/service/price/xml.do"
KAMIS_CERT_KEY = os.environ.get('KAMIS_CERT_KEY', '')
KAMIS_CERT_ID = os.environ.get('KAMIS_CERT_ID', '')

# 가락시장 가격 정보 (키 불필요)
GARAK_BASE_URL = "https://www.garakprice.com"

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

# 가락시장 품목 매핑 (garakprice.com → 우리 품목명)
# keyword: 가락시장 페이지에서 검색할 키워드
# weight_kg: 기준단위의 kg 환산값 (가격을 kg당으로 변환)
# grade: 사용할 등급 (특/상/중)
GARAK_PRODUCT_MAP = {
    '배추': {
        'keyword': '배추',
        'exclude': ['봄동', '얼갈이', '쌈배추', '절임'],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 10,
        'grade': '상',
    },
    '시금치': {
        'keyword': '시금치',
        'exclude': [],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 4,
        'grade': '상',
    },
    '상추': {
        'keyword': '상추',
        'exclude': ['적상추'],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 4,
        'grade': '상',
    },
    '고추': {
        'keyword': '풋고추',
        'exclude': ['청양', '홍고추', '꽈리'],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 10,
        'grade': '상',
    },
    '토마토': {
        'keyword': '토마토',
        'exclude': ['방울', '대추'],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 5,
        'grade': '상',
    },
    '오이': {
        'keyword': '백다다기오이',
        'exclude': [],
        'unit_pattern': r'(\d+)\s*개',
        'default_kg': 5,  # 50개 ≒ 약 5kg 기준 환산
        'grade': '상',
    },
    '무': {
        'keyword': '무',
        'exclude': ['열무', '총각무', '알타리'],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 20,
        'grade': '상',
    },
    '대파': {
        'keyword': '대파',
        'exclude': [],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 1,
        'grade': '상',
    },
    '양파': {
        'keyword': '양파',
        'exclude': ['저장양파'],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 12,
        'grade': '상',
    },
    '감자': {
        'keyword': '감자',
        'exclude': ['저장', '수미'],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 20,
        'grade': '상',
    },
    '사과': {
        'keyword': '사과',
        'exclude': [],
        'unit_pattern': r'(\d+)\s*(?:키로|kg)',
        'default_kg': 10,
        'grade': '상',
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
