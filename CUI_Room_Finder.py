
# ============================================================
# CUI FREE ROOM FINDER
# Find classrooms and labs that are free at COMSATS Lahore.
# ============================================================

# Step 1: Import the required libraries.
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup


# Step 2: Configure the Streamlit application.
st.set_page_config(
    page_title="CUI Free Room Finder",
    page_icon="🏫",
    layout="wide",
)

# Step 3: Define the official timetable URL.
BASE_URL = "https://sfs.cuilahore.edu.pk/schedule/Public/Timetable"

# Step 4: Define the days used by the timetable.
DAYS = {
    "Mo": "Monday",
    "Tu": "Tuesday",
    "We": "Wednesday",
    "Th": "Thursday",
    "Fr": "Friday",
    "Sa": "Saturday",
    "Su": "Sunday",
}

# Step 5: Define the timetable's 30-minute grid.
DAY_START = 8 * 60 + 30
SLOT_DURATION = 30
SLOT_COUNT = 24
DAY_END = DAY_START + SLOT_DURATION * SLOT_COUNT

# Step 6: Prepare the available time choices.
def format_time(minutes):
    # Convert minutes after midnight into a 12-hour time string.
    hour = (minutes // 60) % 24
    minute = minutes % 60
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


TIME_OPTIONS = [
    format_time(DAY_START + i * SLOT_DURATION)
    for i in range(SLOT_COUNT + 1)
]


# Step 7: Create a reusable HTTP session configuration.
def make_request(url, params):
    # Download a timetable page with a browser-like user agent.
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )

    # Stop if the server returns an unsuccessful status code.
    response.raise_for_status()
    return response


# Step 8: Fetch the room list from the website automatically.
@st.cache_data(ttl=300)
def get_room_list():
    # Request the public room timetable page.
    response = make_request(
        BASE_URL,
        {"Kind": "room", "Who": "A-2"},
    )

    # Find the JavaScript array that contains room names.
    match = re.search(
        r"\b(?:var|let|const)\s+all\s*=\s*(\[[\s\S]*?\])\s*;",
        response.text,
    )

    # Stop if the page format has changed.
    if not match:
        raise ValueError(
            "Room list not found. The university website may have changed."
        )

    # Convert the room-list JSON into a Python list.
    rooms = json.loads(match.group(1))

    # Remove empty values and duplicate names.
    rooms = sorted({
        room.strip()
        for room in rooms
        if isinstance(room, str) and room.strip()
    })

    # Return the complete list of room names.
    return rooms


# Step 9: Download and parse the schedule for one room.
@st.cache_data(ttl=300)
def fetch_room_schedule(room):
    # Request the timetable for the selected room.
    response = make_request(
        BASE_URL,
        {"Kind": "room", "Who": room},
    )

    # Parse the returned HTML.
    soup = BeautifulSoup(response.text, "html.parser")
    grid = soup.select_one("table.grid")

    # Make sure a timetable grid exists.
    if grid is None:
        raise ValueError(f"Timetable grid not found for {room}")

    # Store the schedule for each weekday.
    schedule = {}

    # Read every row that represents a day.
    for row in grid.find_all("tr"):
        day_cell = row.find(["th", "td"], class_="daycol")

        # Skip header rows that do not represent a weekday.
        if day_cell is None:
            continue

        day_code = day_cell.get_text(strip=True)

        # Skip any unknown day codes.
        if day_code not in DAYS:
            continue

        # Initially mark every half-hour as unknown/free.
        occupied = [False] * SLOT_COUNT
        details = [""] * SLOT_COUNT
        slot_index = 0

        # Read the timetable cells belonging directly to this row.
        cells = row.find_all("td", class_="slot", recursive=False)

        for cell in cells:
            # A cell may cover several half-hour slots.
            span = int(cell.get("colspan", 1))
            text = cell.get_text(" ", strip=True)
            classes = cell.get("class", [])

            # Scheduled classes and special breaks are unavailable.
            is_busy = bool(text) or "brk" in classes

            # Apply the cell's status to every slot it covers.
            for offset in range(span):
                index = slot_index + offset

                if index < SLOT_COUNT:
                    occupied[index] = is_busy
                    details[index] = text

            # Move forward by the number of slots covered.
            slot_index += span

        # Accept only rows covering the complete timetable grid.
        if slot_index == SLOT_COUNT:
            schedule[DAYS[day_code]] = {
                "occupied": occupied,
                "details": details,
            }

    # Do not silently treat an unreadable schedule as free.
    if not schedule:
        raise ValueError(f"No complete daily schedule found for {room}")

    return schedule


