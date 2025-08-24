import streamlit as st
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
import requests
import sqlite3
import os
import re # Import regex for normalization
import pydeck as pdk # Import pydeck for advanced mapping

# --- Regular Expressions for Validation ---
# Basic international phone number format (allows +, digits, spaces, hyphens, parentheses, 7-20 chars)
CONTACT_NUMBER_PATTERN = r'^\+?[0-9\s\-\(\)]{7,20}$'
# Flexible time format (e.g., "9 AM", "9:00 AM", "9 AM - 5 PM", "9-5 Mon-Fri")
STORE_HOURS_PATTERN = r'^\d{1,2}(:\d{2})?\s*(AM|PM)?\s*(-\s*\d{1,2}(:\d{2})?\s*(AM|PM)?)?\s*([a-zA-Z,&\s-]+)?$'


# --- Normalization Helper Function ---
def normalize_string(text):
    """
    Normalizes a string by converting to lowercase, replacing number words with digits,
    removing non-alphanumeric characters (except spaces), and standardizing spaces.
    """
    if not isinstance(text, str):
        return text # Return as-is if not a string (e.g., None, int)
    text = text.lower()
    
    # Replace common number words with digits
    number_word_map = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "zero": "0"
    }
    for word, digit in number_word_map.items():
        # Use regex with word boundaries to avoid replacing parts of other words (e.g., "lone" -> "l1")
        text = re.sub(r'\b' + word + r'\b', digit, text)
        
    # Remove all non-alphanumeric characters except spaces
    text = re.sub(r'[^a-z0-9\s]', '', text)
    
    # Replace multiple spaces with a single space and strip leading/trailing spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- SQLite Database Setup ---
DB_FILE = "stores.db"

def init_db():
    """Initializes the SQLite database and creates the stores and delivery_fees tables if they don't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Create stores table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                contact_number TEXT,
                branch_supervisor TEXT,
                store_status TEXT DEFAULT 'Operational',
                store_hours TEXT,
                normalized_name TEXT,     -- Added normalized_name
                normalized_address TEXT,  -- Added normalized_address
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add columns to stores table if they don't exist
        columns_to_add_stores = {
            "contact_number": "TEXT",
            "branch_supervisor": "TEXT",
            "store_status": "TEXT DEFAULT 'Operational'",
            "store_hours": "TEXT",
            "normalized_name": "TEXT",
            "normalized_address": "TEXT"
        }
        for col, col_type in columns_to_add_stores.items():
            try:
                cursor.execute(f"ALTER TABLE stores ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    # For existing columns, this warning is okay.
                    pass
        conn.commit()
        
        # --- Migration Step: Populate normalized columns for existing data ---
        # Fetch rows where normalized_name or normalized_address are NULL (newly added columns)
        cursor.execute("SELECT id, name, address, normalized_name, normalized_address FROM stores WHERE normalized_name IS NULL OR normalized_address IS NULL")
        rows_to_update = cursor.fetchall()
        
        for row_id, name, address, current_normalized_name, current_normalized_address in rows_to_update:
            updates = []
            params = []
            
            if current_normalized_name is None:
                updated_normalized_name = normalize_string(name)
                updates.append("normalized_name = ?")
                params.append(updated_normalized_name)
                
            if current_normalized_address is None:
                updated_normalized_address = normalize_string(address)
                updates.append("normalized_address = ?")
                params.append(updated_normalized_address)
                
            if updates: # If there are updates to apply
                update_query = f"UPDATE stores SET {', '.join(updates)} WHERE id = ?"
                params.append(row_id)
                cursor.execute(update_query, tuple(params))
        conn.commit()

# Ensure delivery_fees table is also initialized (as per previous versions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS delivery_fees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                min_order_amount REAL NOT NULL,
                delivery_charge REAL NOT NULL,
                amount_for_free_delivery REAL,
                zone TEXT,
                normalized_location TEXT, -- Added normalized_location
                normalized_zone TEXT,     -- Added normalized_zone
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        columns_to_add_delivery_fees = {
            "amount_for_free_delivery": "REAL",
            "zone": "TEXT",
            "normalized_location": "TEXT", # Add normalized_location column
            "normalized_zone": "TEXT"      # Add normalized_zone column
        }
        for col, col_type in columns_to_add_delivery_fees.items():
            try:
                cursor.execute(f"ALTER TABLE delivery_fees ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    st.warning(f"Could not add column '{col}' to 'delivery_fees' table (may already exist or another issue): {e}")
        conn.commit()

        # --- Migration Step: Populate normalized columns for existing delivery_fees data ---
        cursor.execute("SELECT id, location, zone, normalized_location, normalized_zone FROM delivery_fees WHERE normalized_location IS NULL OR normalized_zone IS NULL")
        rows_to_update_fees = cursor.fetchall()
        
        for row_id, location, zone, current_normalized_location, current_normalized_zone in rows_to_update_fees:
            updates = []
            params = []
            
            if current_normalized_location is None:
                updated_normalized_location = normalize_string(location)
                updates.append("normalized_location = ?")
                params.append(updated_normalized_location)
                
            if current_normalized_zone is None:
                updated_normalized_zone = normalize_string(zone) if zone else ''
                updates.append("normalized_zone = ?")
                params.append(updated_normalized_zone)
                
            if updates:
                update_query = f"UPDATE delivery_fees SET {', '.join(updates)} WHERE id = ?"
                params.append(row_id)
                cursor.execute(update_query, tuple(params))
        conn.commit()


init_db()

# --- Haversine Distance Calculation ---
def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two points on Earth using the Haversine formula.
    Returns distance in kilometers.
    """
    R = 6371

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
        response.raise_for_status()
        data = response.json()

        if data["status"] == "OK":
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
        else:
            st.error(f"Error geocoding address: {data['status']}. Please ensure the address is valid and your API key is correct.")
            return None, None
    except requests.exceptions.RequestException as e:
        st.error(f"Network error or invalid API key: {e}. Please check your internet connection and API key configuration.")
        return None, None
    except Exception as e:
        st.error(f"An unexpected error occurred during geocoding: {e}")
        return None, None

