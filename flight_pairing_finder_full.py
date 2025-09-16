import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta

st.set_page_config(page_title="Flight Pairing Finder", layout="wide")
st.title("Flight Pairing Finder")
st.write("Upload your flight pairings CSV and filter/sort to find your ideal trip. All options from the original script included.")

# --- File Upload ---
csv_file = st.file_uploader("Upload your flight pairings CSV", type=["csv"])
if csv_file is None:
    st.info("Please upload a CSV file to begin.")
    st.stop()

# --- Data Loading and Processing Function ---
@st.cache_data
def parse_flight_pairings_csv(csv_file):
    df = pd.read_csv(csv_file)
    required_cols = ['Pairing', 'Departure', 'Arrival', 'Block hours', 'Pairing details', 'Duration']
    if not all(col in df.columns for col in required_cols):
        st.error(f"CSV is missing required columns: {', '.join([col for col in required_cols if col not in df.columns])}")
        return pd.DataFrame()
    # Parse datetimes and block hours
    df['Departure'] = pd.to_datetime(df['Departure'], format='%b %d,%Y %H:%M', errors='coerce')
    df['Arrival'] = pd.to_datetime(df['Arrival'], format='%b %d,%Y %H:%M', errors='coerce')
    df['Block hours'] = pd.to_timedelta(df['Block hours'].astype(str) + ':00', errors='coerce')
    df['Departure Day'] = df['Departure'].dt.day_name().str.lower()
    df['Arrival Day'] = df['Arrival'].dt.day_name().str.lower()
    # Calculate Roundtrips
    def count_roundtrips(pairing_details):
        if pd.isna(pairing_details):
            return 0
        airport_list = [a.strip() for a in pairing_details.split('-')]
        home_base = 'PTY'
        pty_count_after_first = 0
        found_first_pty = False
        for airport in airport_list:
            if airport == home_base:
                if found_first_pty:
                    pty_count_after_first += 1
                else:
                    found_first_pty = True
        return pty_count_after_first
    df['Roundtrips'] = df['Pairing details'].astype(str).apply(count_roundtrips)
    # Calculate Actual Flights per Day
    def calculate_actual_flights_per_day(row):
        pairing_details = row['Pairing details']
        duration = row['Duration']
        if pd.isna(pairing_details) or pd.isna(duration) or duration == 0:
            return 0.0
        num_segments = pairing_details.count('-') + 1
        return num_segments / duration
    df['Actual Flights per Day'] = df.apply(calculate_actual_flights_per_day, axis=1)
    # Pairing Duration Days
    df['Pairing Duration Days'] = pd.to_numeric(df['Duration'], errors='coerce')
    # Block Hours per Pairing Day
    df['Block Hours per Pairing Day'] = df.apply(
        lambda row: (row['Block hours'].total_seconds() / 3600) / row['Pairing Duration Days']
        if pd.notna(row['Block hours']) and pd.notna(row['Pairing Duration Days']) and row['Pairing Duration Days'] > 0 else 0, axis=1)
    # Block hours total (in hours)
    df['Block hours total'] = df['Block hours'].dt.total_seconds() / 3600
    # Boosted Hours (weekend or Panama holiday)
    holidays_2025 = [
        datetime(2025, 1, 1), datetime(2025, 3, 4), datetime(2025, 4, 18), datetime(2025, 5, 1),
        datetime(2025, 11, 3), datetime(2025, 11, 4), datetime(2025, 11, 5), datetime(2025, 11, 10),
        datetime(2025, 11, 28), datetime(2025, 12, 8), datetime(2025, 12, 25)
    ]
    holidays_dt = pd.to_datetime(holidays_2025).normalize()
    def calc_boosted(row):
        dep = row['Departure']
        arr = row['Arrival']
        block_td = row['Block hours']
        if pd.isna(dep) or pd.isna(arr) or pd.isna(block_td):
            return 0.0
        total_duration_hours = block_td.total_seconds() / 3600
        boosted = 0.0
        # Departure day
        if dep.dayofweek >= 5:
            end_dep_day = dep.replace(hour=23, minute=59, second=59)
            boosted += max(timedelta(0), min(arr, end_dep_day) - dep).total_seconds() / 3600
        # Arrival day (if different)
        if arr.dayofweek >= 5 and arr.date() != dep.date():
            start_arr_day = arr.replace(hour=0, minute=0, second=0)
            boosted += max(timedelta(0), arr - max(dep, start_arr_day)).total_seconds() / 3600
        # Full weekend days in between
        current_day = (dep + timedelta(days=1)).normalize()
        while current_day < arr.normalize():
            if current_day.dayofweek >= 5:
                boosted += 24
            current_day += timedelta(days=1)
        # Holidays
        current_day = dep.normalize()
        while current_day <= arr.normalize():
            if current_day in holidays_dt:
                start_of_day = current_day.replace(hour=0, minute=0, second=0)
                end_of_day = current_day.replace(hour=23, minute=59, second=59)
                overlap_start = max(dep, start_of_day)
                overlap_end = min(arr, end_of_day)
                if overlap_start < overlap_end:
                    boosted += (overlap_end - overlap_start).total_seconds() / 3600
            current_day += timedelta(days=1)
        return min(boosted, total_duration_hours)
    df['Boosted Hours'] = df.apply(calc_boosted, axis=1)
    return df