# Step 10: Convert a displayed time into minutes after midnight.
def parse_time(time_text):
    # Parse times such as 1:00 PM and 8:30 AM correctly.
    parsed = datetime.strptime(time_text, "%I:%M %p")
    return parsed.hour * 60 + parsed.minute


# Step 11: Check whether a room is free for the complete period.
def check_room(room, day, start_minutes, end_minutes):
    # Fetch the room's published schedule.
    schedule = fetch_room_schedule(room)

    # Skip rooms that do not have a schedule for the chosen day.
    if day not in schedule:
        return None

    # Get the selected day's occupancy information.
    day_schedule = schedule[day]
    occupied = day_schedule["occupied"]

    # Convert the selected period into half-hour slot indices.
    start_index = (start_minutes - DAY_START) // SLOT_DURATION
    end_index = (end_minutes - DAY_START) // SLOT_DURATION

    # Check every slot; one busy slot makes the room unavailable.
    for index in range(start_index, end_index):
        if occupied[index]:
            return None

    # Return the room only when the entire interval is free.
    return {
        "Room": room,
        "Day": day,
        "Available From": format_time(start_minutes),
        "Available Until": format_time(end_minutes),
        "Status": "Free",
    }


# Step 12: Display the app heading.
st.title("🏫 CUI Free Room Finder")

st.write(
    "Find available classrooms and laboratories using the "
    "published COMSATS University Lahore timetable."
)

st.caption(
    "The app checks the university's published schedule. "
    "A room shown as free may still be reserved or inaccessible."
)

# Step 13: Add a refresh control to clear cached timetable data.
with st.sidebar:
    st.header("Settings")
    st.write("Timetable data is cached for five minutes.")

    if st.button("🔄 Refresh timetable data", use_container_width=True):
        get_room_list.clear()
        fetch_room_schedule.clear()
        st.rerun()

    st.divider()
    st.write("**Timetable hours**")
    st.write("8:30 AM – 8:30 PM")
    st.write("Slot length: 30 minutes")

st.divider()

# Step 14: Create the day, start-time, and end-time selectors.
col1, col2, col3 = st.columns(3)

with col1:
    selected_day = st.selectbox(
        "Select day",
        list(DAYS.values()),
        index=0,
    )

with col2:
    start_time = st.selectbox(
        "Start time",
        TIME_OPTIONS[:-1],
        index=9,
    )

with col3:
    end_time = st.selectbox(
        "End time",
        TIME_OPTIONS[1:],
        index=11,
    )

# Step 15: Let users choose which types of rooms to search.
room_category = st.radio(
    "Room category",
    ["All rooms", "Classrooms", "Labs"],
    horizontal=True,
)

# Step 16: Explain the chosen time range.
st.info(
    f"Search period: **{start_time} to {end_time}** on **{selected_day}**."
)

