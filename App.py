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

# Initialize the database when the app starts. Moved this call to within specific page logic.
# init_db() # No longer called globally here

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
            # Convert name and address to lowercase for case-insensitive comparison
            name_lower = name.lower()
            address_lower = address.lower()

            # Check for existing store with same name and address (case-insensitive)
            cursor.execute("SELECT id FROM stores WHERE LOWER(name) = ? AND LOWER(address) = ?", (name_lower, address_lower))
            existing_store = cursor.fetchone()
            if existing_store:
                st.error(f"A store with the name '{name}' and address '{address}' already exists!")
                return False

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
                print(f"DEBUG: Store with ID {store_id_int} not found in database for update. This indicates a sync issue or DB file was reset.")
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
        return False

def delete_store_from_db(store_id):
    """Deletes a store from SQLite database by its ID."""
    print(f"DEBUG: Attempting to delete store with ID: {store_id}") # New debug print
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stores WHERE id = ?", (store_id,))
            rows_deleted = cursor.rowcount # Get count of deleted rows
            conn.commit()
        if rows_deleted > 0:
            st.success(f"Store with ID {store_id} deleted successfully!")
            print(f"DEBUG: Successfully deleted {rows_deleted} row(s) for ID: {store_id}") # New debug print
            return True
        else:
            st.warning(f"No store found with ID {store_id} to delete.") # New feedback
            print(f"DEBUG: No store found with ID {store_id} to delete.") # New debug print
            return False
    except Exception as e:
        st.error(f"Error deleting store from database: {e}")
        print(f"ERROR: Exception during delete_store_from_db for ID {store_id}: {e}") # New debug print
        return False

# Use Streamlit's session state to store stores_df for reactivity
if 'stores_df' not in st.session_state:
    st.session_state.stores_df = pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours', 'timestamp'])
if 'editing_store_id' not in st.session_state:
    st.session_state.editing_store_id = None # Store ID of the store currently being edited
if 'editing_store_details' not in st.session_state:
    st.session_state.editing_store_details = {} # Store details of the store currently being edited

# Initialize session state for delete confirmation "popup"
if 'delete_confirm_modal_active' not in st.session_state:
    st.session_state.delete_confirm_modal_active = False
if 'store_id_to_confirm_delete' not in st.session_state:
    st.session_state.store_id_to_confirm_delete = None
if 'store_name_to_confirm_delete' not in st.session_state:
    st.session_state.store_name_to_confirm_delete = None

# Initialize current_page in session state
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Find Nearest Store"

