import pandas as pd

MANIFEST = {
    "title": "채소 가격 데이터 제공 기간 확인",
    "description": "채소 가격 데이터의 제공 기간을 확인하기 위해 두 데이터셋의 거래 기준일 컬럼의 최소 및 최대 날짜를 비교하여 전체 제공 기간을 산출합니다.",
    "tags": ["price"],
    "input_roles": {
        "jdh_agri_daily_trade": {"date": "date"},
        "jdh_agri_trade_moving_avg": {"date": "date"}
    },
    "params": {},
    "outputs": ["vegetable_price_data_period"],
}

def run(inputs, params) -> dict:
    # Extract the date columns from both datasets
    daily_trade_dates = inputs["jdh_agri_daily_trade"]["date"]
    moving_avg_dates = inputs["jdh_agri_trade_moving_avg"]["date"]
    
    # Calculate the overall minimum and maximum dates
    overall_min_date = min(daily_trade_dates.min(), moving_avg_dates.min())
    overall_max_date = max(daily_trade_dates.max(), moving_avg_dates.max())
    
    # Create a result dictionary
    result = {
        "overall_min_date": overall_min_date,
        "overall_max_date": overall_max_date
    }
    
    return {"vegetable_price_data_period": result}

def check(outputs, inputs) -> list[str]:
    errors = []
    result = outputs["vegetable_price_data_period"]
    
    # Check if the result contains valid dates
    if pd.isna(result["overall_min_date"]) or pd.isna(result["overall_max_date"]):
        errors.append("Overall min or max date is NaT.")
    
    # Check if the min date is less than or equal to the max date
    if result["overall_min_date"] > result["overall_max_date"]:
        errors.append("Overall min date is greater than max date.")
    
    return errors