df = parse_flight_pairings_csv(csv_file)
if df.empty:
    st.warning("No data to display.")
    st.stop()

# --- Sidebar: Filters ---
st.sidebar.header("Filter & Sort Preferences")

# Specific Departure/Arrival Dates
departure_dates = pd.Series(df['Departure'].dt.date.dropna().unique()).sort_values()
specific_departure_date = st.sidebar.selectbox("Specific departure date", options=["Any"] + departure_dates.astype(str).tolist())
arrival_dates = pd.Series(df['Arrival'].dt.date.dropna().unique()).sort_values()
specific_arrival_date = st.sidebar.selectbox("Specific arrival date", options=["Any"] + arrival_dates.astype(str).tolist())

# Exclude specific dates (FIXED)
all_dates = pd.concat([df['Departure'].dt.date, df['Arrival'].dt.date]).dropna().unique()
all_dates = pd.Series(all_dates).sort_values()
excluded_dates = st.sidebar.multiselect(
    "Exclude specific dates (departure or arrival)", options=all_dates.astype(str).tolist()
)

# Preferred departure/arrival weekday
all_weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
preferred_departure_weekday = st.sidebar.selectbox("Preferred departure weekday", ["Any"] + [d.capitalize() for d in all_weekdays])
preferred_arrival_weekday = st.sidebar.selectbox("Preferred arrival weekday", ["Any"] + [d.capitalize() for d in all_weekdays])

# Preferred weekdays for all days in pairing
preferred_weekdays = st.sidebar.multiselect("Preferred weekdays (all days in pairing)", [d.capitalize() for d in all_weekdays])

# Earliest departure/arrival time
earliest_departure = st.sidebar.time_input("Earliest departure time", value=None)
earliest_arrival = st.sidebar.time_input("Earliest arrival time", value=None)

# Numeric filters
min_duration = st.sidebar.number_input("Minimum block hours", min_value=0.0, value=0.0, help="Total block hours (duration) minimum")
max_duration = st.sidebar.number_input("Maximum block hours", min_value=0.0, value=0.0, help="Total block hours (duration) maximum (0 = no limit)")
max_roundtrips = st.sidebar.number_input("Maximum roundtrips", min_value=0, value=0)
max_actual_flights_per_day = st.sidebar.number_input("Max actual flights per day", min_value=0.0, value=0.0)
min_block_hours_per_day = st.sidebar.number_input("Min block hours per pairing day", min_value=0.0, value=0.0)

