import pandas as pd
from jejukit import to_numeric

MANIFEST = {
    "title": "소음도가 가장 높은 측정소 찾기",
    "description": "제주공항 소음측정소 중에서 소음도가 가장 높은 측정소를 찾는다.",
    "tags": ["noise", "airport", "jeju"],
    "input_roles": {
        "jeju_airport_noise": {
            "year": "str",
            "quarter": "str",
            "airport": "str",
            "station_name": "str",
            "noise_level": "float"
        }
    },
    "params": {},
    "outputs": ["max_noise_station"],
}

def run(inputs, params) -> dict:
    df = inputs["jeju_airport_noise"].copy()
    
    # Convert noise level to numeric, treating 0 as missing
    df["noise_level"] = to_numeric(df["noise_level"], zero_is_missing=True)
    
    # Drop rows with missing noise levels
    df = df.dropna(subset=["noise_level"])
    
    # Check if the dataframe is empty after dropping missing values
    if df.empty:
        raise DataProblem("No valid noise level data available.")
    
    # Find the station with the maximum noise level
    max_noise_row = df.loc[df["noise_level"].idxmax()]
    max_noise_station = {
        "station_name": max_noise_row["station_name"],
        "noise_level": max_noise_row["noise_level"]
    }
    
    return {"max_noise_station": max_noise_station}

def check(outputs, inputs) -> list[str]:
    problems = []
    max_noise_station = outputs["max_noise_station"]
    
    # Check if the output is empty
    if not max_noise_station:
        problems.append("Output is empty.")
    
    # Check for missing values in the output
    if pd.isnull(max_noise_station["station_name"]) or pd.isnull(max_noise_station["noise_level"]):
        problems.append("Missing values in the output.")
    
    # Check if noise level is within expected range
    if not (49.0 <= max_noise_station["noise_level"] <= 87.0):
        problems.append("Noise level is out of expected range.")
    
    return problems