# --- Function to get route polyline from Google Directions API ---
def get_route_polyline(origin_lat, origin_lon, dest_lat, dest_lon, api_key_to_use):
    """
    Gets a route polyline between two points using Google Directions API.
    Returns a list of [longitude, latitude] pairs, or None if no route found.
    """
    if not str(api_key_to_use).strip():
        st.error("Google Maps API Key is not configured. Please set it in your Streamlit secrets as 'GOOGLE_MAPS_API_KEY'.")
        return None

    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{origin_lat},{origin_lon}",
        "destination": f"{dest_lat},{dest_lon}",
        "key": api_key_to_use
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()

        if data["status"] == "OK" and data["routes"]:
            # Decode the polyline from the first route
            polyline_str = data["routes"][0]["overview_polyline"]["points"]
            
            # Google's polyline encoding algorithm
            # (Adapted from various sources, common for Google Maps API)
            def decode_polyline(polyline_str):
                index, lat, lng = 0, 0, 0
                coordinates = []
                while index < len(polyline_str):
                    b = 0
                    shift = 0
                    result = 0
                    while True:
                        b = ord(polyline_str[index]) - 63
                        index += 1
                        result |= (b & 0x1f) << shift
                        shift += 5
                        if not b >= 0x20:
                            break
                    dlat = ~(result >> 1) if result & 1 else (result >> 1)
                    lat += dlat

                    b = 0
                    shift = 0
                    result = 0
                    while True:
                        b = ord(polyline_str[index]) - 63
                        index += 1
                        result |= (b & 0x1f) << shift
                        shift += 5
                        if not b >= 0x20:
                            break
                    dlng = ~(result >> 1) if result & 1 else (result >> 1)
                    lng += dlng

                    coordinates.append([lng / 100000.0, lat / 100000.0]) # [longitude, latitude]
                return coordinates
            
            return decode_polyline(polyline_str)

        elif data["status"] == "ZERO_RESULTS":
            st.warning("No route found between the specified locations. This might mean they are unreachable by road or too close.")
            return None
        else:
            st.error(f"Error getting route: {data['status']}. {data.get('error_message', '')}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Network error or invalid API key for Directions API: {e}. Please check your internet connection and API key configuration.")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred during route calculation: {e}")
        return None


# --- SQLite Operations for Stores ---
def add_store_to_db(name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours):
    """Adds a new store to SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            normalized_name = normalize_string(name)
            normalized_address = normalize_string(address)

            # Check for existing store using normalized name and address
            cursor.execute("SELECT id FROM stores WHERE normalized_name = ? AND normalized_address = ?", (normalized_name, normalized_address))
            existing_store = cursor.fetchone()
            if existing_store:
                st.error(f"A store with the name '{name}' and address '{address}' (or a similar normalized form) already exists!")
                return False

            cursor.execute("INSERT INTO stores (name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, normalized_name, normalized_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, normalized_name, normalized_address))
            conn.commit()
        st.success(f"Store '{name}' added successfully!")
        return True
    except Exception as e:
        st.error(f"Error adding store to database: {e}")
        return False

def update_store_in_db(store_id, name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours):
    """Updates an existing store in SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            store_id_int = int(store_id)

            normalized_name = normalize_string(name)
            normalized_address = normalize_string(address)

            # Check for duplicates, excluding the current store being updated
            cursor.execute("SELECT id FROM stores WHERE normalized_name = ? AND normalized_address = ? AND id != ?",
                           (normalized_name, normalized_address, store_id_int))
            existing_store = cursor.fetchone()
            if existing_store:
                st.error(f"An updated store with the name '{name}' and address '{address}' (or a similar normalized form) already exists for another entry!")
                return False

            cursor.execute("""
                UPDATE stores SET
                    name = ?,
                    address = ?,
                    latitude = ?,
                    longitude = ?,
                    contact_number = ?,
                    branch_supervisor = ?,
                    store_status = ?,
                    store_hours = ?,
                    normalized_name = ?,
                    normalized_address = ?
                WHERE id = ?
            """, (name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, normalized_name, normalized_address, store_id_int))

            rows_affected = cursor.rowcount
            if rows_affected == 0:
                st.warning(f"No store found with ID {store_id_int} to update, or data was identical.")
                return False
            conn.commit()
        st.success(f"Store '{name}' (ID: {store_id_int}) updated successfully!")
        return True
    except Exception as e:
        st.error(f"Error updating store in database: {e}")
        return False

