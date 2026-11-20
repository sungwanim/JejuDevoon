import pandas as pd
import jejukit

MANIFEST = {
    "title": "2024년 제주 지역의 월별 강수량 계산",
    "description": "2024년 제주 지역의 일별 강수량 데이터를 이용하여 월별로 강수량을 합산한다.",
    "tags": ["precipitation", "monthly", "Jeju"],
    "input_roles": {
        "jeju_weather_daily": {
            "station": "str",
            "station_name": "str",
            "lat": "float",
            "lon": "float",
            "elevation": "float",
            "date": "date",
            "tmean": "float",
            "tmin": "float",
            "tmax": "float",
            "precip": "float"
        }
    },
    "params": {},
    "outputs": ["monthly_precipitation"],
}

def run(inputs, params) -> dict:
    df = inputs["jeju_weather_daily"]
    
    # 필수 컬럼이 비어있는지 확인
    if df.empty:
        raise DataProblem("입력 데이터가 비어 있습니다.")
    
    # 날짜 컬럼을 datetime으로 변환
    df['date'] = jejukit.parse_dates(df['date'])
    
    # 강수량 컬럼을 float로 변환
    df['precip'] = jejukit.to_numeric(df['precip'])
    
    # 월별로 강수량 합산
    monthly_precip = jejukit.resample(
        df,
        date_col='date',
        freq='MS',
        agg={'precip': 'sum'}
    )
    
    # 결과 데이터프레임 생성
    result = pd.DataFrame({
        'month': monthly_precip['date'],
        'total_precipitation': monthly_precip['precip']
    })
    
    return {"monthly_precipitation": result}

def check(outputs, inputs) -> list[str]:
    problems = []
    result = outputs["monthly_precipitation"]
    
    # 결과가 비어 있는지 확인
    if result.empty:
        problems.append("결과 데이터프레임이 비어 있습니다.")
    
    # 강수량이 음수인 경우 확인
    if (result['total_precipitation'] < 0).any():
        problems.append("강수량이 음수인 값이 있습니다.")
    
    return problems