# Sorting
sort_column = st.sidebar.selectbox(
    "Sort by",
    options=[
        'Departure', 'Arrival', 'Block hours total', 'Boosted Hours',
        'Block Hours per Pairing Day', 'Roundtrips', 'Actual Flights per Day'
    ], index=0)
sort_ascending = st.sidebar.checkbox("Sort ascending", value=False)

# --- Filtering ---
filtered_df = df.copy()

# Specific departure/arrival date
if specific_departure_date != "Any":
    filtered_df = filtered_df[filtered_df['Departure'].dt.date.astype(str) == specific_departure_date]
if specific_arrival_date != "Any":
    filtered_df = filtered_df[filtered_df['Arrival'].dt.date.astype(str) == specific_arrival_date]

# Exclude dates
if excluded_dates:
    filtered_df = filtered_df[
        ~filtered_df['Departure'].dt.date.astype(str).isin(excluded_dates) &
        ~filtered_df['Arrival'].dt.date.astype(str).isin(excluded_dates)
    ]

# Preferred departure or arrival weekday
if preferred_departure_weekday != "Any":
    filtered_df = filtered_df[filtered_df['Departure Day'] == preferred_departure_weekday.lower()]
if preferred_arrival_weekday != "Any":
    filtered_df = filtered_df[filtered_df['Arrival Day'] == preferred_arrival_weekday.lower()]

# Preferred weekdays for all days in pairing
if preferred_weekdays:
    def all_days_in(row):
        days = pd.date_range(row['Departure'], row['Arrival']).day_name().str.lower().unique()
        return all(d in [w.lower() for w in preferred_weekdays] for d in days)
    filtered_df = filtered_df[filtered_df.apply(all_days_in, axis=1)]

# Earliest departure/arrival time
if earliest_departure is not None:
    filtered_df = filtered_df[filtered_df['Departure'].dt.time >= earliest_departure]
if earliest_arrival is not None:
    filtered_df = filtered_df[filtered_df['Arrival'].dt.time >= earliest_arrival]

# Numeric filters
if min_duration > 0:
    filtered_df = filtered_df[filtered_df['Block hours total'] >= min_duration]
if max_duration > 0:
    filtered_df = filtered_df[filtered_df['Block hours total'] <= max_duration]
if max_roundtrips > 0:
    filtered_df = filtered_df[filtered_df['Roundtrips'] <= max_roundtrips]
if max_actual_flights_per_day > 0:
    filtered_df = filtered_df[filtered_df['Actual Flights per Day'] <= max_actual_flights_per_day]
if min_block_hours_per_day > 0:
    filtered_df = filtered_df[filtered_df['Block Hours per Pairing Day'] >= min_block_hours_per_day]

# Sorting
if sort_column in filtered_df.columns:
    if pd.api.types.is_timedelta64_dtype(filtered_df[sort_column]):
        filtered_df = filtered_df.assign(_sort_col=filtered_df[sort_column].dt.total_seconds())
        filtered_df = filtered_df.sort_values(by="_sort_col", ascending=sort_ascending).drop(columns=["_sort_col"])
    else:
        filtered_df = filtered_df.sort_values(by=sort_column, ascending=sort_ascending)

st.success(f"Found {len(filtered_df)} matching pairings.")

# --- Results Table ---
display_cols = [
    'Pairing', 'Departure', 'Arrival', 'Block hours', 'Pairing details',
    'Block hours total', 'Boosted Hours', 'Block Hours per Pairing Day',
    'Roundtrips', 'Actual Flights per Day'
]
display_cols = [col for col in display_cols if col in filtered_df.columns]
st.dataframe(filtered_df[display_cols])

# --- Download Option ---
csv = filtered_df.to_csv(index=False)
st.download_button("Download filtered results as CSV", csv, file_name="filtered_pairings.csv", mime="text/csv")