# Step 17: Start the search when the button is pressed.
if st.button(
    "🔍 Find Free Rooms",
    type="primary",
    use_container_width=True,
):
    # Convert selected times into numeric values.
    start_minutes = parse_time(start_time)
    end_minutes = parse_time(end_time)

    # Validate that the selected interval is sensible.
    if start_minutes < DAY_START or end_minutes > DAY_END:
        st.error("Select a time between 8:30 AM and 8:30 PM.")

    elif end_minutes <= start_minutes:
        st.error("End time must be later than start time.")

    elif (
        (start_minutes - DAY_START) % SLOT_DURATION != 0
        or (end_minutes - DAY_START) % SLOT_DURATION != 0
    ):
        st.error("Please select times on 30-minute boundaries.")

    else:
        try:
            # Fetch the room list from the official timetable.
            with st.spinner("Loading the room list..."):
                rooms = get_room_list()

            # Filter rooms by the selected category.
            if room_category == "Classrooms":
                rooms = [
                    room for room in rooms
                    if "lab" not in room.lower()
                ]

            elif room_category == "Labs":
                rooms = [
                    room for room in rooms
                    if "lab" in room.lower()
                ]

            # Prepare containers for successful results and errors.
            free_rooms = []
            errors = []

            # Check rooms concurrently to reduce waiting time.
            with st.spinner(
                f"Checking {len(rooms)} rooms against the timetable..."
            ):
                with ThreadPoolExecutor(max_workers=6) as executor:
                    futures = {
                        executor.submit(
                            check_room,
                            room,
                            selected_day,
                            start_minutes,
                            end_minutes,
                        ): room
                        for room in rooms
                    }

                    # Collect each result as its request finishes.
                    for future in as_completed(futures):
                        room = futures[future]

                        try:
                            result = future.result()

                            if result is not None:
                                free_rooms.append(result)

                        except Exception as error:
                            errors.append({
                                "Room": room,
                                "Error": str(error),
                            })

            # Sort the available rooms alphabetically.
            free_rooms.sort(key=lambda item: item["Room"])

            # Show the results section.
            st.subheader("Search Results")

            st.write(
                f"**{selected_day}: {start_time} – {end_time}**"
            )

            # Show the number of rooms confirmed free.
            st.metric("Rooms confirmed free", len(free_rooms))

            if free_rooms:
                # Convert the results to a table.
                results_df = pd.DataFrame(free_rooms)

                # Display the room list.
                st.dataframe(
                    results_df,
                    use_container_width=True,
                    hide_index=True,
                )

                # Let the user download the room list.
                csv_data = results_df.to_csv(index=False).encode("utf-8")

                st.download_button(
                    label="⬇️ Download results as CSV",
                    data=csv_data,
                    file_name="cui_free_rooms.csv",
                    mime="text/csv",
                )

            else:
                st.warning(
                    "No rooms were confirmed free for this complete period."
                )

            # Show any rooms that could not be checked.
            if errors:
                st.warning(
                    f"{len(errors)} room(s) could not be checked. "
                    "These rooms have not been counted as free."
                )

                with st.expander("View rooms with errors"):
                    st.dataframe(
                        pd.DataFrame(errors),
                        use_container_width=True,
                        hide_index=True,
                    )

            # Show how many rooms were checked successfully.
            checked_count = len(rooms) - len(errors)

            st.caption(
                f"Rooms considered: {len(rooms)} | "
                f"Rooms checked successfully: {checked_count} | "
                f"Rooms with errors: {len(errors)}"
            )

        except Exception as error:
            # Report problems instead of displaying misleading results.
            st.error(f"Unable to complete the search: {error}")

# Step 18: Explain the app's search rules.
with st.expander("ℹ️ How does this app work?"):
    st.markdown(
        """
        1. It fetches the room list from the public university webpage.
        2. It downloads the published timetable for each selected room.
        3. It expands scheduled blocks into 30-minute slots.
        4. It checks every slot in your chosen period.
        5. It displays a room only if every slot is free.
        6. Rooms that fail to load are reported separately, not marked free.

        **Important:** This is a timetable-based finder, not a live sensor
        of whether a room is physically empty, unlocked, or reserved
        outside the published schedule.
        """
    )
