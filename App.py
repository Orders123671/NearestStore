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
                branch_supervisor TEXT,  -- New column for branch supervisor
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
def add_store_to_db(name, address, latitude, longitude, contact_number, branch_supervisor):
    """Adds a new store to SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO stores (name, address, latitude, longitude, contact_number, branch_supervisor) VALUES (?, ?, ?, ?, ?, ?)",
                           (name, address, latitude, longitude, contact_number, branch_supervisor))
            conn.commit()
        st.success(f"Store '{name}' added successfully!")
        return True
    except Exception as e:
        st.error(f"Error adding store to database: {e}")
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
    st.session_state.stores_df = pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'timestamp'])

def fetch_stores_from_db():
    """Fetches all stores from SQLite and updates st.session_state.stores_df."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, address, latitude, longitude, contact_number, branch_supervisor, timestamp FROM stores")
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
    .delete-button {
        background-color: #dc3545; /* Red */
        color: white;
        border-radius: 8px;
        padding: 5px 10px;
        font-size: 0.9em;
        border: none;
        cursor: pointer;
        transition: background-color 0.3s ease;
        box-shadow: 1px 1px 3px rgba(0,0,0,0.2);
    }
    .delete-button:hover {
        background-color: #c82333;
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

elif page == "Add New Store":
    with main_content_placeholder.container():
        st.markdown("---")
        # --- Add New Store Section ---
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Add New Store Location</h3>", unsafe_allow_html=True)

        new_store_name = st.text_input("Store Name")
        new_store_address = st.text_input("Store Address (e.g., '123 Main St, Anytown')", value="")
        new_store_contact = st.text_input("Store Contact Number (optional)", value="") # New input field
        new_store_supervisor = st.text_input("Branch Supervisor Name (optional)", value="") # New input field for supervisor

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
                    # Pass the new contact_number and branch_supervisor to the add function
                    if add_store_to_db(new_store_name, new_store_address, store_lat, store_lon, new_store_contact.strip(), new_store_supervisor.strip()):
                        # Refresh stores data after adding a new one
                        fetch_stores_from_db()
                        st.rerun() # Rerun to update the map and list immediately
                else:
                    st.error("Could not get coordinates for the new store. Please check the address and ensure your API key is correctly configured.")

        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---")

        # --- Display All Saved Stores with Delete Buttons ---
        st.markdown("<h3>All Saved Stores</h3>", unsafe_allow_html=True)
        if not st.session_state.stores_df.empty:
            # Create a copy to avoid SettingWithCopyWarning if we modify it
            display_df = st.session_state.stores_df[['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor']].copy()

            # Adjust column widths for new column
            cols = st.columns([0.5, 1.5, 2.5, 1, 1, 1.2, 1.5, 0.7]) # Adjusted widths: added one more slot
            with cols[0]:
                st.write("ID")
            with cols[1]:
                st.write("Name")
            with cols[2]:
                st.write("Address")
            with cols[3]:
                st.write("Latitude")
            with cols[4]:
                st.write("Longitude")
            with cols[5]:
                st.write("Contact")
            with cols[6]:
                st.write("Supervisor") # Header for new column
            with cols[7]:
                st.write("Delete") # Header for delete button column

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
                with cols[6]: # New column for supervisor
                    supervisor_val = row['branch_supervisor'] if pd.notnull(row['branch_supervisor']) and str(row['branch_supervisor']).strip() else "N/A"
                    st.write(supervisor_val)
                with cols[7]:
                    if st.button("🗑️", key=f"delete_{row['id']}", help=f"Delete {row['name']}",
                                 use_container_width=True,
                                 ):
                        if delete_store_from_db(row['id']):
                            fetch_stores_from_db() # Refresh data after deletion
                            st.rerun() # Rerun the app to update the display

        else:
            st.info("No stores currently in the database.")
