from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAILY_PATH = PROJECT_ROOT / "data" / "raw" / "daily.csv"
MONITORING_PATH = PROJECT_ROOT / "data" / "raw" / "monitoring.csv"
RECOMMENDED_STATION_IDS = [
    "USGS-01646500",
    "USGS-07010000",
    "USGS-08158000",
    "USGS-02087500",
    "USGS-14476500",
]


def print_section(title):
    print(f"\n========== {title} ==========")


def print_dataset_overview(name, dataset):
    print_section(f"{name} DATASET OVERVIEW")
    print(f"Shape (rows, columns): {dataset.shape}")
    print("Complete column names:")
    print(dataset.columns.tolist())

    print("\nData types:")
    print(dataset.dtypes.to_string())

    missing_counts = dataset.isna().sum()
    print("\nMissing values per column:")
    print(missing_counts.to_string())
    columns_with_missing_values = missing_counts[missing_counts > 0]
    if columns_with_missing_values.empty:
        print("No missing values found.")
    else:
        print(
            "Data-quality note: missing values occur in "
            f"{len(columns_with_missing_values)} column(s)."
        )


def print_frequency_table(title, values):
    print(f"\n{title}:")
    if values is None:
        print("Unavailable: required column is missing.")
        return
    print(values.value_counts(dropna=False).to_string())


