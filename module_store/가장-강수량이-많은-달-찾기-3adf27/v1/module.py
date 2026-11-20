import pandas as pd

MANIFEST = {
    "title": "가장 강수량이 많은 달 찾기",
    "description": "월별 강수량 데이터에서 가장 강수량이 많은 달을 찾는다.",
    "tags": ["precipitation", "monthly", "max"],
    "input_roles": {
        "monthly_precipitation": {
            "month": "date",
            "total_precipitation": "float"
        }
    },
    "params": {},
    "outputs": ["max_precipitation_month"],
}

def run(inputs, params) -> dict:
    df = inputs["monthly_precipitation"]
    
    # Find the month with the maximum precipitation
    max_precipitation_row = df.loc[df['total_precipitation'].idxmax()]
    max_precipitation_month = max_precipitation_row['month']
    
    return {"max_precipitation_month": {"month": max_precipitation_month}}

def check(outputs, inputs) -> list[str]:
    errors = []
    df = inputs["monthly_precipitation"]
    
    if df.empty:
        raise DataProblem("입력 데이터가 비었습니다.")
    
    if df['total_precipitation'].isnull().any():
        errors.append("강수량 데이터에 결측치가 있습니다.")
    
    if df['total_precipitation'].max() <= 0:
        errors.append("강수량 데이터가 유효하지 않습니다. 모든 값이 0 이하입니다.")
    
    return errors