def fetch_stores_from_db_local():
    """Fetches all stores from SQLite and updates st.session_state.stores_df.
    This version is for local use within the app's pages."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, timestamp FROM stores")
            rows = cursor.fetchall()
            # Get column names from cursor description
            cols = [description[0] for description in cursor.description]
            st.session_state.stores_df = pd.DataFrame(rows, columns=cols)
            # No st.info here, as it's handled by the calling page now.
    except Exception as e:
        st.error(f"Error fetching stores from database: {e}")

# Call init_db once outside the main app flow to ensure DB is ready
init_db()


# --- Streamlit App Layout ---
st.set_page_config(layout="wide", page_title="Katrina Knowledge Base Tools", page_icon="📍")

st.markdown(
    """
    <style>
    /* Global reset for margin and padding to ensure elements start at the edge */
    html, body {
        margin: 0 !important;
        padding: 0 !important;
        box-sizing: border-box !important;
        height: 100% !important; /* Ensure html and body take full height */
        overflow: hidden; /* Prevent body scroll if sidebar is fixed */
    }

    /* Set the app view container to display as flex */
    [data-testid="stAppViewContainer"] {
        display: flex; /* Enable flexbox */
        flex-direction: row; /* Arrange children (main columns) in a row */
        padding: 0 !important;
        margin: 0 !important;
        font-family: 'Arial', sans-serif;
        background: linear-gradient(to right, #ffe6f2, #e0b0ff) !important; /* Pastel light pink to light purple gradient */
        color: #343a40;
        min-height: 100vh;
        width: 100%;
    }

    /* Remove Streamlit's default sidebar styling entirely */
    [data-testid="stSidebarV1"] {
        display: none !important;
        width: 0 !important;
        min-width: 0 !important;
        max-width: 0 !important;
        flex-basis: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
    }

    /* Main content area - now controlled by custom columns */
    .stApp .main {
        flex-grow: 1 !important; /* Allows it to take all available space */
        flex-shrink: 1 !important;
        width: 100% !important; /* No fixed width or margin-left from sidebar */
        padding: 1rem !important; /* Applied padding for content */
        overflow-y: auto; /* Allow main content to scroll */
    }

    /* Styles for the custom left navigation column */
    .left-nav-column {
        width: 250px; /* Fixed width for the navigation column */
        min-width: 250px;
        max-width: 250px;
        flex-shrink: 0; /* Prevent it from shrinking */
        background-color: #FFFFFF;
        box-shadow: 2px 0 5px rgba(0,0,0,0.1);
        padding: 20px;
        overflow-y: auto; /* Allows navigation to scroll if content is long */
    }

    /* Styles for the main content column (right side) */
    .main-content-column {
        flex-grow: 1; /* Takes remaining space */
        padding: 1rem;
        overflow-y: auto; /* Allows content to scroll */
    }

    /* General styling for Streamlit radio buttons for navigation */
    /* Removed background-color, border-radius, and box-shadow from the overall group */
    .stRadio div[role="radiogroup"] {
        background-color: transparent; /* Changed to transparent */
        border-radius: 0; /* Removed border radius */
        padding: 15px;
        box-shadow: none; /* Removed box shadow */
    }
    .stRadio div[role="radiogroup"] label {
        margin: 5px 0;
        display: flex; /* Ensure labels are flex containers for alignment */
        align-items: center;
        padding: 8px 12px; /* Adjust padding for better look */
        background-color: transparent; /* No specific background for individual labels */
        transition: background-color 0.2s ease;
        color: #343434 !important; /* Ensure individual option text color is readable */
        font-weight: normal; /* Default to normal weight */
    }
    .stRadio div[role="radiogroup"] label:hover {
        background-color: #dee2e6; /* Darker gray on hover for individual options */
    }
    .stRadio div[role="radiogroup"] label.st-selected { /* Streamlit adds st-selected to the selected label */
        font-weight: bold; /* Make selected item bold */
        background-color: #e0b0ff; /* Highlight selected item with light purple */
        border-radius: 8px;
    }

    /* Center text for info alerts */
    .stAlert.info p {
        text-align: center;
        width: 100%; /* Ensure it takes full width for centering */
    }


    /* Main Header Styling - Ensuring center alignment */
    .main-header {
        font-size: 2.8em;
        color: #28a745; /* Vibrant green */
        text-align: center !important; /* Explicitly centered and forced */
        margin-bottom: 25px;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.1);
        padding-top: 20px;
        width: 100%;
    }

    /* Subheader Styling - Ensuring center alignment */
    .subheader {
        font-size: 1.3em;
        color: #495057; /* Slightly darker gray for subheader */
        text-align: center !important; /* Explicitly centered and forced */
        margin-bottom: 40px;
        width: 100%;
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

    /* Streamlit Button Styling (applies to all buttons including link_button) */
    .stButton>button, .stDownloadButton>button, .stLinkButton>a {
        background-color: #007bff; /* Primary blue button */
        color: white;
        border-radius: 8px;
        padding: 8px 18px; /* Made smaller */
        font-size: 1.0em; /* Made smaller */
        border: none;
        cursor: pointer;
        transition: background-color 0.3s ease, transform 0.2s ease, box-shadow 0.3s ease;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2); /* Deeper shadow */
        font-weight: bold;
        text-decoration: none; /* Remove underline for link button */
        display: inline-flex; /* Ensure it behaves like a button */
        align-items: center; /* Center content vertically */
        justify-content: center; /* Center content horizontally */
    }
    .stButton>button:hover, .stDownloadButton>button:hover, .stLinkButton>a:hover {
        background-color: #0056b3; /* Darker blue on hover */
        transform: translateY(-2px); /* Slight lift effect */
        box-shadow: 0 6px 15px rgba(0,0,0,0.3);
    }

    /* Delete Button Specific Styling (for icon buttons in table) */
    .delete-icon-button {
        background-color: #dc3545; /* Red */
        color: white;
        border-radius: 6px;
        padding: 5px 8px; /* Smaller padding */
        font-size: 0.8em; /* Smaller font size for icon */
        border: none;
        cursor: pointer;
        transition: background-color 0.3s ease, transform 0.2s ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        display: inline-flex; /* Align icon and text */
        align-items: center;
        justify-content: center;
        line-height: 1; /* Adjust line height for better icon centering */
    }
    .delete-icon-button:hover {
        background-color: #c82333; /* Darker red on hover */
        transform: translateY(-1px);
    }


    /* Adjust Streamlit specific elements for proportional width */
    .stTextInput, .stSelectbox {
        width: 100%; /* Make them fill their container */
    }
    .stTextInput>div>div>input, .stSelectbox>div>div>select {
        border-radius: 8px;
        border: 1px solid #ced4da; /* Light gray border */
        padding: 10px;
        font-size: 1em;
        width: 100%; /* Ensure the input/select element itself fills the container */
        box-sizing: border-box; /* Include padding and border in the element's total width */
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

    /* Streamlit's "All Saved Stores" table headers (for st.dataframe, if used) */
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

    /* Footer Styling */
    .footer {
        position: fixed; /* Fixes the footer to the bottom of the viewport */
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: rgba(255, 255, 255, 0.8); /* Semi-transparent white background */
        color: #6c757d; /* Muted gray text */
        text-align: center;
        padding: 10px 0;
        font-size: 0.9em;
        box-shadow: 0 -2px 10px rgba(0,0,0,0.05); /* Soft shadow above the footer */
        z-index: 1000; /* Ensure footer stays on top */
    }

    /* --- Modal Specific CSS --- */
    /* Target the div that st.empty() creates. It's usually the last stVerticalBlock in the main app div */
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0, 0, 0, 0.6); /* Semi-transparent black overlay */
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 10000;
    }

    /* Target the st.container() div inside the st.empty() for the modal box */
    /* This is the direct child of the st.empty() div's content div */
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child > div:first-child {
        background-color: #f8d7da; /* Light red background for the box */
        border: 2px solid #dc3545; /* Red border */
        border-radius: 12px;
        padding: 30px;
        box-shadow: 0 5px 15px rgba(0,0,0,0.3);
        text-align: center;
        max-width: 500px;
        width: 90%;
        animation: fadeIn 0.3s ease-out;
    }

    /* Ensure h4 inside the modal box has the correct color */
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child > div:first-child h4 {
        color: #dc3545;
        margin-bottom: 20px;
        font-size: 1.5em;
    }

    /* Style for Streamlit buttons within the modal */
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child .stButton > button {
        padding: 10px 20px;
        font-size: 1em;
        border-radius: 8px;
        font-weight: bold;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        transition: all 0.2s ease-in-out;
    }

    /* Specific colors for confirm/cancel buttons using st.columns' structure within the modal */
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child [data-testid="stHorizontalBlock"] > div:first-child .stButton > button {
        background-color: #28a745; /* Green */
        color: white;
    }
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child [data-testid="stHorizontalBlock"] > div:first-child .stButton > button:hover {
        background-color: #218838;
        transform: translateY(-1px);
    }
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child [data-testid="stHorizontalBlock"] > div:last-child .stButton > button {
        background-color: #6c757d; /* Gray */
        color: white;
    }
    [data-testid="stAppViewContainer"] > section > div > div > div:last-child > div:first-child [data-testid="stHorizontalBlock"] > div:last-child .stButton > button:hover {
        background-color: #5a6268;
        transform: translateY(-1px);
    }

    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("<h1 class='main-header'>📍 Katrina Knowledge Base Tools</h1>", unsafe_allow_html=True)
