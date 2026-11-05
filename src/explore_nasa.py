import pandas as pd
from pathlib import Path

# Project data directory
DATA_DIR = Path("data/raw")

stations = [
    "01646500",
    "02087500",
    "07010000",
    "08158000"
]

for station in stations:

    file_path = DATA_DIR / f"nasa_power_{station}.csv"

    print("\n" + "=" * 60)
    print(f"EXPLORING STATION: {station}")
    print("=" * 60)

    # Skip NASA metadata and read actual tabular data
    df = pd.read_csv(file_path, skiprows=14)

    print("\nDataset Shape:")
    print(df.shape)

    print("\nColumn Names:")
    print(df.columns.tolist())

    print("\nFirst 5 Records:")
    print(df.head())

    print("\nData Types:")
    print(df.dtypes)

    print("\nMissing Values:")
    print(df.isnull().sum())

    # NASA POWER uses -999 as a source-data missing-value indicator.
    missing_indicator_counts = df.eq(-999).sum()
    if len(df) > 0:
        missing_indicator_percentages = missing_indicator_counts.div(len(df)).mul(100)
    else:
        missing_indicator_percentages = missing_indicator_counts.astype(float)

    print(f"\nNASA POWER -999 Values for Station {station}:")
    print("Count per column:")
    print(missing_indicator_counts.to_string())

    print(f"\nNASA POWER -999 Percentage for Station {station}:")
    print(missing_indicator_percentages.map(lambda value: f"{value:.2f}%").to_string())

    # Report ordinary Pandas nulls separately from NASA's -999 indicator.
    null_counts = df.isnull().sum()
    print(f"\nPandas null values for Station {station}:")
    print(null_counts.to_string())

    # Exclude date components so the list identifies weather parameter columns.
    date_columns = {"YEAR", "MO", "DY", "DATE"}
    weather_parameter_columns = [
        column
        for column in df.columns
        if str(column).strip().upper() not in date_columns
    ]
    parameters_with_missing_values = [
        column
        for column in weather_parameter_columns
        if missing_indicator_counts[column] > 0 or null_counts[column] > 0
    ]
    print(f"\nWeather parameters with missing values for Station {station}:")
    if parameters_with_missing_values:
        print(parameters_with_missing_values)
    else:
        print("None identified.")

    print("\nStatistical Summary:")
    print(df.describe())

    print("\nDuplicate Records:")
    print(df.duplicated().sum())