def main():
    daily = pd.read_csv(
        DAILY_PATH,
        dtype={
            "monitoring_location_id": "string",
            "parameter_code": "string",
            "statistic_id": "string",
        },
    )
    monitoring = pd.read_csv(MONITORING_PATH, dtype={"id": "string"})

    print_dataset_overview("DAILY", daily)
    print_dataset_overview("MONITORING", monitoring)

    print_section("STATION COVERAGE")
    monitoring_ids = (
        set(monitoring["id"].dropna().astype(str))
        if "id" in monitoring.columns
        else set()
    )
    daily_station_column = "monitoring_location_id"
    if daily_station_column in daily.columns:
        daily_station_counts = daily[daily_station_column].value_counts(dropna=False)
        print("Daily observation counts per station:")
        print(daily_station_counts.to_string())
        daily_ids = set(daily[daily_station_column].dropna().astype(str))
    else:
        print(f"Unavailable: daily column {daily_station_column!r} is missing.")
        daily_ids = set()

    if monitoring_ids:
        print("\nUnique monitoring station IDs:")
        print(sorted(monitoring_ids))
    elif "id" not in monitoring.columns:
        print("\nUnavailable: monitoring column 'id' is missing.")
    else:
        print("\nNo non-missing monitoring station IDs found.")

    print("\nRecommended hackathon station availability:")
    for station_id in RECOMMENDED_STATION_IDS:
        print(
            f"{station_id}: monitoring.csv="
            f"{'present' if station_id in monitoring_ids else 'missing'}, "
            f"daily.csv={'present' if station_id in daily_ids else 'missing'}"
        )
    all_monitoring_stations_present = set(RECOMMENDED_STATION_IDS).issubset(
        monitoring_ids
    )
    print(
        "All five recommended stations present in monitoring.csv: "
        f"{'yes' if all_monitoring_stations_present else 'no'}"
    )

    print_section("OBSERVATION DATES")
    if "time" in daily.columns:
        parsed_dates = pd.to_datetime(daily["time"], errors="coerce")
        print(f"Minimum observation date: {parsed_dates.min()}")
        print(f"Maximum observation date: {parsed_dates.max()}")
        invalid_or_missing_dates = int(parsed_dates.isna().sum())
        print(f"Missing or unparseable observation dates: {invalid_or_missing_dates}")
        if invalid_or_missing_dates:
            print(
                "Data-quality note: some observation dates are missing or could "
                "not be parsed."
            )
    else:
        print("Unavailable: daily column 'time' is missing.")

    print_section("PARAMETER AND STATISTIC FREQUENCIES")
    parameter_values = daily["parameter_code"] if "parameter_code" in daily else None
    statistic_values = daily["statistic_id"] if "statistic_id" in daily else None
    print_frequency_table("Parameter code frequencies", parameter_values)
    print_frequency_table("Statistic ID frequencies", statistic_values)

    print_section("DAILY MEAN OBSERVATIONS (statistic_id = 00003)")
    if statistic_values is None:
        print("Unavailable: daily column 'statistic_id' is missing.")
    else:
        mean_mask = statistic_values.astype("string").str.strip().eq("00003")
        daily_mean = daily.loc[mean_mask]
        print(f"Matching observations: {len(daily_mean)}")
        inspection_columns = [
            column
            for column in (
                "monitoring_location_id",
                "time",
                "parameter_code",
                "statistic_id",
                "unit_of_measure",
                "value",
            )
            if column in daily_mean.columns
        ]
        if daily_mean.empty:
            print("No observations have statistic_id = 00003.")
        elif inspection_columns:
            print("First five matching observations:")
            print(daily_mean[inspection_columns].head().to_string(index=False))
        else:
            print("Matching rows exist, but no standard inspection columns are available.")

    print_section("DISCHARGE VALUE QUALITY AND UNITS")
    if "parameter_code" in daily.columns:
        discharge_mask = (
            daily["parameter_code"].astype("string").str.strip().eq("00060")
        )
        discharge = daily.loc[discharge_mask]
        print(f"Discharge observations (parameter_code = 00060): {len(discharge)}")

        if "value" in discharge.columns:
            numeric_values = pd.to_numeric(discharge["value"], errors="coerce")
            missing_values = int(discharge["value"].isna().sum())
            non_numeric_values = int(
                (discharge["value"].notna() & numeric_values.isna()).sum()
            )
            zero_values = int(numeric_values.eq(0).sum())
            negative_values = int(numeric_values.lt(0).sum())
            print(f"Missing discharge values: {missing_values}")
            print(f"Non-numeric discharge values: {non_numeric_values}")
            print(f"Zero discharge values: {zero_values}")
            print(f"Negative discharge values: {negative_values}")
            if missing_values or non_numeric_values or negative_values:
                print(
                    "Data-quality note: inspect missing, non-numeric, or negative "
                    "discharge records; no records were changed or removed."
                )
            if zero_values:
                print(
                    "Data-quality note: zero discharge values are present; "
                    "interpret them in the context of the station and dates."
                )
        else:
            print("Unavailable: daily column 'value' is missing.")

        if "unit_of_measure" in discharge.columns:
            print("\nDischarge measurement unit frequencies:")
            print(discharge["unit_of_measure"].value_counts(dropna=False).to_string())
        else:
            print("\nUnavailable: daily column 'unit_of_measure' is missing.")
    else:
        print(
            "Unavailable: cannot isolate discharge without daily column "
            "'parameter_code'."
        )

    print_section("MONITORING STATION COORDINATES")
    latitude_column = next(
        (column for column in ("latitude", "lat", "y") if column in monitoring.columns),
        None,
    )
    longitude_column = next(
        (column for column in ("longitude", "lon", "long", "x") if column in monitoring.columns),
        None,
    )
    coordinate_columns = ["id"] if "id" in monitoring.columns else []
    if latitude_column and longitude_column:
        coordinate_columns.extend([latitude_column, longitude_column])
        print(f"Latitude column: {latitude_column}")
        print(f"Longitude column: {longitude_column}")
        print(monitoring[coordinate_columns].to_string(index=False))
        missing_coordinates = int(
            monitoring[[latitude_column, longitude_column]].isna().any(axis=1).sum()
        )
        print(f"Stations with missing latitude or longitude: {missing_coordinates}")
    else:
        print("Unavailable: latitude/longitude columns were not found.")


if __name__ == "__main__":
    main()