st.markdown("<p class='subheader'>Your one stop shop Tools</p>", unsafe_allow_html=True)

# Retrieve API key from Streamlit secrets
try:
    google_api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
except KeyError:
    st.error("Missing Streamlit secret: 'GOOGLE_MAPS_API_KEY'. Please add it to your Streamlit secrets file.")
    google_api_key = "" # Set to empty to prevent errors if not found

# --- Main content placeholder and Modal placeholder ---
modal_placeholder = st.empty() # Still needed for the delete confirmation modal overlay

# --- Main layout using st.columns ---
col_nav, col_content = st.columns([1, 4]) # 1 part for navigation, 4 parts for content

with col_nav:
    st.markdown("<div class='left-nav-column'>", unsafe_allow_html=True)
    st.markdown("<h3>Navigation</h3>", unsafe_allow_html=True)
    
    page = st.radio(
        "", # Empty label for the radio group, as we have an H3
        ["Find Nearest Store", "Add/Edit Store", "Delivery Fee"],
        key="main_navigation_radio",
        index=["Find Nearest Store", "Add/Edit Store", "Delivery Fee"].index(st.session_state.current_page),
        help="Select a tool from the options below."
    )
    # Update session state based on radio selection
    if page != st.session_state.current_page:
        st.session_state.current_page = page
        st.rerun() # Rerun to update content column immediately

    st.markdown("</div>", unsafe_allow_html=True)

