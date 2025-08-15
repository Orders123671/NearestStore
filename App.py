import streamlit as st
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
import requests # For making API calls to Google Geocoding
import sqlite3 # New import for SQLite database operations
import os # For managing the database file path

# --- SQLite Database Setup ---
DB_FILE = "stores.db" # Name of your SQLite database file

def init_db():
    """Initializes the SQLite database and creates the stores table if it doesn't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                contact_number TEXT,
                branch_supervisor TEXT,
                store_status TEXT DEFAULT 'Operational', -- New column for store status with a default
                store_hours TEXT, -- New column for store hours
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add columns if they don't exist (for existing databases)
        try:
            cursor.execute("ALTER TABLE stores ADD COLUMN contact_number TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                st.warning(f"Could not add 'contact_number' column (may already exist): {e}")
        try:
            cursor.execute("ALTER TABLE stores ADD COLUMN branch_supervisor TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                st.warning(f"Could not add 'branch_supervisor' column (may already exist): {e}")
        try:
            # Add store_status column, ensuring it has a default if added to existing data
            cursor.execute("ALTER TABLE stores ADD COLUMN store_status TEXT DEFAULT 'Operational'")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                st.warning(f"Could not add 'store_status' column (may already exist): {e}")
        try:
            cursor.execute("ALTER TABLE stores ADD COLUMN store_hours TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                st.warning(f"Could not add 'store_hours' column (may already exist): {e}")
        conn.commit()

# Initialize the database when the app starts
init_db()

# --- Haversine Distance Calculation ---
def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two points on Earth using the Haversine formula.
    Returns distance in kilometers.
    """
    R = 6371  # Radius of Earth in kilometers

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c
    return distance

# --- Function to get coordinates from an address using Google Geocoding API ---
def get_coordinates_from_address(address, api_key_to_use):
    """
    Converts an address to latitude and longitude using Google Maps Geocoding API.
    Returns (latitude, longitude) or None if not found.
    """
    # API key is now loaded from st.secrets, no user input
    if not str(api_key_to_use).strip():
        st.error("Google Maps API Key is not configured. Please set it in your Streamlit secrets as 'GOOGLE_MAPS_API_KEY'.")
        return None, None

    base_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": address,
        "key": api_key_to_use
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        if data["status"] == "OK":
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
        else:
            st.error(f"Error geocoding address: {data['status']}. {data.get('error_message', '')}")
            return None, None
    except requests.exceptions.RequestException as e:
        st.error(f"Network error or invalid API key: {e}")
        return None, None
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return None, None

