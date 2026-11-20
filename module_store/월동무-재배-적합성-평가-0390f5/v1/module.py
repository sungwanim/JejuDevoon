import pandas as pd
import jejukit

MANIFEST = {
    "title": "월동무 재배 적합성 평가",
    "description": "선택된 위치의 기후 조건을 분석하여 월동무 재배에 적합한지 평가합니다.",
    "tags": ["climate", "agriculture", "suitability"],
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
    "outputs": ["suitability_assessment"],
}

def run(inputs, params) -> dict:
    df = inputs["jeju_weather_daily"]
    
    # Ensure date is in datetime format
    df['date'] = jejukit.parse_dates(df['date'])
    
    # Filter for the winter months (December, January, February)
    winter_months = df[df['date'].dt.month.isin([12, 1, 2])]
    
    # Calculate average temperature and total precipitation for winter months
    winter_stats = winter_months.groupby(['station', 'station_name', 'lat', 'lon', 'elevation']).agg(
        avg_tmean=('tmean', 'mean'),
        total_precip=('precip', 'sum')
    ).reset_index()
    
    # Define suitability criteria
    suitable_temp_range = (0, 10)  # Example temperature range in Celsius
    max_precipitation = 100  # Example maximum precipitation in mm
    
    # Evaluate suitability
    winter_stats['suitable'] = (
        (winter_stats['avg_tmean'] >= suitable_temp_range[0]) &
        (winter_stats['avg_tmean'] <= suitable_temp_range[1]) &
        (winter_stats['total_precip'] <= max_precipitation)
    )
    
    # Prepare the output
    suitability_assessment = winter_stats[['station', 'station_name', 'lat', 'lon', 'elevation', 'suitable']]
    
    # Convert DataFrame to dict
    suitability_assessment_dict = suitability_assessment.to_dict(orient='list')
    
    return {"suitability_assessment": suitability_assessment_dict}

def check(outputs, inputs) -> list[str]:
    errors = []
    df = pd.DataFrame(outputs["suitability_assessment"])
    
    # Check for empty results
    if df.empty:
        errors.append("No data available for suitability assessment.")
    
    # Check for missing values
    if df.isnull().any().any():
        errors.append("Missing values found in the suitability assessment results.")
    
    # Check for reasonable values
    if not df['suitable'].isin([True, False]).all():
        errors.append("Unexpected values in 'suitable' column.")
    
    return errors