with col_content:
    st.markdown("<div class='main-content-column'>", unsafe_allow_html=True)

    if st.session_state.current_page == "Find Nearest Store":
        fetch_stores_from_db_local() # Fetch stores for this page
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
                    st.info("No stores loaded from the database. Please add some stores using the 'Add/Edit Store' page.")

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

    elif st.session_state.current_page == "Add/Edit Store":
        fetch_stores_from_db_local() # Fetch stores for this page
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
                                fetch_stores_from_db_local() # Refresh data after add
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
                    # print(f"DEBUG: Selected Store ID: {st.session_state.editing_store_id}") # Debug print
                    # print(f"DEBUG: Editing Details: {st.session_state.editing_store_details}") # Debug print
                else:
                    st.warning(f"Selected store '{selected_store_name_for_edit}' not found in current data. Please try again.")
                    st.session_state.editing_store_id = None
                    st.session_state.editing_store_details = {}
            else:
                # Clear editing state if no store is selected or placeholder is chosen
                st.session_state.editing_store_id = None
                st.session_state.editing_store_details = {}

            # --- Conditional display of edit fields ---
            if st.session_state.editing_store_id:
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
                current_status_index = store_status_options_edit.index(current_status) if current_status in store_status_options_edit else 0
                edited_status = st.selectbox("Store Status", options=store_status_options_edit, index=current_status_index, key="edit_status")
                edited_hours = st.text_input("Store Hours (e.g., '9 AM - 5 PM Mon-Fri')", value=current_hours, key="edit_hours")

                # --- Update Button ---
                if st.button("Update Store Details", key="update_button", use_container_width=True): # use_container_width is valid for buttons
                    if st.session_state.editing_store_id is None:
                        st.warning("Please select a store to edit first.") # This case should ideally not happen now
                    elif not str(edited_name).strip():
                        st.error("Store name cannot be empty.")
                    elif not str(edited_address).strip():
                        st.error("Store address cannot be empty.")
                    else:
                        new_lat = st.session_state.editing_store_details.get('latitude')
                        new_lon = st.session_state.editing_store_details.get('longitude')

                        if edited_address.strip() != current_address.strip():
                            with st.spinner(f"Geocoding updated address: '{edited_address}'..."):
                                temp_lat, temp_lon = get_coordinates_from_address(edited_address, google_api_key)
                            if temp_lat is None or temp_lon is None:
                                st.error("Could not geocode the updated address. Please try again.")
                                st.stop()
                            else:
                                new_lat, new_lon = temp_lat, temp_lon

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
                                st.session_state.editing_store_id = None
                                st.session_state.editing_store_details = {}
                                fetch_stores_from_db_local()
                                st.rerun()
                        else:
                            st.error("Invalid coordinates for update. Geocoding failed.")
            else:
                # This message will appear when "Edit Existing Store" is selected but no specific store is chosen.
                st.info("Please select a store from the dropdown above to edit its details.")


            st.markdown("</div>", unsafe_allow_html=True) # Close input-section

        st.markdown("---")

        # --- Display All Saved Stores (Simulated Table) ---
        if mode == "Edit Existing Store":
            st.markdown("<h3>All Saved Stores</h3>", unsafe_allow_html=True)
            if not st.session_state.stores_df.empty:
                # Define column ratios for the simulated table (ID, Name, Address, Contact, Supervisor, Status, Hours, Actions)
                # Adjust ratios as needed for your data lengths
                cols_config = st.columns([0.5, 2, 3, 1.5, 1.5, 1.2, 2, 0.8])

                # Header Row
                with cols_config[0]: st.write("**ID**")
                with cols_config[1]: st.write("**Name**")
                with cols_config[2]: st.write("**Address**")
                with cols_config[3]: st.write("**Contact**")
                with cols_config[4]: st.write("**Supervisor**")
                with cols_config[5]: st.write("**Status**")
                with cols_config[6]: st.write("**Hours**")
                with cols_config[7]: st.write("**Actions**") # Header for delete button

                st.markdown("---") # Separator after header

                for index, store in st.session_state.stores_df.iterrows():
                    row_cols = st.columns([0.5, 2, 3, 1.5, 1.5, 1.2, 2, 0.8])
                    with row_cols[0]: st.write(str(store['id']))
                    with row_cols[1]: st.write(store['name'])
                    with row_cols[2]: st.write(store['address'])
                    with row_cols[3]: st.write(str(store.get('contact_number', 'N/A')))
                    with row_cols[4]: st.write(str(store.get('branch_supervisor', 'N/A')))
                    with row_cols[5]: st.write(str(store.get('store_status', 'N/A')))
                    with row_cols[6]: st.write(str(store.get('store_hours', 'N/A')))
                    with row_cols[7]:
                        # Use a unique key for each button and the custom class
                        # Note: The `type="secondary"` on the button ensures it uses the secondary button styling from Streamlit,
                        # which is then overridden by the custom CSS for `.delete-icon-button`.
                        # I've modified the key and styling to align with the column layout.
                        if st.button("🗑️", key=f"delete_row_{store['id']}", help=f"Delete {store['name']}", type="secondary"
                        ):
                            st.session_state.delete_confirm_modal_active = True
                            st.session_state.store_id_to_confirm_delete = store['id']
                            st.session_state.store_name_to_confirm_delete = store['name']
                            st.rerun() # Trigger rerun to show the modal

                    st.markdown("---") # Separator between rows
            else:
                # This info message appears if there are no stores in the database at all.
                st.info("No stores currently in the database. Add some using 'Add New Store' tab!")

    elif st.session_state.current_page == "Delivery Fee":
        st.markdown("---")
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Delivery Fee Information</h3>", unsafe_allow_html=True)
        st.write("Click the button below to visit our delivery fee information page.")

        # You can replace this URL with the actual website you want to link to.
        delivery_fee_url = "https://www.example.com/delivery-fees"
        st.link_button("Go to Delivery Fee Page", delivery_fee_url)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True) # Close main-content-column div

