from pathlib import Path

import pandas as pd


# Resolve input and output files from this script's project location.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DAILY_PATH = PROJECT_ROOT / "data" / "raw" / "daily.csv"
PROCESSED_PATH = PROJECT_ROOT / "data" / "processed" / "usgs_daily_mean.csv"


def main():
    # Read the source data without converting station IDs or zero-padded codes.
    daily = pd.read_csv(
        RAW_DAILY_PATH,
        dtype={
            "monitoring_location_id": "string",
            "parameter_code": "string",
            "statistic_id": "string",
        },
    )

    # Report the actual input schema before checking the columns used below.
    print("Raw daily dataset columns:")
    print(daily.columns.tolist())
    required_columns = {
        "monitoring_location_id",
        "parameter_code",
        "statistic_id",
        "time",
        "value",
        "unit_of_measure",
    }
    missing_columns = required_columns.difference(daily.columns)
    if missing_columns:
        raise ValueError(
            "The raw daily dataset is missing required columns: "
            f"{sorted(missing_columns)}"
        )

    # Select only daily mean discharge records; retain all source columns and rows
    # that meet both code conditions.
    filtered = daily.loc[
        daily["parameter_code"].eq("00060")
        & daily["statistic_id"].eq("00003")
    ].copy()

    print("\n========== FILTERED USGS DAILY MEAN DISCHARGE ==========")
    print(f"Original number of rows: {len(daily)}")
    print(f"Number of filtered rows: {len(filtered)}")

    # Summarize station coverage, observation dates, and repeated station-date keys.
    station_column = "monitoring_location_id"
    station_ids = sorted(filtered[station_column].dropna().unique().tolist())
    print(f"Unique station IDs: {station_ids}")
    print(f"Number of unique stations: {len(station_ids)}")

    observation_dates = pd.to_datetime(filtered["time"], errors="coerce")
    if observation_dates.notna().any():
        print(f"Date range: {observation_dates.min()} to {observation_dates.max()}")
    else:
        print("Date range: unavailable (no parseable observation dates)")
    invalid_dates = int(observation_dates.isna().sum())
    print(f"Missing or unparseable observation dates: {invalid_dates}")

    station_date_columns = [station_column, "time"]
    duplicate_rows = filtered.duplicated(station_date_columns, keep=False)
    duplicate_combinations = filtered.loc[
        duplicate_rows, station_date_columns
    ].drop_duplicates()
    extra_duplicate_rows = int(
        filtered.duplicated(station_date_columns, keep="first").sum()
    )
    print(
        "Duplicate station-date combinations: "
        f"{len(duplicate_combinations)} "
        f"({extra_duplicate_rows} additional duplicate row(s))"
    )

    # Convert discharge values only in memory to report numeric quality and summary
    # statistics; the source CSV and selected records are not cleaned or modified.
    numeric_discharge = pd.to_numeric(filtered["value"], errors="coerce")
    missing_discharge = int(numeric_discharge.isna().sum())
    nonnumeric_discharge = int(
        (filtered["value"].notna() & numeric_discharge.isna()).sum()
    )
    print(f"Missing discharge values: {missing_discharge}")
    print(f"Non-numeric discharge values: {nonnumeric_discharge}")
    if numeric_discharge.notna().any():
        print(f"Minimum discharge: {numeric_discharge.min()}")
        print(f"Maximum discharge: {numeric_discharge.max()}")
        print(f"Mean discharge: {numeric_discharge.mean()}")
        print(f"Median discharge: {numeric_discharge.median()}")
    else:
        print("Discharge statistics: unavailable (no numeric values)")

    # Show each station's filtered observation count and the reported units.
    print("\nNumber of observations per station:")
    if filtered.empty:
        print("No matching observations.")
    else:
        print(filtered[station_column].value_counts(dropna=False).sort_index().to_string())

    print("\nDischarge units:")
    unit_counts = filtered["unit_of_measure"].value_counts(dropna=False)
    if unit_counts.empty:
        print("No units available.")
    else:
        print(unit_counts.to_string())

    # Write only the filtered observations to the requested processed-data path.
    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(PROCESSED_PATH, index=False)
    print(f"\nFiltered dataset saved to: {PROCESSED_PATH}")


if __name__ == "__main__":
    main()