# --- SQLite Operations for Stores ---
def add_store_to_db(name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours):
    """Adds a new store to SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO stores (name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours))
            conn.commit()
        st.success(f"Store '{name}' added successfully!")
        return True
    except Exception as e:
        st.error(f"Error adding store to database: {e}")
        return False

def update_store_in_db(store_id, name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours):
    """Updates an existing store in SQLite database."""
    print(f"DEBUG: update_store_in_db called for ID: {store_id} (Type: {type(store_id)})")
    print(f"DEBUG: Name: '{name}', Address: '{address}'")
    print(f"DEBUG: Lat: {latitude}, Lon: {longitude}")
    print(f"DEBUG: Contact: '{contact_number}', Supervisor: '{branch_supervisor}'")
    print(f"DEBUG: Status: '{store_status}', Hours: '{store_hours}'")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            # Ensure store_id is an integer for the query
            store_id_int = int(store_id)

            # --- DEBUG: Verify initial DB content before update ---
            cursor.execute("SELECT id, name, address, contact_number, branch_supervisor, store_status, store_hours FROM stores WHERE id = ?", (store_id_int,))
            initial_row = cursor.fetchone()
            if initial_row:
                initial_data = dict(zip(['id', 'name', 'address', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours'], initial_row))
                print(f"DEBUG: Data in DB BEFORE update (ID {store_id_int}): {initial_data}")
            else:
                print(f"DEBUG: Store with ID {store_id_int} NOT FOUND BEFORE update. This indicates a sync issue or DB file was reset.")
                st.error(f"Store with ID {store_id_int} not found in database for update. Please add it again or refresh the page and try editing.")
                return False # Exit if store not found


            cursor.execute("""
                UPDATE stores SET
                    name = ?,
                    address = ?,
                    latitude = ?,
                    longitude = ?,
                    contact_number = ?,
                    branch_supervisor = ?,
                    store_status = ?,
                    store_hours = ?
                WHERE id = ?
            """, (name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, store_id_int))

            # Check how many rows were affected by the UPDATE
            rows_affected = cursor.rowcount
            print(f"DEBUG: Rows affected by UPDATE for ID {store_id_int}: {rows_affected}")

            conn.commit() # Commit the transaction here

            # --- DEBUG: Verify immediate DB content after commit ---
            cursor.execute("SELECT id, name, address, contact_number, branch_supervisor, store_status, store_hours FROM stores WHERE id = ?", (store_id_int,))
            updated_row = cursor.fetchone()
            if updated_row:
                cols_for_debug = ['id', 'name', 'address', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours']
                updated_data = dict(zip(cols_for_debug, updated_row))
                print(f"DEBUG: Data in DB AFTER update (ID {store_id_int}): {updated_data}")
            else:
                print(f"DEBUG: Store with ID {store_id_int} NOT FOUND AFTER update verification (this is unexpected if rows_affected > 0).")
            # --- End DEBUG ---

        if rows_affected > 0:
            st.success(f"Store '{name}' (ID: {store_id_int}) updated successfully!")
            return True
        else:
            # This case means the UPDATE statement executed, but found no matching row or no actual change.
            st.warning(f"Update completed, but no changes were applied to store '{name}' (ID: {store_id_int}). Data might be identical or store not found.")
            return False
    except Exception as e:
        st.error(f"Error updating store in database: {e}")
        print(f"ERROR: Exception during update_store_in_db: {e}")
        return False


def delete_store_from_db(store_id):
    """Deletes a store from SQLite database by its ID."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stores WHERE id = ?", (store_id,))
            conn.commit()
        st.success(f"Store with ID {store_id} deleted successfully!")
        return True
    except Exception as e:
        st.error(f"Error deleting store from database: {e}")
        return False

# Use Streamlit's session state to store stores_df for reactivity
if 'stores_df' not in st.session_state:
    st.session_state.stores_df = pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours', 'timestamp'])
if 'editing_store_id' not in st.session_state:
    st.session_state.editing_store_id = None # Store ID of the store currently being edited
if 'editing_store_details' not in st.session_state:
    st.session_state.editing_store_details = {} # Store details of the store currently being edited