def delete_store_from_db(store_id):
    """D
eletes a store from SQLite database by its ID."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stores WHERE id = ?", (store_id,))
            rows_deleted = cursor.rowcount
            conn.commit()
        if rows_deleted > 0:
            st.success(f"Store with ID {store_id} deleted successfully!")
            return True
        else:
            st.warning(f"No store found with ID {store_id} to delete.")
            return False
    except Exception as e:
        st.error(f"Error deleting store from database: {e}")
        return False

# --- SQLite Operations for Delivery Fees ---
def add_delivery_fee_to_db(location, min_order_amount, delivery_charge, amount_for_free_delivery, zone):
    """Adds a new delivery fee entry to SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            normalized_location = normalize_string(location)
            normalized_zone = normalize_string(zone) if zone else '' # Handle optional zone, normalize even if empty

            # Check for existing entry using normalized location and zone
            cursor.execute("SELECT id FROM delivery_fees WHERE normalized_location = ? AND normalized_zone = ?",
                           (normalized_location, normalized_zone))
            existing_fee = cursor.fetchone()
            if existing_fee:
                st.error(f"Duplicate record: A delivery fee entry for '{location}' in zone '{zone}' (or a similar normalized form) already exists!")
                return False

            cursor.execute("INSERT INTO delivery_fees (location, min_order_amount, delivery_charge, amount_for_free_delivery, zone, normalized_location, normalized_zone) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (location, min_order_amount, delivery_charge, amount_for_free_delivery, zone, normalized_location, normalized_zone))
            conn.commit()
        st.success(f"Delivery fee for '{location}' added successfully!")
        return True
    except Exception as e:
        st.error(f"Error adding delivery fee to database: {e}")
        return False

def update_delivery_fee_in_db(fee_id, location, min_order_amount, delivery_charge, amount_for_free_delivery, zone):
    """Updates an existing delivery fee entry in SQLite database."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            fee_id_int = int(fee_id)
            
            normalized_location = normalize_string(location)
            normalized_zone = normalize_string(zone) if zone else '' # Handle optional zone, normalize even if empty

            # Check for duplicates, excluding the current fee being updated
            cursor.execute("SELECT id FROM delivery_fees WHERE normalized_location = ? AND normalized_zone = ? AND id != ?",
                           (normalized_location, normalized_zone, fee_id_int))
            existing_fee = cursor.fetchone()
            if existing_fee:
                st.error(f"Duplicate record: An updated delivery fee entry for '{location}' in zone '{zone}' (or a similar normalized form) already exists for another entry!")
                return False

            cursor.execute("""
                UPDATE delivery_fees SET
                    location = ?,
                    min_order_amount = ?,
                    delivery_charge = ?,
                    amount_for_free_delivery = ?,
                    zone = ?,
                    normalized_location = ?,
                    normalized_zone = ?
                WHERE id = ?
            """, (location, min_order_amount, delivery_charge, amount_for_free_delivery, zone, normalized_location, normalized_zone, fee_id_int))

            rows_affected = cursor.rowcount
            if rows_affected == 0:
                st.warning(f"No delivery fee entry found with ID {fee_id_int} to update, or data was identical.")
                return False
            conn.commit()
        st.success(f"Delivery fee for '{location}' (ID: {fee_id_int}) updated successfully!")
        return True
    except Exception as e:
        st.error(f"Error updating delivery fee in database: {e}")
        return False


def delete_delivery_fee_from_db(fee_id):
    """Deletes a delivery fee entry from SQLite database by its ID."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM delivery_fees WHERE id = ?", (fee_id,))
            rows_deleted = cursor.rowcount
            conn.commit()
        if rows_deleted > 0:
            st.success(f"Delivery fee entry with ID {fee_id} deleted successfully!")
            return True
        else:
            st.warning(f"No delivery fee entry found with ID {fee_id} to delete.")
            return False
    except Exception as e:
        st.error(f"Error deleting delivery fee from database: {e}")
        return False

# Initialize Streamlit session state variables
if 'stores_df' not in st.session_state:
    st.session_state.stores_df = pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours', 'timestamp', 'normalized_name', 'normalized_address']) # Added new columns
if 'editing_store_id' not in st.session_state:
    st.session_state.editing_store_id = None
if 'editing_store_details' not in st.session_state:
    st.session_state.editing_store_details = {}
# Initialize delete confirmation state variables
if 'delete_confirm_modal_active' not in st.session_state:
    st.session_state.delete_confirm_modal_active = False
if 'store_id_to_confirm_delete' not in st.session_state:
    st.session_state.store_id_to_confirm_delete = None
if 'store_name_to_confirm_delete' not in st.session_state:
    st.session_state.store_name_to_confirm_delete = None

if 'delivery_fees_df' not in st.session_state:
    st.session_state.delivery_fees_df = pd.DataFrame(columns=['id', 'location', 'min_order_amount', 'delivery_charge', 'amount_for_free_delivery', 'zone', 'timestamp', 'normalized_location', 'normalized_zone'])
if 'editing_delivery_fee_id' not in st.session_state:
    st.session_state.editing_delivery_fee_id = None
if 'editing_delivery_fee_details' not in st.session_state:
    st.session_state.editing_delivery_fee_details = {}

# Session state for store search input
if 'store_search_input' not in st.session_state:
    st.session_state.store_search_input = ""
if 'store_search_query' not in st.session_state:
    st.session_state.store_search_query = "" # To hold the query when search is triggered

if 'user_lat' not in st.session_state:
    st.session_state.user_lat = None
if 'user_lon' not in st.session_state:
    st.session_state.user_lon = None

def fetch_stores_from_db_local():
    """Fetches all stores from SQLite and updates st.session_state.stores_df."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Fetch the new normalized columns as well
            cursor.execute("SELECT id, name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, normalized_name, normalized_address, timestamp FROM stores")
            rows = cursor.fetchall()
            cols = [description[0] for description in cursor.description]
            st.session_state.stores_df = pd.DataFrame(rows, columns=cols)
    except Exception as e:
        st.error(f"Error fetching stores from database: {e}")

def fetch_delivery_fees_from_db_local():
    """Fetches all delivery fee entries from SQLite and updates st.session_state.delivery_fees_df."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, location, min_order_amount, delivery_charge, amount_for_free_delivery, zone, normalized_location, normalized_zone, timestamp FROM delivery_fees")
            rows = cursor.fetchall()
            cols = [description[0] for description in cursor.description]
            st.session_state.delivery_fees_df = pd.DataFrame(rows, columns=cols)
    except Exception as e:
        st.error(f"Error fetching delivery fees from database: {e}")

def clear_delivery_fee_edit_state():
    """Clears the session state for editing a delivery fee.
       This will also effectively clear the form inputs when rerunning."""
    st.session_state.editing_delivery_fee_id = None
    st.session_state.editing_delivery_fee_details = {}
    st.rerun()

def clear_store_edit_state():
    """Clears the session state for editing a store."""
    st.session_state.editing_store_id = None
    st.session_state.editing_store_details = {}
    st.rerun()

# --- Streamlit App Layout ---
st.set_page_config(
    layout="wide",
    page_title="Katrina Knowledge Base Tools",
    page_icon="📍",
    initial_sidebar_state="expanded" # Changed to expanded for better navigation visibility
)