# --- Footer Section ---
st.markdown("<div class='footer'>", unsafe_allow_html=True)
st.markdown("Copyright 2025", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# Conditional "Popup" for Delete Confirmation
if st.session_state.delete_confirm_modal_active:
    with modal_placeholder.container(): # Use the placeholder to render the modal
        # This container will be the modal overlay and content box
        with st.container():
            st.markdown(f"<h4>Are you sure you want to delete '{st.session_state.store_name_to_confirm_delete}'?</h4>", unsafe_allow_html=True)
            st.markdown("<p>This action cannot be undone.</p>", unsafe_allow_html=True)

            col_confirm, col_cancel = st.columns([1, 1])
            with col_confirm:
                if st.button("Confirm Delete", key="confirm_delete_final_btn", use_container_width=True, help="Permanently delete this store"):
                    if st.session_state.store_id_to_confirm_delete:
                        print(f"DEBUG: Confirming and attempting to delete store ID: {st.session_state.store_id_to_confirm_delete}")
                        if delete_store_from_db(st.session_state.store_id_to_confirm_delete):
                            st.session_state.delete_confirm_modal_active = False
                            st.session_state.store_id_to_confirm_delete = None
                            st.session_state.store_name_to_confirm_delete = None
                            st.session_state.editing_store_id = None
                            st.session_state.editing_store_details = {}
                            fetch_stores_from_db_local()
                            st.rerun()
            with col_cancel:
                if st.button("Cancel", key="cancel_delete_final_btn", use_container_width=True, help="Cancel deletion and return"):
                    st.session_state.delete_confirm_modal_active = False
                    st.session_state.store_id_to_confirm_delete = None
                    st.session_state.store_name_to_confirm_delete = None
                    st.rerun()