def fetch_stores_from_db():
    """Fetches all stores from SQLite and updates st.session_state.stores_df."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, timestamp FROM stores")
            rows = cursor.fetchall()
            # Get column names from cursor description
            cols = [description[0] for description in cursor.description]
            st.session_state.stores_df = pd.DataFrame(rows, columns=cols)
            if st.session_state.stores_df.empty:
                st.info("No stores found in the database. Add some below!")
    except Exception as e:
        st.error(f"Error fetching stores from database: {e}")

# Call fetch stores once at the beginning to populate the dataframe
fetch_stores_from_db()

# --- Streamlit App Layout ---
st.set_page_config(layout="wide", page_title="Katrina store finder", page_icon="📍")

st.markdown(
    """
    <style>
    /* General body styling for a clean look */
    body {
        font-family: 'Arial', sans-serif;
        background-color: #f8f9fa; /* Light gray background */
        color: #343a40; /* Dark gray text */
    }

    /* Main Header Styling */
    .main-header {
        font-size: 2.8em;
        color: #28a745; /* Vibrant green */
        text-align: center;
        margin-bottom: 25px;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.1);
        padding-top: 20px;
    }

    /* Subheader Styling */
    .subheader {
        font-size: 1.3em;
        color: #495057; /* Slightly darker gray for subheader */
        text-align: center;
        margin-bottom: 40px;
    }

    /* Input Section (Forms) Styling */
    .input-section {
        background-color: #ffffff; /* White background for input sections */
        padding: 30px;
        border-radius: 12px;
        margin-bottom: 40px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1); /* Soft shadow for depth */
        border: 1px solid #e9ecef; /* Light border */
    }

    /* Headers within sections */
    h3 {
        color: #007bff; /* Blue for section headers */
        margin-bottom: 20px;
        border-bottom: 2px solid #007bff;
        padding-bottom: 10px;
    }

    /* Result Card Styling */
    .result-card {
        background-color: #d4edda; /* Light green background for success/result */
        border-left: 6px solid #28a745; /* Stronger green border */
        padding: 25px;
        border-radius: 12px;
        margin-top: 30px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.08);
    }

    /* Store Name in Result Card */
    .store-name {
        font-size: 1.8em;
        font-weight: bold;
        color: #155724; /* Darker green for emphasis */
        margin-bottom: 10px;
    }

    /* Distance and other text in Result Card */
    .distance-text {
        font-size: 1.1em;
        color: #333;
        line-height: 1.6;
    }

    /* Streamlit Button Styling */
    .stButton>button {
        background-color: #007bff; /* Primary blue button */
        color: white;
        border-radius: 8px;
        padding: 12px 25px;
        font-size: 1.1em;
        border: none;
        cursor: pointer;
        transition: background-color 0.3s ease, transform 0.2s ease, box-shadow 0.3s ease;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2); /* Deeper shadow */
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #0056b3; /* Darker blue on hover */
        transform: translateY(-2px); /* Slight lift effect */
        box-shadow: 0 6px 15px rgba(0,0,0,0.3);
    }

    /* Delete Button Specific Styling */
    .delete-button {
        background-color: #dc3545; /* Red */
        color: white;
        border-radius: 6px;
        padding: 8px 15px;
        font-size: 0.95em;
        border: none;
        cursor: pointer;
        transition: background-color 0.3s ease, transform 0.2s ease;
        box-shadow: 0 2px 5px rgba(0,0,0,0.15);
    }
    .delete-button:hover {
        background-color: #c82333; /* Darker red on hover */
        transform: translateY(-1px);
    }

    /* Adjust Streamlit specific elements for better fit */
    .stTextInput>div>div>input, .stSelectbox>div>div>select {
        border-radius: 8px;
        border: 1px solid #ced4da; /* Light gray border */
        padding: 10px;
        font-size: 1em;
    }
    .stTextInput>div>div>input:focus, .stSelectbox>div>div>select:focus {
        border-color: #007bff; /* Blue border on focus */
        box-shadow: 0 0 0 0.2rem rgba(0,123,255,.25);
    }

    /* Info and Warning messages */
    .stAlert {
        border-radius: 8px;
        padding: 15px;
    }
    .stAlert.info {
        background-color: #e2f2ff; /* Light blue for info */
        border-left: 5px solid #007bff;
    }
    .stAlert.warning {
        background-color: #fff3cd; /* Light yellow for warning */
        border-left: 5px solid #ffc107;
    }
    .stAlert.error {
        background-color: #f8d7da; /* Light red for error */
        border-left: 5px solid #dc3545;
    }

    /* Sidebar Navigation */
    .stRadio > label {
        color: #007bff; /* Blue for radio button labels */
        font-weight: bold;
    }
    .stRadio div[role="radiogroup"] {
        background-color: #e9ecef; /* Light gray for radio group background */
        border-radius: 10px;
        padding: 15px;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.05);
    }
    .stRadio div[role="radiogroup"] label {
        margin: 5px 0;
        padding: 8px 12px;
        border-radius: 6px;
        transition: background-color 0.2s ease;
    }
    .stRadio div[role="radiogroup"] label:hover {
        background-color: #dee2e6; /* Darker gray on hover */
    }
    .stRadio div[role="radiogroup"] label[data-baseweb="radio"] div {
        color: #343a40; /* Ensure text color is readable */
    }

    /* Streamlit's "All Saved Stores" table headers */
    div[data-testid="stDataFrame"] .header-row {
        background-color: #007bff; /* Blue header for table */
        color: white;
        font-weight: bold;
    }
    div[data-testid="stDataFrame"] .header-cell {
        padding: 10px 5px;
        border-bottom: 2px solid #0056b3;
    }
    div[data-testid="stDataFrame"] .data-row:nth-child(odd) {
        background-color: #f8f9fa; /* Light gray alternating rows */
    }
    div[data-testid="stDataFrame"] .data-row:nth-child(even) {
        background-color: #ffffff; /* White alternating rows */
    }
    div[data-testid="stDataFrame"] .data-cell {
        padding: 8px 5px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("<h1 class='main-header'>📍 Katrina store finder</h1>", unsafe_allow_html=True)
st.markdown("<p class='subheader'>Find the closest store or add new store locations.</p>", unsafe_allow_html=True)

# --- Navigation ---
page = st.sidebar.radio("Navigation", ["Find Nearest Store", "Add/Edit Store"])
st.sidebar.markdown("---") # Separator in sidebar

# Retrieve API key from Streamlit secrets
try:
    google_api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
except KeyError:
    st.error("Missing Streamlit secret: 'GOOGLE_MAPS_API_KEY'. Please add it to your Streamlit secrets file.")
    google_api_key = "" # Set to empty to prevent errors if not found

# Use a main content container to ensure proper rendering for each page
main_content_placeholder = st.empty()

if page == "Find Nearest Store":
    with main_content_placeholder.container():
        st.markdown("---")
        # --- User Location Input Section ---
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Your Current Location</h3>", unsafe_allow_html=True)

        # Use st.form for "Enter" key submission
        with st.form("search_form"):
            user_address_input = st.text_input("Enter your Address (e.g., 'Burj Khalifa, Dubai')", value="", key="search_address_input")
            find_nearest_button = st.form_submit_button("Find Nearest Store")

        if find_nearest_button:
            user_lat, user_lon = None, None
            if str(user_address_input).strip():
                with st.spinner("Searching for the nearest store..."):
                    user_lat, user_lon = get_coordinates_from_address(user_address_input, google_api_key)
                if user_lat is None or user_lon is None:
                    st.error("Could not get coordinates from the provided address. Please try another address or check your API key.")
            else:
                st.error("Please provide an address to find the nearest store.")

            if user_lat is not None and user_lon is not None:
                nearest_store = None
                min_distance = float('inf')

                # Use stores_df from session_state (populated by SQLite)
                if not st.session_state.stores_df.empty:
                    for index, store in st.session_state.stores_df.iterrows():
                        store_lat = store["latitude"]
                        store_lon = store["longitude"]
                        distance = haversine(user_lat, user_lon, store_lat, store_lon)

                        if distance < min_distance:
                            min_distance = distance
                            nearest_store = store

                    if nearest_store is not None:
                        st.markdown("<div class='result-card'>", unsafe_allow_html=True)
                        st.markdown(f"<p class='store-name'>Nearest Store: {nearest_store['name']}</p>", unsafe_allow_html=True)
                        st.markdown(f"<p class='distance-text'>Distance: {min_distance:.2f} km</p>", unsafe_allow_html=True)
                        st.markdown(f"<p class='distance-text'>Address: {nearest_store['address']}</p>", unsafe_allow_html=True) # Added store address here

                        # Display contact number
                        contact_to_display = nearest_store.get('contact_number')
                        if pd.notnull(contact_to_display) and str(contact_to_display).strip():
                            st.markdown(f"<p class='distance-text'>Contact: {str(contact_to_display).strip()}</p>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<p class='distance-text'>Contact: Not Available</p>", unsafe_allow_html=True)

                        # Display branch supervisor
                        supervisor_to_display = nearest_store.get('branch_supervisor')
                        if pd.notnull(supervisor_to_display) and str(supervisor_to_display).strip():
                            st.markdown(f"<p class='distance-text'>Supervisor: {str(supervisor_to_display).strip()}</p>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<p class='distance-text'>Supervisor: Not Available</p>", unsafe_allow_html=True)

                        # Display store status
                        status_to_display = nearest_store.get('store_status')
                        if pd.notnull(status_to_display) and str(status_to_display).strip():
                            st.markdown(f"<p class='distance-text'>Status: {str(status_to_display).strip()}</p>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<p class='distance-text'>Status: Not Available</p>", unsafe_allow_html=True)

                        # Display store hours
                        hours_to_display = nearest_store.get('store_hours')
                        if pd.notnull(hours_to_display) and str(hours_to_display).strip():
                            st.markdown(f"<p class='distance-text'>Hours: {str(hours_to_display).strip()}</p>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<p class='distance-text'>Hours: Not Available</p>", unsafe_allow_html=True)


                        st.markdown("</div>", unsafe_allow_html=True)
                    else:
                        st.warning("No stores found in the database to compare with. Please add some stores first.")
                else:
                    st.warning("No stores loaded from the database. Please add some stores using the 'Add/Edit Store' page.")

                # --- Prepare data for map (always show map if user location is valid) ---
                if user_lat is not None and user_lon is not None:
                    # Create a DataFrame for the user's location
                    user_location_df = pd.DataFrame([{
                        'latitude': user_lat,
                        'longitude': user_lon,
                        'name': 'Your Location',
                        'size': 200,  # Larger marker for user's location
                        'color': [255, 0, 0] # Red color for user's location
                    }])

                    # Add size and color to store DataFrame for map differentiation
                    stores_df_for_map = st.session_state.stores_df.copy()
                    # Ensure latitude and longitude columns exist before assigning values
                    if not stores_df_for_map.empty and ('latitude' in stores_df_for_map.columns and 'longitude' in stores_df_for_map.columns):
                        stores_df_for_map['size'] = 50 # Smaller marker for stores
                        # Assign a list of lists, one inner list for each row
                        stores_df_for_map['color'] = [[0, 0, 255]] * len(stores_df_for_map)
                    else:
                        # If DataFrame is empty or missing columns, create an empty one for concatenation
                        stores_df_for_map = pd.DataFrame(columns=['latitude', 'longitude', 'name', 'size', 'color'])


                    # Combine user's location and store locations for the map
                    # Filter out rows from stores_df_for_map that might have missing lat/lon
                    map_data_stores = stores_df_for_map.dropna(subset=['latitude', 'longitude'])
                    map_data = pd.concat([user_location_df, map_data_stores[['latitude', 'longitude', 'name', 'size', 'color']]])

                    if not map_data.empty:
                        st.map(map_data,
                            latitude='latitude',
                            longitude='longitude',
                            size='size',
                            color='color',
                            zoom=11) # Adjust zoom level as needed
                    else:
                        st.info("No locations to display on the map yet.")

        st.markdown("</div>", unsafe_allow_html=True) # Close input-section

elif page == "Add/Edit Store":
    with main_content_placeholder.container():
        st.markdown("---")
        # --- Mode Selector: Add vs. Edit ---
        mode = st.radio("Choose Mode", ["Add New Store", "Edit Existing Store"], key="add_edit_mode_selector")
        st.markdown("---")

        if mode == "Add New Store":
            st.markdown("<div class='input-section'>", unsafe_allow_html=True)
            st.markdown("<h3>Add New Store Location</h3>", unsafe_allow_html=True)

            # Using st.form with clear_on_submit=True for automatic clearing
            with st.form("add_store_form", clear_on_submit=True):
                new_store_name = st.text_input("Store Name", key="add_name_form") # Unique key for form input
                new_store_address = st.text_input("Store Address (e.g., 'Burj Khalifa, Dubai')", key="add_address_form")
                new_store_contact = st.text_input("Store Contact Number (optional)", key="add_contact_form")
                new_store_supervisor = st.text_input("Branch Supervisor Name (optional)", key="add_supervisor_form")

                store_status_options = ["", "Operational", "Temporarily Closed", "Permanently Closed"]
                new_store_status = st.selectbox("Store Status", options=store_status_options, key="add_status_form")
                new_store_hours = st.text_input("Store Hours (e.g., '9 AM - 5 PM Mon-Fri')", key="add_hours_form")

                add_button_submitted = st.form_submit_button("Add Store to Database")

                if add_button_submitted:
                    if not str(new_store_name).strip():
                        st.error("Please enter a name for the new store.")
                    elif not str(new_store_address).strip():
                        st.error("Please enter an address for the new store.")
                    else:
                        st.info(f"Geocoding new store address: '{new_store_address}'...")
                        store_lat, store_lon = get_coordinates_from_address(new_store_address, google_api_key)
                        if store_lat is not None and store_lon is not None:
                            if add_store_to_db(new_store_name.strip(), new_store_address.strip(), store_lat, store_lon, new_store_contact.strip(), new_store_supervisor.strip(), new_store_status, new_store_hours.strip()):
                                fetch_stores_from_db() # Refresh data after add
                                # The form's clear_on_submit=True handles clearing inputs
                        else:
                            st.error("Could not get coordinates for the new store. Please check the address and ensure your API key is correctly configured.")
                # No st.rerun() here explicitly, as form submission implicitly reruns the app.

            st.markdown("</div>", unsafe_allow_html=True)

        elif mode == "Edit Existing Store":
            st.markdown("<div class='input-section'>", unsafe_allow_html=True)
            st.markdown("<h3>Edit Existing Store Location</h3>", unsafe_allow_html=True)

            # --- Store Selection for Editing ---
            store_names = [""] + list(st.session_state.stores_df['name'].unique()) if not st.session_state.stores_df.empty else [""]
            selected_store_name_for_edit = st.selectbox(
                "Select Store to Edit",
                options=store_names,
                key="select_store_to_edit"
            )

            # Populate editing state if a store is selected
            if selected_store_name_for_edit and selected_store_name_for_edit != "":
                selected_store_row_series = st.session_state.stores_df[
                    st.session_state.stores_df['name'] == selected_store_name_for_edit
                ]
                if not selected_store_row_series.empty:
                    selected_store_row = selected_store_row_series.iloc[0]
                    st.session_state.editing_store_id = selected_store_row['id']
                    st.session_state.editing_store_details = selected_store_row.to_dict()
                    print(f"DEBUG: Selected store for edit (from DataFrame): ID={st.session_state.editing_store_id}, Details={st.session_state.editing_store_details}")
                else:
                    st.warning(f"Selected store '{selected_store_name_for_edit}' not found in current data. Please try again.")
                    st.session_state.editing_store_id = None
                    st.session_state.editing_store_details = {}
            else:
                # Clear editing state if no store is selected or placeholder is chosen
                st.session_state.editing_store_id = None
                st.session_state.editing_store_details = {}

            # --- Input Fields for Editing (pre-filled from session state) ---
            # Use a dummy value if no store is selected to avoid KeyError
            current_name = st.session_state.editing_store_details.get('name', '')
            current_address = st.session_state.editing_store_details.get('address', '')
            current_contact = st.session_state.editing_store_details.get('contact_number', '')
            current_supervisor = st.session_state.editing_store_details.get('branch_supervisor', '')
            current_status = st.session_state.editing_store_details.get('store_status', '')
            current_hours = st.session_state.editing_store_details.get('store_hours', '')

            edited_name = st.text_input("Store Name", value=current_name, key="edit_name")
            edited_address = st.text_input("Store Address", value=current_address, key="edit_address")
            edited_contact = st.text_input("Store Contact Number (optional)", value=current_contact, key="edit_contact")
            edited_supervisor = st.text_input("Branch Supervisor Name (optional)", value=current_supervisor, key="edit_supervisor")

            store_status_options_edit = ["", "Operational", "Temporarily Closed", "Permanently Closed"]
            # Find the correct index for the current status, default to 0 (empty) if not found
            current_status_index = store_status_options_edit.index(current_status) if current_status in store_status_options_edit else 0
            edited_status = st.selectbox("Store Status", options=store_status_options_edit, index=current_status_index, key="edit_status")
            edited_hours = st.text_input("Store Hours (e.g., '9 AM - 5 PM Mon-Fri')", value=current_hours, key="edit_hours")

            if st.button("Update Store Details", key="update_button"):
                if st.session_state.editing_store_id is None:
                    st.warning("Please select a store to edit first.")
                elif not str(edited_name).strip():
                    st.error("Store name cannot be empty.")
                elif not str(edited_address).strip():
                    st.error("Store address cannot be empty.")
                else:
                    # Initialize new_lat, new_lon with the currently selected store's numerical coordinates
                    new_lat = st.session_state.editing_store_details.get('latitude')
                    new_lon = st.session_state.editing_store_details.get('longitude')

                    # Check if address changed, then re-geocode
                    if edited_address.strip() != current_address.strip():
                        with st.spinner(f"Geocoding updated address: '{edited_address}'..."):
                            temp_lat, temp_lon = get_coordinates_from_address(edited_address, google_api_key)
                        if temp_lat is None or temp_lon is None:
                            st.error("Could not geocode the updated address. Please try again.")
                            st.stop()
                        else:
                            new_lat, new_lon = temp_lat, temp_lon
                    # Else (address did not change), new_lat and new_lon already hold the correct current numerical values from initialization

                    if new_lat is not None and new_lon is not None:
                        if update_store_in_db(
                            st.session_state.editing_store_id,
                            edited_name.strip(),
                            edited_address.strip(),
                            new_lat,
                            new_lon,
                            edited_contact.strip(),
                            edited_supervisor.strip(),
                            edited_status,
                            edited_hours.strip()
                        ):
                            # Clear editing state after successful update
                            st.session_state.editing_store_id = None
                            st.session_state.editing_store_details = {}
                            fetch_stores_from_db()
                            st.rerun()
                    else:
                        st.error("Invalid coordinates for update. Geocoding failed.")
            st.markdown("</div>", unsafe_allow_html=True) # Close input-section

        st.markdown("---")

        # --- Display All Saved Stores with Delete Buttons ---
        st.markdown("<h3>All Saved Stores</h3>", unsafe_allow_html=True)
        if not st.session_state.stores_df.empty:
            display_df = st.session_state.stores_df[['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours']].copy()

            # Adjust column widths for new column
            # (ID, Name, Address, Lat, Lon, Contact, Supervisor, Status, Hours, Delete)
            cols = st.columns([0.4, 1.2, 2.0, 0.9, 0.9, 1.2, 1.4, 1.1, 1.5, 0.7])
            with cols[0]:
                st.write("**ID**")
            with cols[1]:
                st.write("**Name**")
            with cols[2]:
                st.write("**Address**")
            with cols[3]:
                st.write("**Latitude**")
            with cols[4]:
                st.write("**Longitude**")
            with cols[5]:
                st.write("**Contact**")
            with cols[6]:
                st.write("**Supervisor**")
            with cols[7]:
                st.write("**Status**")
            with cols[8]:
                st.write("**Hours**") # Header for new column
            with cols[9]:
                st.write("**Delete**")

            # The loop for displaying data rows should be here:
            for index, row in display_df.iterrows():
                with cols[0]:
                    st.write(row['id'])
                with cols[1]:
                    st.write(row['name'])
                with cols[2]:
                    st.write(row['address'])
                with cols[3]:
                    st.write(f"{row['latitude']:.4f}")
                with cols[4]:
                    st.write(f"{row['longitude']:.4f}")
                with cols[5]:
                    contact_val = row['contact_number'] if pd.notnull(row['contact_number']) and str(row['contact_number']).strip() else "N/A"
                    st.write(contact_val)
                with cols[6]:
                    supervisor_val = row['branch_supervisor'] if pd.notnull(row['branch_supervisor']) and str(row['branch_supervisor']).strip() else "N/A"
                    st.write(supervisor_val)
                with cols[7]:
                    status_val = row['store_status'] if pd.notnull(row['store_status']) and str(row['store_status']).strip() else "N/A"
                    st.write(status_val)
                with cols[8]: # New column for hours
                    hours_val = row['store_hours'] if pd.notnull(row['store_hours']) and str(row['store_hours']).strip() else "N/A"
                    st.write(hours_val)
                with cols[9]:
                    if st.button("🗑️", key=f"delete_{row['id']}", help=f"Delete {row['name']}",
                                 use_container_width=True,
                                 ):
                        if delete_store_from_db(row['id']):
                            fetch_stores_from_db()
                            st.rerun()

        else:
            st.info("No stores currently in the database.")