# Load CSS from external file
def load_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.error(f"Error: CSS file '{file_name}' not found. Please ensure style.css is in the same directory as app.py.")

# Apply general styling from style.css
load_css("style.css")

# Add Google Fonts link for 'Inter'
st.markdown('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">', unsafe_allow_html=True)

st.markdown("<h1 class='main-header'>📍 Katrina Knowledge Base Tools</h1>", unsafe_allow_html=True)
st.markdown("<p class='subheader'>Your one stop shop Tools</p>", unsafe_allow_html=True)

# Retrieve API key from Streamlit secrets
try:
    google_api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
except KeyError:
    st.error("Missing Streamlit secret: 'GOOGLE_MAPS_API_KEY'. Please add it to your Streamlit secrets file.")
    google_api_key = ""

# --- Sidebar Navigation ---
st.sidebar.markdown("## Navigation")
selected_page = st.sidebar.radio(
    "Go to",
    ["Find Store/Add/Edit", "Delivery Fee", "Price Calculator"]
)

if selected_page == "Find Store/Add/Edit":
    fetch_stores_from_db_local()
    st.markdown("---")
    
    # Tabs for Find Store and Add/Edit
    tab_search_stores, tab_add_edit_stores = st.tabs(["Search Stores", "Add/Edit Stores"])

    with tab_search_stores:
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Search Nearest Store</h3>", unsafe_allow_html=True)
        st.write("Enter your location to find the nearest store.")

        # Wrap the input and button in a form so Enter key triggers submission
        with st.form("find_nearest_store_form_tab"):
            # Use session state for input value
            user_address_input = st.text_input(
                "Enter your Address (e.g., 'Burj Khalifa, Dubai')",
                value=st.session_state.store_search_input,
                key="search_address_input_tab"
            )
            find_nearest_button_submitted = st.form_submit_button("Find Nearest Store")

        # Handle search logic when form is submitted
        if find_nearest_button_submitted:
            st.session_state.store_search_query = user_address_input # Store current input for processing
            
            if st.session_state.store_search_query.strip():
                with st.spinner("Geocoding address and searching for the nearest store..."):
                    user_lat, user_lon = get_coordinates_from_address(st.session_state.store_search_query, google_api_key)
            else:
                st.error("Please provide an address to find the nearest store.")
                user_lat, user_lon = None, None # Reset coordinates if input is empty

            # Store the coordinates in session state for map and results if found
            st.session_state.user_lat = user_lat
            st.session_state.user_lon = user_lon
        
        # Display results and map if coordinates are available in session state
        if 'user_lat' in st.session_state and st.session_state.user_lat is not None and st.session_state.user_lon is not None:
            user_lat = st.session_state.user_lat
            user_lon = st.session_state.user_lon

            nearest_store = None
            min_distance = float('inf')

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
                st.markdown(f"<p class='distance-text'>Address: {nearest_store['address']}</p>", unsafe_allow_html=True)

                contact_to_display = nearest_store.get('contact_number')
                if pd.notnull(contact_to_display) and str(contact_to_display).strip():
                    st.markdown(f"<p class='distance-text'>Contact: {str(contact_to_display).strip()}</p>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<p class='distance-text'>Contact: Not Available</p>", unsafe_allow_html=True)

                supervisor_to_display = nearest_store.get('branch_supervisor')
                if pd.notnull(supervisor_to_display) and str(supervisor_to_display).strip():
                    st.markdown(f"<p class='distance-text'>Supervisor: {str(supervisor_to_display).strip()}</p>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<p class='distance-text'>Supervisor: Not Available</p>", unsafe_allow_html=True)

                status_to_display = nearest_store.get('store_status')
                if pd.notnull(status_to_display) and str(status_to_display).strip():
                    st.markdown(f"<p class='distance-text'>Status: {str(status_to_display).strip()}</p>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<p class='distance-text'>Status: Not Available</p>", unsafe_allow_html=True)

                hours_to_display = nearest_store.get('store_hours')
                if pd.notnull(hours_to_display) and str(hours_to_display).strip():
                    st.markdown(f"<p class='distance-text'>Hours: {str(hours_to_display).strip()}</p>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<p class='distance-text'>Hours: Not Available</p>", unsafe_allow_html=True)

                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.warning("No stores found in the database to compare with. Please add some stores first.")
        else:
            st.info("Enter your location to find the nearest store.")

        # Map display for user location and stores (now with Pydeck for a realistic route)
        if 'user_lat' in st.session_state and st.session_state.user_lat is not None and st.session_state.user_lon is not None:
            user_lat = st.session_state.user_lat
            user_lon = st.session_state.user_lon

            layers = []
            
            # Add user location to a temporary DataFrame for plotting
            user_location_df = pd.DataFrame([{
                'latitude': user_lat,
                'longitude': user_lon,
                'name': 'Your Location',
                'color': [255, 0, 0, 200], # Red for user
                'radius': 200,
                'type': 'user',
                'description': 'Your current geocoded location.'
            }])
            
            # Prepare stores for map, including highlight for nearest
            stores_for_map_data = []
            if not st.session_state.stores_df.empty:
                for index, store in st.session_state.stores_df.iterrows():
                    color = [0, 0, 255, 160]  # Default blue for general stores
                    radius = 50
                    description = f"{store['name']}<br/>{store['address']}"

                    if nearest_store is not None and store['id'] == nearest_store['id']:
                        color = [0, 255, 0, 200]  # Green for nearest
                        radius = 70
                        description = f"Nearest: {nearest_store['name']}<br/>{nearest_store['address']}<br/>Distance: {min_distance:.2f} km"
                    
                    stores_for_map_data.append({
                        'latitude': store['latitude'],
                        'longitude': store['longitude'],
                        'name': store['name'],
                        'color': color,
                        'radius': radius,
                        'type': 'store',
                        'description': description
                    })
            
            stores_for_map = pd.DataFrame(stores_for_map_data)
            
            all_points_df = pd.concat([user_location_df, stores_for_map], ignore_index=True)
            
            if not all_points_df.empty:
                layers.append(
                    pdk.Layer(
                        "ScatterplotLayer",
                        all_points_df,
                        pickable=True,
                        auto_highlight=True,
                        get_position="[longitude, latitude]",
                        get_color="color",
                        get_radius="radius",
                        tooltip={"text": "{name}\n{description}"} # Tooltip now shows name and description
                    )
                )

            # Add route to nearest store if available and locations are distinct
            if nearest_store is not None and user_lat is not None and user_lon is not None:
                # Check if the locations are identical before drawing the route
                if abs(user_lat - nearest_store['latitude']) < 1e-6 and abs(user_lon - nearest_store['longitude']) < 1e-6:
                    st.info("The nearest store is at your exact location. No route is needed.")
                else:
                    with st.spinner("Calculating the route..."):
                        route_coords = get_route_polyline(user_lat, user_lon, nearest_store['latitude'], nearest_store['longitude'], google_api_key)
                    
                    if route_coords:
                        # Create a DataFrame for the PathLayer
                        route_df = pd.DataFrame([{'path': route_coords}])
                        
                        layers.append(
                            pdk.Layer(
                                "PathLayer",
                                route_df,
                                get_path="path",
                                get_color=[255, 0, 0, 255], # Solid Red path
                                get_width=10, # Thicker path
                                pickable=False,
                                auto_highlight=False
                            )
                        )
                        st.success("Route calculated and displayed on the map!")
                    else:
                        st.warning("Could not calculate a detailed route. Displaying straight line if locations are distinct.")
                        # Fallback to straight line if route API fails but locations are distinct
                        line_data = pd.DataFrame([{
                            'start_lat': user_lat,
                            'start_lon': user_lon,
                            'end_lat': nearest_store['latitude'],
                            'end_lon': nearest_store['longitude'],
                            'color': [255, 165, 0, 255], # Orange for fallback line
                            'width': 8 
                        }])
                        layers.append(
                            pdk.Layer(
                                "LineLayer",
                                line_data,
                                get_source_position="[start_lon, start_lat]",
                                get_target_position="[end_lon, end_lat]",
                                get_color="color",
                                get_stroke_width="width",
                                pickable=False
                            )
                        )
                
            # Set initial view state - center on user location if available, otherwise a default
            view_state = pdk.ViewState(
                latitude=user_lat if user_lat is not None else 25.276987, # Default to Dubai if no user_lat
                longitude=user_lon if user_lon is not None else 55.296249, # Default to Dubai if no user_lon
                zoom=11,
                pitch=45,
            )

            if layers:
                st.pydeck_chart(pdk.Deck(
                    map_style="mapbox://styles/mapbox/light-v9", # Light map style
                    initial_view_state=view_state,
                    layers=layers,
                ))
            else:
                st.info("No locations to display on the map yet.")
        st.markdown("</div>", unsafe_allow_html=True)

    with tab_add_edit_stores:
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        
        # Dynamically change header for Add/Edit form
        form_header = "Edit Store Location" if st.session_state.editing_store_id else "Add New Store Location"
        st.markdown(f"<h3>{form_header}</h3>", unsafe_allow_html=True)

        with st.form("add_edit_store_form", clear_on_submit=not st.session_state.editing_store_id):
            # Pre-fill form if editing
            default_name = st.session_state.editing_store_details.get('name', '')
            default_address = st.session_state.editing_store_details.get('address', '')
            default_contact = st.session_state.editing_store_details.get('contact_number', '')
            default_supervisor = st.session_state.editing_store_details.get('branch_supervisor', '')
            default_status = st.session_state.editing_store_details.get('store_status', '')
            default_hours = st.session_state.editing_store_details.get('store_hours', '')

            new_store_name = st.text_input("Store Name*", value=default_name, key="store_name_form")
            new_store_address = st.text_input("Store Address (e.g., 'Burj Khalifa, Dubai')*", value=default_address, key="store_address_form")
            new_store_contact = st.text_input("Store Contact Number (mobile/landline format)*", value=default_contact, key="store_contact_form")
            new_store_supervisor = st.text_input("Branch Supervisor Name*", value=default_supervisor, key="store_supervisor_form")

            store_status_options = ["", "Operational", "Temporarily Closed", "Permanently Closed"]
            current_status_index = store_status_options.index(default_status) if default_status in store_status_options else 0
            new_store_status = st.selectbox("Store Status*", options=store_status_options, index=current_status_index, key="store_status_form")
            new_store_hours = st.text_input("Store Hours (e.g., '9 AM - 5 PM Mon-Fri')*", value=default_hours, key="store_hours_form")

            submit_button_label = "Update Store Details" if st.session_state.editing_store_id else "Add Store to Database"
            form_submitted = st.form_submit_button(submit_button_label)

            if form_submitted:
                # Validation checks for required fields and formats
                if not str(new_store_name).strip():
                    st.error("Store Name is required.")
                elif not str(new_store_address).strip():
                    st.error("Store Address is required.")
                elif not str(new_store_contact).strip():
                    st.error("Store Contact Number is required.")
                elif not re.match(CONTACT_NUMBER_PATTERN, new_store_contact.strip()):
                    st.error("Store Contact Number must be in a valid mobile/landline format (e.g., +123 456 7890, 050 1234567).")
                elif not str(new_store_supervisor).strip():
                    st.error("Branch Supervisor Name is required.")
                elif not str(new_store_status).strip():
                    st.error("Store Status is required.")
                elif not str(new_store_hours).strip():
                    st.error("Store Hours are required.")
                elif not re.match(STORE_HOURS_PATTERN, new_store_hours.strip()):
                    st.error("Store Hours must be in a valid time format (e.g., '9 AM - 5 PM Mon-Fri', '09:00 - 17:00').")
                else: # All validations passed
                    st.info(f"Geocoding address: '{new_store_address}'...")
                    store_lat, store_lon = get_coordinates_from_address(new_store_address, google_api_key)
                    if store_lat is not None and store_lon is not None:
                        if st.session_state.editing_store_id: # If editing
                            if update_store_in_db(
                                st.session_state.editing_store_id,
                                new_store_name.strip(),
                                new_store_address.strip(),
                                store_lat,
                                store_lon,
                                new_store_contact.strip(),
                                new_store_supervisor.strip(),
                                new_store_status,
                                new_store_hours.strip()
                            ):
                                clear_store_edit_state() # Clear edit state after successful update
                        else: # If adding new
                            if add_store_to_db(new_store_name.strip(), new_store_address.strip(), store_lat, store_lon, new_store_contact.strip(), new_store_supervisor.strip(), new_store_status, new_store_hours.strip()):
                                fetch_stores_from_db_local() # Refresh data
                                # Form clears on submit for new add due to clear_on_submit=True
                    else:
                        st.error("Could not get coordinates. Please check the address and ensure your API key is correctly configured.")
        
        # Cancel Edit button outside the form, visible only when editing
        if st.session_state.editing_store_id:
            if st.button("Cancel Edit", key="cancel_store_edit_button", use_container_width=True):
                clear_store_edit_state()


        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("<h3>All Saved Stores</h3>", unsafe_allow_html=True)
        if not st.session_state.stores_df.empty:
            cols_config = st.columns([0.5, 2, 3, 1.5, 1.5, 1.2, 2, 0.8, 0.8]) # Added column for Edit button

            with cols_config[0]: st.markdown("**ID**")
            with cols_config[1]: st.markdown("**Name**")
            with cols_config[2]: st.markdown("**Address**")
            with cols_config[3]: st.markdown("**Contact**")
            with cols_config[4]: st.markdown("**Supervisor**")
            with cols_config[5]: st.markdown("**Status**")
            with cols_config[6]: st.markdown("**Hours**")
            with cols_config[7]: st.markdown("**Edit**") # Edit button header
            with cols_config[8]: st.markdown("**Delete**") # Delete button header

            st.markdown("---")

            for index, store in st.session_state.stores_df.iterrows():
                row_cols = st.columns([0.5, 2, 3, 1.5, 1.5, 1.2, 2, 0.8, 0.8]) # Columns for data + 2 buttons
                with row_cols[0]: st.write(str(store['id']))
                with row_cols[1]: st.write(store['name'])
                with row_cols[2]: st.write(store['address'])
                with row_cols[3]: st.write(str(store.get('contact_number', 'N/A')))
                with row_cols[4]: st.write(str(store.get('branch_supervisor', 'N/A')))
                with row_cols[5]: st.write(str(store.get('store_status', 'N/A')))
                with row_cols[6]: st.write(str(store.get('store_hours', 'N/A')))
                with row_cols[7]: # Edit button
                    if st.button("✏️", key=f"edit_store_{store['id']}", help=f"Edit {store['name']}", type="secondary"):
                        st.session_state.editing_store_id = store['id']
                        st.session_state.editing_store_details = store.to_dict()
                        st.rerun() # Rerun to update the form
                with row_cols[8]: # Delete button
                    if st.button("🗑️", key=f"delete_store_{store['id']}", help=f"Delete {store['name']}", type="secondary"):
                        # Set session state for modal to appear
                        st.session_state.delete_confirm_modal_active = True
                        st.session_state.store_id_to_confirm_delete = store['id']
                        st.session_state.store_name_to_confirm_delete = store['name']
                        st.rerun()

                st.markdown("---")
        else:
            st.info("No stores currently in the database. Add some using the form above!")

