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
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
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
def add_store_to_db(name, address, latitude, longitude):
    """Adds a new store to SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO stores (name, address, latitude, longitude) VALUES (?, ?, ?, ?)",
                           (name, address, latitude, longitude))
            conn.commit()
        st.success(f"Store '{name}' added successfully!")
        return True
    except Exception as e:
        st.error(f"Error adding store to database: {e}")
        return False

# Use Streamlit's session state to store stores_df for reactivity
if 'stores_df' not in st.session_state:
    st.session_state.stores_df = pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'timestamp'])

def fetch_stores_from_db():
    """Fetches all stores from SQLite and updates st.session_state.stores_df."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, address, latitude, longitude, timestamp FROM stores")
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
st.set_page_config(layout="wide", page_title="Nearest Store Finder", page_icon="📍")

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.5em;
        color: #4CAF50; /* Green */
        text-align: center;
        margin-bottom: 20px;
    }
    .subheader {
        font-size: 1.2em;
        color: #333;
        text-align: center;
        margin-bottom: 30px;
    }
    .input-section {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 30px;
    }
    .result-card {
        background-color: #e6ffe6; /* Light green */
        border-left: 5px solid #4CAF50;
        padding: 20px;
        border-radius: 10px;
        margin-top: 20px;
    }
    .store-name {
        font-size: 1.5em;
        font-weight: bold;
        color: #2e7d32; /* Darker green */
    }
    .distance-text {
        font-size: 1.1em;
        color: #555;
    }
    .stButton>button {
        background-color: #4CAF50;
        color: white;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 1.1em;
        border: none;
        cursor: pointer;
        transition: background-color 0.3s ease;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.2);
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("<h1 class='main-header'>📍 Nearest Store Finder</h1>", unsafe_allow_html=True)
st.markdown("<p class='subheader'>Find the closest store or add new store locations.</p>", unsafe_allow_html=True)

# --- Navigation ---
page = st.sidebar.radio("Navigation", ["Find Nearest Store", "Add New Store"])
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
        user_address_input = st.text_input("Enter your Address (e.g., 'Burj Khalifa, Dubai')", value="")

        if st.button("Find Nearest Store"):
            user_lat, user_lon = None, None
            if str(user_address_input).strip():
                st.info(f"Geocoding address: '{user_address_input}'...")
                # Pass API key loaded from secrets
                user_lat, user_lon = get_coordinates_from_address(user_address_input, google_api_key)
                if user_lat is None or user_lon is None:
                    st.error("Could not get coordinates from the provided address. Please try another address or check your API key.")
            else:
                st.error("Please provide an address to find the nearest store.")

            if user_lat is not None and user_lon is not None:
                st.subheader("Searching for the nearest store...")

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
                        st.markdown("</div>", unsafe_allow_html=True)
                    else:
                        st.warning("No stores found in the database to compare with. Please add some stores first.")
                else:
                    st.warning("No stores loaded from the database. Please add some stores using the 'Add New Store' page.")

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
                        # This is the key fix: assign a list of lists, one inner list for each row
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

elif page == "Add New Store":
    with main_content_placeholder.container():
        st.markdown("---")
        # --- Add New Store Section ---
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Add New Store Location</h3>", unsafe_allow_html=True)

        new_store_name = st.text_input("Store Name")
        new_store_address = st.text_input("Store Address (e.g., '123 Main St, Anytown')", value="")

        if st.button("Add Store to Database"):
            if not str(new_store_name).strip():
                st.error("Please enter a name for the new store.")
            elif not str(new_store_address).strip():
                st.error("Please enter an address for the new store.")
            else:
                st.info(f"Geocoding new store address: '{new_store_address}'...")
                # Pass API key loaded from secrets
                store_lat, store_lon = get_coordinates_from_address(new_store_address, google_api_key)
                if store_lat is not None and store_lon is not None:
                    if add_store_to_db(new_store_name, new_store_address, store_lat, store_lon):
                        # Refresh stores data after adding a new one
                        fetch_stores_from_db()
                        st.rerun() # Rerun to update the map and list immediately
                else:
                    st.error("Could not get coordinates for the new store. Please check the address and ensure your API key is correctly configured.")

        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---")

        # --- Display All Saved Stores (always visible on Add New Store page) ---
        st.markdown("<h3>All Saved Stores</h3>", unsafe_allow_html=True)
        if not st.session_state.stores_df.empty:
            st.dataframe(st.session_state.stores_df[['name', 'address', 'latitude', 'longitude']])
        else:
            st.info("No stores currently in the database.")