elif selected_page == "Delivery Fee":
    fetch_delivery_fees_from_db_local()
    st.markdown("---")
    
    # Tabs for Delivery Fee section
    tab_search_delivery_fee, tab_add_edit_delivery_fee = st.tabs(["Search Delivery Fee", "Add/Edit Delivery Fee"])

    with tab_search_delivery_fee:
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Search Delivery Fee</h3>", unsafe_allow_html=True)
        st.write("Enter details to search for delivery fee information.")
        
        # Use an st.form for search to enable Enter key submission
        with st.form("delivery_fee_search_form"):
            # Initialize the state variable for the search input
            if 'delivery_search_input' not in st.session_state:
                st.session_state.delivery_search_input = ""

            # The text_input's value is directly tied to the session state variable.
            # When st.rerun() happens, the input's value will reflect st.session_state.delivery_search_input.
            # The 'key' here is for internal Streamlit management of the widget itself,
            # but we explicitly manage the value via the 'value' parameter.
            search_term_input_value = st.text_input(
                "Search by Location or Zone",
                value=st.session_state.delivery_search_input,
                key="delivery_fee_search_input_actual_widget" # Unique key for the widget
            )
            
            # Now only the Search button is present
            search_button_submitted = st.form_submit_button("Search")
            
        # Handle search button (only if search button was pressed or form submitted by Enter)
        if search_button_submitted:
            # When the form is submitted (by search or Enter), update the search query in session state
            # with the *current* value from the text input.
            st.session_state.delivery_search_query = search_term_input_value

            if st.session_state.delivery_search_query.strip():
                keywords = [normalize_string(kw) for kw in st.session_state.delivery_search_query.split() if kw.strip()] # Normalize search keywords
                
                if keywords:
                    # Initialize a boolean series for filtering
                    condition = pd.Series([False] * len(st.session_state.delivery_fees_df), index=st.session_state.delivery_fees_df.index)

                    for keyword in keywords:
                        # Apply normalization to the DataFrame columns for consistent comparison
                        condition = condition | \
                                    (st.session_state.delivery_fees_df['location'].apply(normalize_string).str.contains(keyword, case=False, na=False)) | \
                                    (st.session_state.delivery_fees_df['zone'].apply(normalize_string).str.contains(keyword, case=False, na=False))
                    
                    filtered_df = st.session_state.delivery_fees_df[condition]

                    if not filtered_df.empty:
                        st.markdown("<h4>Search Results:</h4>", unsafe_allow_html=True)
                        # Display using columns for a table-like layout
                        cols_config_search_fee = st.columns([0.5, 2, 1.5, 1.5, 2, 1.5]) 

                        with cols_config_search_fee[0]: st.markdown("**ID**")
                        with cols_config_search_fee[1]: st.markdown("**Location**")
                        with cols_config_search_fee[2]: st.markdown("**Min Order (AED)**")
                        with cols_config_search_fee[3]: st.markdown("**Charge (AED)**")
                        with cols_config_search_fee[4]: st.markdown("**Free Delivery From (AED)**")
                        with cols_config_search_fee[5]: st.markdown("**Zone**")
                        st.markdown("---")

                        for index, fee in filtered_df.iterrows():
                            row_cols_search_fee = st.columns([0.5, 2, 1.5, 1.5, 2, 1.5])
                            with row_cols_search_fee[0]: st.write(str(fee['id']))
                            with row_cols_search_fee[1]: st.write(fee['location'])
                            with row_cols_search_fee[2]: st.write(f"{fee['min_order_amount']:.2f}")
                            with row_cols_search_fee[3]: st.write(f"{fee['delivery_charge']:.2f}")
                            with row_cols_search_fee[4]: st.write(f"{fee['amount_for_free_delivery']:.2f}" if pd.notnull(fee['amount_for_free_delivery']) and fee['amount_for_free_delivery'] > 0 else "N/A")
                            with row_cols_search_fee[5]: st.write(fee['zone'] if pd.notnull(fee['zone']) else "N/A")
                            st.markdown("---")
                    else:
                        st.info(f"No delivery fee entries found matching any of the terms in '{st.session_state.delivery_search_query}'.")
                else:
                    st.info("Please enter a location or zone to search.")
            else:
                st.warning("Please enter a location or zone to search.")
        

        st.markdown("</div>", unsafe_allow_html=True)

    with tab_add_edit_delivery_fee:
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        # Dynamically change header for Add/Edit form
        fee_form_header = "Edit Delivery Fee Entry" if st.session_state.editing_delivery_fee_id else "Add New Delivery Fee Entry"
        st.markdown(f"<h3>{fee_form_header}</h3>", unsafe_allow_html=True)

        with st.form("add_edit_delivery_fee_form", clear_on_submit=not st.session_state.editing_delivery_fee_id): # Clear on submit only for new adds
            default_location = st.session_state.editing_delivery_fee_details.get('location', '')
            default_min_order = st.session_state.editing_delivery_fee_details.get('min_order_amount', 0.0)
            default_charge = st.session_state.editing_delivery_fee_details.get('delivery_charge', 0.0)
            default_free_amount = st.session_state.editing_delivery_fee_details.get('amount_for_free_delivery', 0.0)
            default_zone = st.session_state.editing_delivery_fee_details.get('zone', '')

            new_fee_location = st.text_input("Location*", value=default_location, key="edit_fee_location")
            new_fee_min_order = st.number_input("Minimum Order Amount (AED)*", min_value=0.0, format="%.2f", value=default_min_order, key="edit_fee_min_order")
            new_fee_charge = st.number_input("Delivery Charge (AED)*", min_value=0.0, format="%.2f", value=default_charge, key="edit_fee_charge")
            new_fee_free_amount = st.number_input("Amount for Free Delivery (AED) (optional)", min_value=0.0, format="%.2f", value=default_free_amount, key="edit_fee_free_amount")
            new_fee_zone = st.text_input("Zone (e.g., 'Zone A', 'Downtown')*", value=default_zone, key="edit_fee_zone")

            submit_button_label = "Update Delivery Fee Entry" if st.session_state.editing_delivery_fee_id else "Add Delivery Fee Entry"
            form_submitted = st.form_submit_button(submit_button_label)
            
            if form_submitted:
                # Validation checks for required fields
                if not new_fee_location.strip():
                    st.error("Location is required.")
                elif new_fee_min_order is None or new_fee_min_order < 0:
                    st.error("Minimum Order Amount is required and cannot be negative.")
                elif new_fee_charge is None or new_fee_charge < 0:
                    st.error("Delivery Charge is required and cannot be negative.")
                elif not new_fee_zone.strip(): # Zone is now required
                    st.error("Zone is required.")
                else:
                    if st.session_state.editing_delivery_fee_id:
                        # Update existing entry
                        if update_delivery_fee_in_db(
                            st.session_state.editing_delivery_fee_id,
                            new_fee_location.strip(),
                            new_fee_min_order,
                            new_fee_charge,
                            new_fee_free_amount,
                            new_fee_zone.strip()
                        ):
                            fetch_delivery_fees_from_db_local() # Refresh data
                            clear_delivery_fee_edit_state() # Clear state after update and rerun
                    else:
                        # Add new entry
                        if add_delivery_fee_to_db(
                            new_fee_location.strip(),
                            new_fee_min_order,
                            new_fee_charge,
                            new_fee_free_amount,
                            new_fee_zone.strip()
                        ):
                            fetch_delivery_fees_from_db_local() # Refresh data
                            clear_delivery_fee_edit_state() # Clear state after add and rerun

        # Place Cancel Edit button outside the form, conditionally
        if st.session_state.editing_delivery_fee_id:
            if st.button("Cancel Edit", key="cancel_edit_fee_button_outside", use_container_width=True):
                clear_delivery_fee_edit_state()

        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("<h3>All Saved Delivery Fee Entries</h3>", unsafe_allow_html=True)
        if not st.session_state.delivery_fees_df.empty:
            # Display using columns for a table-like layout
            cols_config_fee = st.columns([0.5, 2, 1.5, 1.5, 2, 1.5, 0.8, 0.8]) # Adjusted column widths for Edit + Delete

            with cols_config_fee[0]: st.markdown("**ID**")
            with cols_config_fee[1]: st.markdown("**Location**")
            with cols_config_fee[2]: st.markdown("**Min Order (AED)**")
            with cols_config_fee[3]: st.markdown("**Charge (AED)**")
            with cols_config_fee[4]: st.markdown("**Free Delivery From (AED)**")
            with cols_config_fee[5]: st.markdown("**Zone**")
            with cols_config_fee[6]: st.markdown("**Edit**")
            with cols_config_fee[7]: st.markdown("**Delete**")

            st.markdown("---")

            for index, fee in st.session_state.delivery_fees_df.iterrows():
                row_cols_fee = st.columns([0.5, 2, 1.5, 1.5, 2, 1.5, 0.8, 0.8])
                with row_cols_fee[0]: st.write(str(fee['id']))
                with row_cols_fee[1]: st.write(fee['location'])
                with row_cols_fee[2]: st.write(f"{fee['min_order_amount']:.2f}")
                with row_cols_fee[3]: st.write(f"{fee['delivery_charge']:.2f}")
                with row_cols_fee[4]: st.write(f"{fee['amount_for_free_delivery']:.2f}" if pd.notnull(fee['amount_for_free_delivery']) and fee['amount_for_free_delivery'] > 0 else "N/A")
                with row_cols_fee[5]: st.write(fee['zone'] if pd.notnull(fee['zone']) else "N/A")
                with row_cols_fee[6]:
                    if st.button("✏️", key=f"edit_fee_{fee['id']}", help=f"Edit fee for {fee['location']}", type="secondary"):
                        st.session_state.editing_delivery_fee_id = fee['id']
                        st.session_state.editing_delivery_fee_details = fee.to_dict()
                        st.rerun() # Rerun to update the form
                with row_cols_fee[7]: # Corrected: Changed 'row_cols' to 'row_cols_fee'
                    if st.button("🗑️", key=f"delete_fee_{fee['id']}", help=f"Delete fee for {fee['location']}", type="secondary"):
                        if delete_delivery_fee_from_db(fee['id']):
                            fetch_delivery_fees_from_db_local() # Refresh data after deletion
                            st.rerun()
                st.markdown("---")
        else:
            st.info("No delivery fee entries currently in the database. Add some using the form above!")


elif selected_page == "Price Calculator":
    st.markdown("---")
    st.markdown("<div classs='input-section'>", unsafe_allow_html=True)
    st.markdown("<h3>Price Calculator</h3>", unsafe_allow_html=True)
    st.write("This section will allow you to calculate prices.")
    item_price = st.number_input("Enter Item Price", min_value=0.0, format="%.2f", key="item_price_input")
    quantity = st.number_input("Enter Quantity", min_value=1, step=1, key="quantity_input")

    if st.button("Calculate Total Price", key="calculate_price_btn"):
        total_price = item_price * quantity
        st.success(f"The total price is: ${total_price:.2f}")

    st.markdown("</div>", unsafe_allow_html=True)

# --- Footer Section ---
st.markdown("<div classs='footer'>", unsafe_allow_html=True)
st.markdown("Copyright 2025", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# Conditional "Popup" for Delete Confirmation (remains unchanged)
if st.session_state.delete_confirm_modal_active:
    store_id_to_delete = st.session_state.store_id_to_confirm_delete
    store_name_to_delete = st.session_state.store_name_to_confirm_delete

    # Inject dynamic CSS for the modal overlay and content box
    st.markdown(
        """
        <style>
        #custom-modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.7);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10000;
        }
        #custom-modal-content {
            background-color: #ffffff;
            border: 2px solid #dc3545;
            border-radius: 12px;
            padding: 2.5rem;
            box-shadow: 0 3px 8px rgba(0,0,0,0.2); /* Reduced shadow for a softer look */
            text-align: center;
            max-width: 550px;
            width: 90%;
            animation: fadeIn 0.3s ease-out;
            color: #343a40;
        }

        #custom-modal-content h4 {
            color: #dc3545;
            margin-bottom: 1.5rem;
            font-size: 1.8rem;
            font-weight: 700;
        }
        #custom-modal-content p {
            font-size: 1.1rem;
            margin-bottom: 2rem;
        }

        #custom-modal-content .stButton > button {
            padding: 0.7rem 1.5rem;
            font-size: 1.05rem;
            border-radius: 8px;
            font-weight: 600;
            box-shadow: 0 3px 8px rgba(0,0,0,0.2);
            transition: all 0.2s ease-in-out; /* Added transition for hover effect */
        }

        #custom-modal-content [data-testid="stHorizontalBlock"] > div:first-child .stButton > button {
            background-color: #28a745;
            color: white;
        }
        #custom-modal-content [data-testid="stHorizontalBlock"] > div:first-child .stButton > button:hover {
            background-color: #218838;
            transform: translateY(-2px); /* Lift effect on hover */
            box-shadow: 0 5px 12px rgba(0,0,0,0.3); /* Enhanced shadow on hover */
        }
        #custom-modal-content [data-testid="stHorizontalBlock"] > div:last-child .stButton > button {
            background-color: #6c757d;
            color: white;
        }
        #custom-modal-content [data-testid="stHorizontalBlock"] > div:last-child .stButton > button:hover {
            background-color: #5a6268;
            transform: translateY(-2px); /* Lift effect on hover */
            box-shadow: 0 5px 12px rgba(0,0,0,0.3); /* Enhanced shadow on hover */
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown('<div id="custom-modal-overlay">', unsafe_allow_html=True)
    with st.container():
        st.markdown('<div id="custom-modal-content">', unsafe_allow_html=True)
        st.markdown(f"<h4>Are you sure you want to delete '{store_name_to_delete}'?</h4>", unsafe_allow_html=True)
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
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
