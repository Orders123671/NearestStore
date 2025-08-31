import streamlit as st
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
import requests
import re # Import regex for normalization
import pydeck as pdk # Import pydeck for advanced mapping
import json # Import json for pretty printing the raw response
import firebase_admin
from firebase_admin import credentials, firestore
import polyline # New import for robust polyline decoding

# --- SET PAGE CONFIGURATION FIRST ---
# This must be the very first Streamlit command executed
st.set_page_config(
    layout="wide",
    page_title="Katrina Knowledge Base Tools",
    page_icon="🧰🎂", # Changed to toolbox and cake icons
    initial_sidebar_state="expanded"
)

# --- Firebase Initialization (CRITICAL) ---
# Check if Firebase app is already initialized to prevent re-initialization
if not firebase_admin._apps:
    try:
        # Load the service account credentials from Streamlit secrets
        firebase_secrets = st.secrets["firestore_service_account"]
        # FIX: Convert the Streamlit secrets AttrDict to a Python dictionary
        cred = credentials.Certificate(dict(firebase_secrets))
        firebase_admin.initialize_app(cred)
        # st.success("Firebase app initialized successfully!")
    except KeyError:
        st.error("Missing Streamlit secret: 'firestore_service_account'. Please add it to your Streamlit secrets file.")
    except Exception as e:
        st.error(f"Error initializing Firebase: {e}. Please check your service account credentials.")

# Get a Firestore client instance
db = firestore.client()

# --- Security PIN ---
# Define a 6-digit PIN for adding/editing records
SECURITY_PIN = "123456"

# --- Regex Patterns for Validation ---
CONTACT_NUMBER_PATTERN = r"^\+?[0-9\s()\s-]{7,15}$"
STORE_HOURS_PATTERN = r"^\d{1,2}(:\d{2})?\s*([AP]M)?\s*-\s*\d{1,2}(:\d{2})?\s*([AP]M)?$"


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
            st.error(f"Error geocoding address '{address}': {data['status']}. {data.get('error_message', '')} Please ensure the address is valid and your API key is correct.")
            return None, None
    except requests.exceptions.RequestException as e:
        st.error(f"Network error or invalid API key for Geocoding API: {e}. Please check your internet connection and API key configuration.")
        return None, None
    except Exception as e:
        st.error(f"An unexpected error occurred during geocoding: {e}")
        return None, None

# --- Function to get route polyline and travel time from Google Directions API ---
def get_route_details(origin_lat, origin_lon, dest_lat, dest_lon, api_key_to_use):
    """
    Gets route polyline and travel time between two points using Google Directions API.
    Returns (list of [longitude, latitude] pairs, travel_time_text) or (None, None).
    """
    if not str(api_key_to_use).strip():
        st.error("Google Maps API Key is not configured. Please set it in your Streamlit secrets as 'GOOGLE_MAPS_API_KEY'. **Also ensure the Directions API is enabled in your Google Cloud Project.**")
        return None, None

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
            polyline_str = data["routes"][0]["overview_polyline"]["points"]
            
            travel_time_text = data["routes"][0]["legs"][0]["duration"]["text"] # Get human-readable duration

            # Use the robust `polyline` library to decode the string
            decoded_polyline = polyline.decode(polyline_str)
            # The library returns lat/lon pairs, so we need to convert to lon/lat for Pydeck
            decoded_polyline_for_pydeck = [[lon, lat] for lat, lon in decoded_polyline]

            return decoded_polyline_for_pydeck, travel_time_text

        elif data["status"] == "ZERO_RESULTS":
            st.warning("No route found between the specified locations. This might mean they are unreachable by road or too close.")
            return None, None
        else:
            st.error(f"Error getting route from Directions API: {data['status']}. {data.get('error_message', '')} Please ensure the locations are valid and your API key has Directions API enabled.")
            return None, None
    except requests.exceptions.RequestException as e:
        st.error(f"Network error or invalid API key for Directions API: {e}. Please check your internet connection and API key configuration.")
        return None, None
    except Exception as e:
        st.error(f"An unexpected error occurred during route calculation: {e}")
        return None, None

# --- Firestore Operations for Stores ---
def add_store_to_db(name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, store_type, google_pin_location):
    """Adds a new store to Firestore database."""
    try:
        normalized_name = normalize_string(name)
        normalized_address = normalize_string(address)
        normalized_store_type = normalize_string(store_type) if store_type else None

        # Check for existing store using normalized name and address
        docs = db.collection('stores').where('normalized_name', '==', normalized_name).where('normalized_address', '==', normalized_address).stream()
        if any(docs):
            st.error(f"A store with the name '{name}' and address '{address}' (or a similar normalized form) already exists!")
            return False

        doc_ref = db.collection('stores').document()
        doc_ref.set({
            'name': name,
            'address': address,
            'latitude': latitude,
            'longitude': longitude,
            'contact_number': contact_number,
            'branch_supervisor': branch_supervisor,
            'store_status': store_status,
            'store_hours': store_hours,
            'store_type': store_type,
            'google_pin_location': google_pin_location, # Added new field
            'normalized_name': normalized_name,
            'normalized_address': normalized_address,
            'normalized_store_type': normalized_store_type,
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        st.success(f"Store '{name}' added successfully!")
        st.cache_data.clear()
        
        # After successful add, increment the counter and force a rerun to clear the form fields
        st.session_state.new_store_form_counter += 1
        st.rerun()
        return True
    except Exception as e:
        st.error(f"Error adding store to database: {e}")
        return False

def update_store_in_db(store_id, name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, store_type, google_pin_location):
    """Updates an existing store in Firestore database."""
    try:
        normalized_name = normalize_string(name)
        normalized_address = normalize_string(address)
        normalized_store_type = normalize_string(store_type) if store_type else None

        # Check for duplicates, excluding the current store being updated
        docs = db.collection('stores').where('normalized_name', '==', normalized_name).where('normalized_address', '==', normalized_address).stream()
        for doc in docs:
            if doc.id != store_id:
                st.error(f"An updated store with the name '{name}' and address '{address}' (or a similar normalized form) already exists for another entry!")
                return False

        doc_ref = db.collection('stores').document(store_id)
        doc_ref.update({
            'name': name,
            'address': address,
            'latitude': latitude,
            'longitude': longitude,
            'contact_number': contact_number,
            'branch_supervisor': branch_supervisor,
            'store_status': store_status,
            'store_hours': store_hours,
            'store_type': store_type,
            'google_pin_location': google_pin_location, # Added new field
            'normalized_name': normalized_name,
            'normalized_address': normalized_address,
            'normalized_store_type': normalized_store_type,
        })
        st.success(f"Store '{name}' (ID: {store_id}) updated successfully!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error updating store in database: {e}")
        return False

def delete_store_from_db(store_id):
    """Deletes a store from Firestore database by its ID."""
    try:
        db.collection('stores').document(store_id).delete()
        st.success(f"Store with ID {store_id} deleted successfully!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error deleting store from database: {e}")
        return False

# --- Firestore Operations for Delivery Fees ---
def add_delivery_fee_to_db(location, min_order_amount, delivery_charge, amount_for_free_delivery, zone):
    """Adds a new delivery fee entry to Firestore database."""
    try:
        normalized_location = normalize_string(location)
        normalized_zone = normalize_string(zone) if zone else '' # Handle optional zone, normalize even if empty

        # Check for existing entry using normalized location and zone
        docs = db.collection('delivery_fees').where('normalized_location', '==', normalized_location).where('normalized_zone', '==', normalized_zone).stream()
        if any(docs):
            st.error(f"Duplicate record: A delivery fee entry for '{location}' in zone '{zone}' (or a similar normalized form) already exists!")
            return False

        doc_ref = db.collection('delivery_fees').document()
        doc_ref.set({
            'location': location,
            'min_order_amount': min_order_amount,
            'delivery_charge': delivery_charge,
            'amount_for_free_delivery': amount_for_free_delivery,
            'zone': zone,
            'normalized_location': normalized_location,
            'normalized_zone': normalized_zone,
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        st.success(f"Delivery fee for '{location}' added successfully!")
        st.cache_data.clear()
        st.rerun()
        return True
    except Exception as e:
        st.error(f"Error adding delivery fee to database: {e}")
        return False

def update_delivery_fee_in_db(fee_id, location, min_order_amount, delivery_charge, amount_for_free_delivery, zone):
    """Updates an existing delivery fee entry in Firestore database."""
    try:
        normalized_location = normalize_string(location)
        normalized_zone = normalize_string(zone) if zone else '' # Handle optional zone, normalize even if empty

        # Check for duplicates, excluding the current fee being updated
        docs = db.collection('delivery_fees').where('normalized_location', '==', normalized_location).where('normalized_zone', '==', normalized_zone).stream()
        for doc in docs:
            if doc.id != fee_id:
                st.error(f"Duplicate record: An updated delivery fee entry for '{location}' in zone '{zone}' (or a similar normalized form) already exists for another entry!")
                return False

        doc_ref = db.collection('delivery_fees').document(fee_id)
        doc_ref.update({
            'location': location,
            'min_order_amount': min_order_amount,
            'delivery_charge': delivery_charge,
            'amount_for_free_delivery': amount_for_free_delivery,
            'zone': zone,
            'normalized_location': normalized_location,
            'normalized_zone': normalized_zone,
        })
        st.success(f"Delivery fee for '{location}' (ID: {fee_id}) updated successfully!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error updating delivery fee in database: {e}")
        return False

def delete_delivery_fee_from_db(fee_id):
    """Deletes a delivery fee entry from Firestore database by its ID."""
    try:
        db.collection('delivery_fees').document(fee_id).delete()
        st.success(f"Delivery fee entry with ID {fee_id} deleted successfully!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error deleting delivery fee from database: {e}")
        return False

# --- Caching Functions (Updated for Firestore) ---
@st.cache_data(ttl=3600) # Cache for 1 hour, or until inputs change (e.g., a function is called with new data)
def fetch_stores_from_db_local():
    """Fetches all stores from Firestore and returns a DataFrame."""
    try:
        docs = db.collection('stores').stream()
        stores_list = []
        for doc in docs:
            store_data = doc.to_dict()
            store_data['id'] = doc.id
            stores_list.append(store_data)
        
        df = pd.DataFrame(stores_list)
        if not df.empty:
            df = df.sort_values(by='timestamp', ascending=False)
            df['id'] = df['id'].astype(str) # Ensure ID is string for display
            # Ensure 'google_pin_location' column exists, even if empty for older data
            if 'google_pin_location' not in df.columns:
                df['google_pin_location'] = ''
            # Ensure normalized columns exist for backward compatibility
            if 'normalized_name' not in df.columns:
                df['normalized_name'] = df['name'].apply(normalize_string)
            if 'normalized_address' not in df.columns:
                df['normalized_address'] = df['address'].apply(normalize_string)
            if 'normalized_store_type' not in df.columns:
                df['normalized_store_type'] = df['store_type'].apply(lambda x: normalize_string(x) if x else None)
        return df
    except Exception as e:
        st.error(f"Error fetching stores from database: {e}")
        return pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours', 'store_type', 'google_pin_location', 'normalized_name', 'normalized_address', 'normalized_store_type'])

@st.cache_data(ttl=3600)
def fetch_delivery_fees_from_db_local():
    """Fetches all delivery fee entries from Firestore and returns a DataFrame."""
    try:
        docs = db.collection('delivery_fees').stream()
        fees_list = []
        for doc in docs:
            fee_data = doc.to_dict()
            fee_data['id'] = doc.id
            fees_list.append(fee_data)
        
        df = pd.DataFrame(fees_list)
        if not df.empty:
            df = df.sort_values(by='timestamp', ascending=False)
            df['id'] = df['id'].astype(str) # Ensure ID is string for display
            # Ensure normalized columns exist, even if they were not present in older documents
            if 'normalized_location' not in df.columns:
                df['normalized_location'] = df['location'].apply(normalize_string)
            if 'normalized_zone' not in df.columns:
                df['normalized_zone'] = df['zone'].apply(lambda x: normalize_string(x) if x else '')

        return df
    except Exception as e:
        st.error(f"Error fetching delivery fees from database: {e}")
        return pd.DataFrame(columns=['id', 'location', 'min_order_amount', 'delivery_charge', 'amount_for_free_delivery', 'zone', 'normalized_location', 'normalized_zone'])

# Call the cached functions to initialize session state DataFrames
st.session_state.stores_df = fetch_stores_from_db_local()
st.session_state.delivery_fees_df = fetch_delivery_fees_from_db_local()


# Initialize Streamlit session state variables
if 'stores_df' not in st.session_state:
    st.session_state.stores_df = pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours', 'store_type', 'google_pin_location', 'timestamp', 'normalized_name', 'normalized_address', 'normalized_store_type']) # Added new columns
if 'editing_store_id' not in st.session_state:
    st.session_state.editing_store_id = None
if 'editing_store_details' not in st.session_state:
    st.session_state.editing_store_details = {}
if 'new_store_form_counter' not in st.session_state: # New counter for form key for Add/Edit tab
    st.session_state.new_store_form_counter = 0

if 'search_form_counter' not in st.session_state: # New counter for search form key for Search Stores tab
    st.session_state.search_form_counter = 0


if 'delivery_fees_df' not in st.session_state:
    st.session_state.delivery_fees_df = pd.DataFrame(columns=['id', 'location', 'min_order_amount', 'delivery_charge', 'amount_for_free_delivery', 'zone', 'timestamp', 'normalized_location', 'normalized_zone'])
if 'editing_delivery_fee_id' not in st.session_state:
    st.session_state.editing_delivery_fee_id = None
if 'editing_delivery_fee_details' not in st.session_state:
    st.session_state.editing_delivery_fee_details = {}

# --- CRITICAL: Use selected_delivery_tab to store the string value ---
if 'selected_delivery_tab' not in st.session_state:
    st.session_state.selected_delivery_tab = "Search/View" # Default to "Search/View" tab as a string
    
# --- CRITICAL: New session state for stores tab management ---
if 'selected_store_tab' not in st.session_state:
    st.session_state.selected_store_tab = "Search Stores"

# Session state for store search input (will be used to manage text_input value)
if 'store_search_input_display' not in st.session_state:
    st.session_state.store_search_input_display = ""
if 'store_search_query' not in st.session_state:
    st.session_state.store_search_query = "" # To hold the query when search is triggered
if 'store_search_type' not in st.session_state: # New session state for search type filter
    st.session_state.store_search_type = "All Stores"
if 'store_results_search_query' not in st.session_state:
    st.session_state.store_results_search_query = ""
    

if 'user_lat' not in st.session_state:
    st.session_state.user_lat = None
if 'user_lon' not in st.session_state:
    st.session_state.user_lon = None

# Session state for price calculator
if 'selected_complexity' not in st.session_state:
    st.session_state.selected_complexity = "--- Select a Complexity ---"
if 'real_cake_size' not in st.session_state:
    st.session_state.real_cake_size = 0.0 # Default value changed to 0.0
if 'dummy_cake_size' not in st.session_state:
    st.session_state.dummy_cake_size = 0.0 # Default value set for initial calculation
if 'add_flavor_charge' not in st.session_state:
    st.session_state.add_flavor_charge = False
if 'selected_toy_complexity' not in st.session_state:
    st.session_state.selected_toy_complexity = "--- Select a Toy Complexity ---"
if 'toy_quantity' not in st.session_state:
    st.session_state.toy_quantity = 0
if 'apply_discount' not in st.session_state:
    st.session_state.apply_discount = False
if 'generate_report' not in st.session_state:
    st.session_state.generate_report = False
    
# Session state for delivery fee search input
if 'fee_search_query' not in st.session_state:
    st.session_state.fee_search_query = ""
    

def set_edit_store_state(store_id):
    """Sets the session state to populate the store form for editing
    and forces the tab to switch to the Add/Edit tab."""
    store_to_edit = st.session_state.stores_df[st.session_state.stores_df['id'] == store_id]
    if not store_to_edit.empty:
        st.session_state.editing_store_id = store_id
        st.session_state.editing_store_details = store_to_edit.iloc[0].to_dict()
        # FIX: Set the tab state to "Add/Edit Stores" to force the switch
        st.session_state.selected_store_tab = "Add/Edit Stores"
        # Removed st.rerun() here as the state change triggers it.
    else:
        st.warning("No store found with that ID.")

def delete_and_rerun_store(store_id):
    """Deletes a store entry and re-fetches data."""
    if delete_store_from_db(store_id):
        st.session_state.stores_df = fetch_stores_from_db_local()
        # Removed st.rerun() here as the state change triggers it.


def set_edit_fee_state(fee_id):
    """Sets the session state to populate the delivery fee form for editing
    and switches to the Add/Edit tab."""
    fee_to_edit = st.session_state.delivery_fees_df[st.session_state.delivery_fees_df['id'] == fee_id]
    if not fee_to_edit.empty:
        st.session_state.editing_delivery_fee_id = fee_id
        st.session_state.editing_delivery_fee_details = fee_to_edit.iloc[0].to_dict()
        st.session_state.selected_delivery_tab = "Add/Edit" # Force "Add/Edit" tab
        # Removed st.rerun() here as the state change triggers it.
    else:
        st.warning("No delivery fee entry found with that ID.")

def delete_and_rerun_fee(fee_id):
    """Deletes a fee entry and reruns the app to refresh the table."""
    if delete_delivery_fee_from_db(fee_id):
        st.session_state.delivery_fees_df = fetch_delivery_fees_from_db_local()
        # Removed st.rerun() here as the state change triggers it.

def clear_delivery_fee_edit_state():
    """Clears the session state for editing a delivery fee,
    keeping the user on the Add/Edit tab with a blank form."""
    st.session_state.editing_delivery_fee_id = None
    st.session_state.editing_delivery_fee_details = {}
    st.session_state.selected_delivery_tab = "Add/Edit" # Stay on Add/Edit tab, with blank form
    # Removed st.rerun() here as the state change triggers it.

def clear_store_edit_state():
    """Clears the session state for editing a store and forces a rerun.
    This is primarily for canceling an edit. It also increments the new store form counter
    to ensure the 'Add' form is fresh after a cancellation."""
    st.session_state.editing_store_id = None
    st.session_state.editing_store_details = {}
    st.session_state.new_store_form_counter += 1 # Increment to ensure next 'Add' form is fresh
    # Removed st.rerun() here as the state change triggers it.
    
def reset_price_calculator_inputs():
    """Resets all input fields on the price calculator page."""
    st.session_state.selected_complexity = "--- Select a Complexity ---"
    st.session_state.real_cake_size = 0.0
    st.session_state.dummy_cake_size = 0.0
    st.session_state.add_flavor_charge = False
    st.session_state.selected_toy_complexity = "--- Select a Toy Complexity ---"
    st.session_state.toy_quantity = 0
    st.session_state.apply_discount = False
    st.session_state.generate_report = False
    
# Load CSS from external file
def load_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.error(f"Error: CSS file '{file_name}' not found. Please ensure style.css is in the same directory as app.py.")

# Apply general styling from style.css
try:
    with open("style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("`style.css` not found. Default Streamlit styles will be used.")

# Add Google Fonts link for 'Inter'
st.markdown('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">', unsafe_allow_html=True)

st.markdown("<h1 class='main-header'>🧰🎂 Katrina Knowledge Base Tools</h1>", unsafe_allow_html=True) # Updated header with new icons
st.markdown("<p class='subheader'>Your one stop shop Tools</p>", unsafe_allow_html=True)

# Retrieve API key from Streamlit secrets
try:
    google_api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
except KeyError:
    st.error("Missing Streamlit secret: 'GOOGLE_MAPS_API_KEY'. Please add it to your Streamlit secrets file.")
    google_api_key = ""

# Retrieve Mapbox API key from Streamlit secrets
try:
    mapbox_api_key = st.secrets["MAPBOX_API_KEY"]
    # Set Mapbox API key as a global Pydeck setting
    pdk.settings.mapbox_api_key = mapbox_api_key
except KeyError:
    st.warning("Missing Streamlit secret: 'MAPBOX_API_KEY'. Pydeck maps may not render correctly without it. Please add it to your Streamlit secrets file.")
    # Assign an empty string or None if not found, as pydeck.settings will handle it.
    mapbox_api_key = ""    


# --- Sidebar Navigation ---
st.sidebar.markdown(
    "<h3 style='color: DarkPink; text-align: center;'>🎂 Katrina Coffee and Cakes 🎂</h3>",
    unsafe_allow_html=True
)
st.sidebar.markdown("---")

selected_page = st.sidebar.radio(
    "Go to",
    ["Find Store/Add/Edit", "Delivery Fee", "Price Calculator", "General Info"]
)

# Define store types globally or at least consistently
STORE_TYPES = ["All Stores", "Smart Seven", "KCC", "Other"]

if selected_page == "Find Store/Add/Edit":
    st.session_state.stores_df = fetch_stores_from_db_local() # Always get latest from cache
    st.markdown("---")
    
    store_tab_options = ["Search Stores", "Add/Edit Stores"]

    # This is the key change: use st.radio with session state for tab control
    def on_store_radio_change():
        st.session_state.selected_store_tab = st.session_state.store_tab_selector_widget

    # FIX: The widget now directly returns the value, and we store it in session state.
    selected_store_tab = st.radio(
        "Select a section:",
        store_tab_options,
        index=store_tab_options.index(st.session_state.selected_store_tab),
        key="store_tab_selector_widget",
        on_change=on_store_radio_change,
        help="Navigate between searching and managing stores."
    )

    if selected_store_tab == "Search Stores":
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Search Nearest Store</h3>", unsafe_allow_html=True)
        st.write("Enter your location to find the nearest store.")

        # Wrap the input and button in a form so Enter key triggers submission
        with st.form("find_nearest_store_form_tab"):
            # Use session state for input value, controlled by the form submission
            user_address_input = st.text_input(
                "Enter your Address (e.g., 'Burj Khalifa, Dubai')",
                value=st.session_state.store_search_input_display,
                key="search_address_input_tab"
            )
            
            # New dropdown for store type filter with dynamic key for state reset
            selected_store_type_filter = st.selectbox(
                "Filter by Store Type",
                options=STORE_TYPES,
                index=STORE_TYPES.index(st.session_state.store_search_type),
                key=f"store_type_filter_search_{st.session_state.search_form_counter}" # Dynamic key for selectbox
            )
            
            # Only one button: "Find Nearest Store"
            find_button = st.form_submit_button(
                label="Find Nearest Store",
                help="Click to find the store closest to your entered address."
            )

        # If the search button is clicked or a previous search query exists
        if find_button:
            # Update the persistent search query and type
            st.session_state.store_search_query = user_address_input
            st.session_state.store_search_type = selected_store_type_filter
            st.session_state.store_search_input_display = "" # Clear the input field after submission
            st.session_state.search_form_counter += 1 # Increment to force fresh form on next render
            st.rerun() # Explicit rerun to ensure UI fully reflects new state
        
        # Only proceed with map and results if a query has been submitted
        if st.session_state.store_search_query:
            # Geocode user's location
            st.session_state.user_lat, st.session_state.user_lon = get_coordinates_from_address(st.session_state.store_search_query, google_api_key)

            if st.session_state.user_lat and st.session_state.user_lon:
                # Filter stores by type if not "All Stores"
                filtered_stores = st.session_state.stores_df.copy()
                if st.session_state.store_search_type != "All Stores":
                    # FIX: Use normalized_store_type for filtering
                    normalized_filter_type = normalize_string(st.session_state.store_search_type)
                    filtered_stores = filtered_stores[filtered_stores['normalized_store_type'] == normalized_filter_type]
                
                if not filtered_stores.empty:
                    # Calculate distance to all stores
                    filtered_stores['distance_km'] = filtered_stores.apply(
                        lambda row: haversine(st.session_state.user_lat, st.session_state.user_lon, row['latitude'], row['longitude']),
                        axis=1
                    )
                    
                    # Sort by distance and get the top 3 stores
                    top_three_stores = filtered_stores.sort_values(by='distance_km').head(3)
                    
                    st.subheader("Search Results")
                    
                    # Display details for each of the top 3 stores
                    for index, nearest_store in top_three_stores.iterrows():
                        st.markdown(f"---")
                        st.info(f"**{nearest_store['name']}** in **{nearest_store['address']}**, approximately **{nearest_store['distance_km']:.2f} km** away.")

                        # Get route polyline and travel time
                        route_polyline, travel_time_text = get_route_details(st.session_state.user_lat, st.session_state.user_lon, nearest_store['latitude'], nearest_store['longitude'], google_api_key)
                        
                        if travel_time_text:
                            st.info(f"Estimated travel time: **{travel_time_text}**")
                        else:
                            st.warning("Could not retrieve route details (e.g., travel time). The locations might be too close or the Google Directions API had an issue.")
                        
                        st.markdown("---")
                        st.subheader(f"Details for {nearest_store['name']}")
                        st.write(f"**Address:** {nearest_store['address']}")
                        st.write(f"**Google PIN Location:** {nearest_store.get('google_pin_location', 'N/A')}")
                        st.write(f"**Branch Supervisor:** {nearest_store.get('branch_supervisor', 'N/A')}")
                        st.write(f"**Contact Number:** {nearest_store.get('contact_number', 'N/A')}")
                        st.write(f"**Store Status:** {nearest_store.get('store_status', 'N/A')}")
                        st.write(f"**Store Hours:** {nearest_store.get('store_hours', 'N/A')}")


                    # Create a DataFrame for the map
                    map_data = top_three_stores.rename(columns={'latitude': 'lat', 'longitude': 'lon'})
                    map_data['icon_data'] = [
                        {"path": "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5S10.62 6.5 12 6.5s2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z", 
                         "fill_color": [255, 0, 0] if i == 0 else [0, 128, 0], # Use index for highlighting the nearest
                         "stroke_width": 0, "fill_opacity": 1.0, "scale": 100} # Increased scale
                        for i, (index, row) in enumerate(map_data.iterrows())
                    ]
                    
                    # Add user's location to the map data
                    user_location_df = pd.DataFrame([{
                        'name': 'Your Location',
                        'address': st.session_state.store_search_query,
                        'lat': st.session_state.user_lat,
                        'lon': st.session_state.user_lon,
                        'icon_data': {"path": "M20.94 11c-.46-4.17-3.37-7.6-7.14-9.35C13.43 1.25 12.72 1 12 1c-.72 0-1.43.25-1.8.65-3.77 1.75-6.68 5.18-7.14 9.35H2v2h2.06c.46 4.17 3.37 7.6 7.14 9.35.37.18.78.29 1.2.35V24h2v-1.65c.42-.06.83-.17 1.2-.35 3.77-1.75 6.68-5.18 7.14-9.35H22v-2h-1.06zm-8.88 9.35c-2.91-1.47-5.1-4.08-5.78-7.35h11.55c-.68 3.27-2.87 5.88-5.77 7.35z", "fill_color": [0, 0, 255], "stroke_width": 0, "fill_opacity": 1.0, "scale": 100} # Increased scale
                    }])
                    
                    map_data = pd.concat([map_data, user_location_df], ignore_index=True)

                    # Create a pydeck map
                    view_state = pdk.ViewState(
                        latitude=st.session_state.user_lat,
                        longitude=st.session_state.user_lon,
                        zoom=12, # Increased zoom level
                        pitch=45,
                    )

                    layers = []
                    
                    # Add Route Layer for each of the top 3 stores
                    for index, store in top_three_stores.iterrows():
                        route_polyline, _ = get_route_details(st.session_state.user_lat, st.session_state.user_lon, store['latitude'], store['longitude'], google_api_key)
                        if route_polyline and len(route_polyline) > 1:
                            route_layer = pdk.Layer(
                                 "PathLayer",
                                 data=[{"path": route_polyline}],
                                 get_path="path",
                                 get_color=[255, 255, 0],  # Yellow routes
                                 width_min_pixels=6,
                                 pickable=True,
                                 auto_highlight=True
                             )
                            layers.append(route_layer)
                             
                    # Add Icon Layer for Stores and User Location
                    icon_layer = pdk.Layer(
                        "IconLayer",
                        data=map_data,
                        get_position="[lon, lat]",
                        get_icon="icon_data",
                        get_size=40, # This size interacts with the scale in icon_data
                        pickable=True
                    )
                    
                    # Add tooltip and pickability
                    tooltip = {
                        "html": "<b>{name}</b><br/>{address}",
                        "style": {"backgroundColor": "steelblue", "color": "white"}
                    }
                    
                    layers.append(icon_layer)
                    
                    # Create the Deckgl map
                    deck = pdk.Deck(
                        map_style="mapbox://styles/mapbox/light-v10",
                        initial_view_state=view_state,
                        layers=layers,
                        tooltip=tooltip,
                    )
                    st.pydeck_chart(deck)
                    
                else:
                    st.warning(f"No stores of type '{st.session_state.store_search_type}' found in the database. Please check your data.")
            else:
                st.error("Could not find coordinates for the entered address. Please try again with a more specific location.")
        else:
            st.info("Please enter a location and click 'Find Nearest Store' to begin your search.")

    elif selected_store_tab == "Add/Edit Stores":
        st.markdown("<div class='input-section'>", unsafe_allow_html=True) # Added div for styling
        st.markdown("<h3>Add/Edit Stores</h3>", unsafe_allow_html=True)
        st.info("To add or edit a store, please enter the required details below.")

        # Display the search bar
        st.text_input(
            "Search for an existing store to edit:",
            placeholder="Search by name, address, or type...",
            key="store_results_search_query"
        )
        
        st.markdown("---")
        
        # Determine if we're in edit mode
        is_edit_mode = st.session_state.editing_store_id is not None
        
        # Use a unique key for the form that changes based on edit mode and ID
        # For new entries, use the new_store_form_counter to ensure key uniqueness after submission
        form_key = f"add_edit_store_form_id_{st.session_state.editing_store_id}" if is_edit_mode else f"add_edit_store_form_new_{st.session_state.new_store_form_counter}"

        # Display the form for adding/editing a store
        with st.form(form_key):
            st.markdown("<h4>{} Store</h4>".format("Edit" if is_edit_mode else "Add"), unsafe_allow_html=True)
            
            # Form inputs - ensure unique keys that change with editing_store_id or the form counter
            # And crucially, set value explicitly to '' if not in edit mode
            name = st.text_input("Store Name", value=st.session_state.editing_store_details.get('name', '') if is_edit_mode else '', key=f"store_name_input_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")
            address = st.text_input("Address", value=st.session_state.editing_store_details.get('address', '') if is_edit_mode else '', key=f"store_address_input_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")
            contact_number = st.text_input("Contact Number (e.g., +971 50 123 4567)", value=st.session_state.editing_store_details.get('contact_number', '') if is_edit_mode else '', key=f"contact_number_input_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")
            branch_supervisor = st.text_input("Branch Supervisor", value=st.session_state.editing_store_details.get('branch_supervisor', '') if is_edit_mode else '', key=f"branch_supervisor_input_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")
            
            # For selectbox, similar logic to set index
            store_status_options = ["--- Select Status ---", "Operational", "Temporarily Closed", "Permanently Closed"]
            if is_edit_mode and st.session_state.editing_store_details.get('store_status') in store_status_options:
                current_store_status_index = store_status_options.index(st.session_state.editing_store_details.get('store_status'))
            else:
                current_store_status_index = 0 # Default to "--- Select Status ---" for new entries
            store_status = st.selectbox("Store Status", store_status_options, index=current_store_status_index, key=f"store_status_select_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")
            
            store_hours = st.text_input("Store Hours (e.g., 9 AM - 10 PM)", value=st.session_state.editing_store_details.get('store_hours', '') if is_edit_mode else '', key=f"store_hours_input_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")
            
            # New field for store type
            store_type_options_with_select = ["--- Select Type ---"] + STORE_TYPES[1:] # Exclude "All Stores"
            if is_edit_mode and st.session_state.editing_store_details.get('store_type') in store_type_options_with_select:
                current_store_type_index = store_type_options_with_select.index(st.session_state.editing_store_details.get('store_type'))
            else:
                current_store_type_index = 0 # Default to "--- Select Type ---" for new entries
            
            store_type = st.selectbox("Store Type", options=store_type_options_with_select, index=current_store_type_index, key=f"store_type_select_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")
            
            # NEW FIELD FOR GOOGLE PIN LOCATION
            google_pin_location = st.text_input("Google PIN Location (e.g., plus code or name)", value=st.session_state.editing_store_details.get('google_pin_location', '') if is_edit_mode else '', key=f"google_pin_input_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")

            # New PIN field for security
            if is_edit_mode:
                pin_label = "Enter PIN to update"
            else:
                pin_label = "Enter PIN to add"
            user_pin = st.text_input(pin_label, type="password", key=f"pin_input_{st.session_state.editing_store_id}_{st.session_state.new_store_form_counter}")

            # Form submission buttons - arranged in columns
            col1, col2 = st.columns(2)
            with col1:
                submit_button = st.form_submit_button(label="{} Store".format("Update" if is_edit_mode else "Add"))
            with col2:
                if is_edit_mode:
                    cancel_button = st.form_submit_button(label="Cancel Edit", on_click=clear_store_edit_state) 

            # Handle form submission
            if submit_button:
                if user_pin != SECURITY_PIN:
                    st.error("Incorrect PIN. Record was not saved.")
                elif not name or not address:
                    st.error("Store Name and Address are required.")
                # Added validation for default selections in add mode
                elif not is_edit_mode and store_status == "--- Select Status ---":
                    st.error("Please select a valid Store Status.")
                elif not is_edit_mode and store_type == "--- Select Type ---":
                    st.error("Please select a valid Store Type.")
                elif contact_number and not re.match(CONTACT_NUMBER_PATTERN, contact_number):
                    st.error("Invalid contact number format. Please use a valid international format.")
                elif store_hours and not re.match(STORE_HOURS_PATTERN, store_hours):
                    st.error("Invalid store hours format. Please use a format like '9 AM - 10 PM' or '9:00 - 22:00'.")
                else:
                    lat, lon = get_coordinates_from_address(address, google_api_key)
                    if lat and lon:
                        # If in edit mode, ensure '--- Select Status ---' is not saved as actual status
                        final_store_status = None if store_status == "--- Select Status ---" else store_status
                        final_store_type = None if store_type == "--- Select Type ---" else store_type

                        if is_edit_mode:
                            if update_store_in_db(st.session_state.editing_store_id, name, address, lat, lon, contact_number, branch_supervisor, final_store_status, store_hours, final_store_type, google_pin_location):
                                clear_store_edit_state() 
                        else:
                            # add_store_to_db now handles incrementing the counter and rerunning
                            add_store_to_db(name, address, lat, lon, contact_number, branch_supervisor, final_store_status, store_hours, final_store_type, google_pin_location)
                            
        st.markdown("---")
        st.markdown("<h4>Existing Stores</h4>", unsafe_allow_html=True)
        
        # Display existing stores with edit/delete buttons
        if not st.session_state.stores_df.empty:
            
            # --- New Filtering Logic ---
            filtered_df = st.session_state.stores_df
            if st.session_state.store_results_search_query:
                normalized_query = normalize_string(st.session_state.store_results_search_query)
                filtered_df = filtered_df[
                    filtered_df['normalized_name'].str.contains(normalized_query, na=False) |
                    filtered_df['normalized_address'].str.contains(normalized_query, na=False) |
                    filtered_df['normalized_store_type'].str.contains(normalized_query, na=False)
                ]

            if not filtered_df.empty:
                stores_df_sorted = filtered_df.sort_values(by='name')
                
                # Adjusted columns to include the new field
                header_cols = st.columns([0.5, 1.5, 2, 1.5, 1.5, 1, 1, 1, 1.5])
                with header_cols[0]: st.markdown("<strong>ID</strong>", unsafe_allow_html=True)
                with header_cols[1]: st.markdown("<strong>Name</strong>", unsafe_allow_html=True)
                with header_cols[2]: st.markdown("<strong>Address</strong>", unsafe_allow_html=True)
                with header_cols[3]: st.markdown("<strong>Contact</strong>", unsafe_allow_html=True)
                with header_cols[4]: st.markdown("<strong>Supervisor</strong>", unsafe_allow_html=True)
                with header_cols[5]: st.markdown("<strong>Status</strong>", unsafe_allow_html=True)
                with header_cols[6]: st.markdown("<strong>Hours</strong>", unsafe_allow_html=True)
                with header_cols[7]: st.markdown("<strong>PIN</strong>", unsafe_allow_html=True)
                with header_cols[8]: st.markdown("<strong>Actions</strong>", unsafe_allow_html=True)
                st.markdown("---")

                for index, row in stores_df_sorted.iterrows():
                    # Adjusted columns to include the new field
                    row_cols = st.columns([0.5, 1.5, 2, 1.5, 1.5, 1, 1, 1, 1.5])
                    with row_cols[0]: st.write(row['id'])
                    with row_cols[1]: st.write(row['name'])
                    with row_cols[2]: st.write(row['address'])
                    with row_cols[3]: st.write(row['contact_number'] if row['contact_number'] else '-')
                    with row_cols[4]: st.write(row['branch_supervisor'] if row['branch_supervisor'] else '-')
                    with row_cols[5]: st.write(row['store_status'] if row['store_status'] else '-')
                    with row_cols[6]: st.write(row['store_hours'] if row['store_hours'] else '-')
                    with row_cols[7]: st.write(row['google_pin_location'] if 'google_pin_location' in row and row['google_pin_location'] else '-')
                    with row_cols[8]:
                        edit_button_col, delete_button_col = st.columns(2)
                        with edit_button_col:
                            st.button(
                                "✏️", 
                                key=f"edit_store_add_edit_{row['id']}", # Unique key for this tab's button
                                help="Edit this store",
                                on_click=set_edit_store_state,
                                args=(row['id'],)
                            )
                        with delete_button_col:
                            # Removed the modal logic. Now directly calls delete_and_rerun_store
                            st.button(
                                "🗑️", 
                                key=f"delete_store_add_edit_{row['id']}", # Unique key for this tab's button
                                help="Delete this store",
                                on_click=delete_and_rerun_store,
                                args=(row['id'],)
                            )
                st.markdown("---")
            else:
                st.info("No stores found matching your search criteria. Please try a different search term.")
        else:
            st.info("No store entries yet. Add one using the form above!")
        


elif selected_page == "Delivery Fee":
    # Ensure this is called at the very beginning of the Delivery Fee section
    # to get the freshest data BEFORE any operations or rendering.
    st.session_state.delivery_fees_df = fetch_delivery_fees_from_db_local()
    st.markdown("---")
    
    delivery_tab_options = ["Search/View", "Add/Edit"]

    # Determine the initial selected tab based on editing state
    initial_selected_tab_value = st.session_state.selected_delivery_tab
        
    # Set the radio button's index based on the string value in session state
    initial_radio_index = delivery_tab_options.index(initial_selected_tab_value)

    # Callback function for the radio button
    def on_radio_change():
        st.session_state.selected_delivery_tab = st.session_state.delivery_tab_selector_widget
        # If the user manually switches back to Search/View, clear any pending edits
        if st.session_state.selected_delivery_tab == "Search/View":
            st.session_state.editing_delivery_fee_id = None
            st.session_state.editing_delivery_fee_details = {}

    st.radio(
        "Select a section:",
        delivery_tab_options,
        index=initial_radio_index, # Initialize with the correct index
        key="delivery_tab_selector_widget", # Use a key for the widget itself
        on_change=on_radio_change, # Update session state when user clicks radio
        help="Navigate between viewing and managing delivery fees."
    )
    
    # --- NOW CHECK AGAINST THE STRING VALUES ---
    if st.session_state.selected_delivery_tab == "Search/View":
        st.markdown("<h3>Search and View Delivery Fees</h3>", unsafe_allow_html=True)
        
        search_query = st.text_input(
            "Search by Location or Zone:",
            placeholder="e.g., Al Barsha, Downtown Dubai, Zone A",
            key="delivery_fee_search_query"
        )
        
        # New search logic with normalization
        if search_query:
            normalized_query = normalize_string(search_query)
            filtered_df = st.session_state.delivery_fees_df[
                st.session_state.delivery_fees_df['normalized_location'].str.contains(normalized_query, na=False) |
                st.session_state.delivery_fees_df['normalized_zone'].str.contains(normalized_query, na=False)
            ]
        else:
            filtered_df = st.session_state.delivery_fees_df
            
        if not filtered_df.empty:
            filtered_df = filtered_df.sort_values(by='location')

            st.markdown("---")
            # Removed the "Actions" header and the edit button from this view
            header_cols = st.columns([0.5, 2, 1.5, 1.5, 1.5, 1.5]) 
            with header_cols[0]: st.markdown("<strong>ID</strong>", unsafe_allow_html=True)
            with header_cols[1]: st.markdown("<strong>Location</strong>", unsafe_allow_html=True)
            with header_cols[2]: st.markdown("<strong>Zone</strong>", unsafe_allow_html=True)
            with header_cols[3]: st.markdown("<strong>Min Order (AED)</strong>", unsafe_allow_html=True)
            with header_cols[4]: st.markdown("<strong>Charge (AED)</strong>", unsafe_allow_html=True)
            with header_cols[5]: st.markdown("<strong>Free At (AED)</strong>", unsafe_allow_html=True)
            st.markdown("---")
            
            for index, row in filtered_df.iterrows():
                # Removed the "Actions" column content
                row_cols = st.columns([0.5, 2, 1.5, 1.5, 1.5, 1.5]) 
                with row_cols[0]: st.write(row['id'])
                with row_cols[1]: st.write(row['location'])
                with row_cols[2]: st.write(row['zone'] if row['zone'] else '-')
                with row_cols[3]: st.write(f"AED {row['min_order_amount']:.2f}")
                with row_cols[4]: st.write(f"AED {row['delivery_charge']:.2f}")
                with row_cols[5]: st.write(f"AED {row['amount_for_free_delivery']:.2f}" if row['amount_for_free_delivery'] and row['amount_for_free_delivery'] > 0 else '-')
            st.markdown("---")
        else:
            st.info("No delivery fee data found. Use the 'Add/Edit' tab to add an entry.")
            
    elif st.session_state.selected_delivery_tab == "Add/Edit":
        st.markdown("<h3>Add/Edit Delivery Fees</h3>", unsafe_allow_html=True)
        is_edit_mode = st.session_state.editing_delivery_fee_id is not None
        
        # Use a unique key for the form that changes based on edit mode and ID
        form_key = f"add_edit_fee_form_id_{st.session_state.editing_delivery_fee_id}" if is_edit_mode else "add_edit_fee_form_new"

        with st.form(form_key):
            st.markdown("<h4>{} Delivery Fee</h4>".format("Edit" if is_edit_mode else "Add"), unsafe_allow_html=True)
            
            location = st.text_input("Location/City", value=st.session_state.editing_delivery_fee_details.get('location', '') if is_edit_mode else '', key="location_input")
            zone = st.text_input("Zone (Optional)", value=st.session_state.editing_delivery_fee_details.get('zone', '') if is_edit_mode else '', key="zone_input")
            min_order_amount = st.number_input("Min. Order Amount (AED)", min_value=0.0, value=st.session_state.editing_delivery_fee_details.get('min_order_amount', 0.0) if is_edit_mode else 0.0, step=1.0, key="min_order_input")
            delivery_charge = st.number_input("Delivery Charge (AED)", min_value=0.0, value=st.session_state.editing_delivery_fee_details.get('delivery_charge', 0.0) if is_edit_mode else 0.0, step=1.0, key="delivery_charge_input")
            amount_for_free_delivery = st.number_input("Amount for Free Delivery (AED, Optional)", min_value=0.0, value=st.session_state.editing_delivery_fee_details.get('amount_for_free_delivery', 0.0) if is_edit_mode else 0.0, step=1.0, key="free_delivery_input")
            
            # New PIN field for security
            if is_edit_mode:
                pin_label = "Enter PIN to update"
            else:
                pin_label = "Enter PIN to add"
            user_pin = st.text_input(pin_label, type="password", key=f"pin_input_fee_{st.session_state.editing_delivery_fee_id}")

            # Adjusted columns to bring buttons closer
            button_col1, button_col2, _ = st.columns([0.2, 0.2, 0.6]) 
            with button_col1:
                submit_button = st.form_submit_button(label="{} Fee".format("Update" if is_edit_mode else "Add"))
            with button_col2:
                if is_edit_mode:
                    cancel_button = st.form_submit_button(label="Cancel Edit", on_click=clear_delivery_fee_edit_state) 
            
            if submit_button:
                if user_pin != SECURITY_PIN:
                    st.error("Incorrect PIN. Record was not saved.")
                elif not location:
                    st.error("Location/City is a required field.")
                else:
                    if is_edit_mode:
                        # Attempt to update the fee
                        if update_delivery_fee_in_db(st.session_state.editing_delivery_fee_id, location, min_order_amount, delivery_charge, amount_for_free_delivery, zone):
                            # IMPORTANT: Re-fetch the data immediately after a successful update
                            st.session_state.delivery_fees_df = fetch_delivery_fees_from_db_local()
                            # If update is successful, clear form, and stay on "Add/Edit" tab
                            st.session_state.editing_delivery_fee_id = None
                            st.session_state.editing_delivery_fee_details = {}
                            st.session_state.selected_delivery_tab = "Add/Edit" # Stay on Add/Edit tab
                            st.rerun() # Explicit rerun to ensure UI updates after state changes
                    else:
                        # Add new fee
                        if add_delivery_fee_to_db(location, min_order_amount, delivery_charge, amount_for_free_delivery, zone):
                            # IMPORTANT: Re-fetch the data immediately after a successful add
                            st.session_state.delivery_fees_df = fetch_delivery_fees_from_db_local()
                            st.session_state.selected_delivery_tab = "Add/Edit" # Stay on Add/Edit tab after adding
                            st.rerun() # Explicit rerun to ensure UI updates after state changes
        
        st.markdown("---")
        st.markdown("<h4>Existing Delivery Fees</h4>", unsafe_allow_html=True)
        
        if not st.session_state.delivery_fees_df.empty:
            fees_df_sorted = st.session_state.delivery_fees_df.sort_values(by='location')

            header_cols = st.columns([0.5, 2, 1.5, 1.5, 1.5, 1.5, 1.5])
            with header_cols[0]: st.markdown("<strong>ID</strong>", unsafe_allow_html=True)
            with header_cols[1]: st.markdown("<strong>Location</strong>", unsafe_allow_html=True)
            with header_cols[2]: st.markdown("<strong>Zone</strong>", unsafe_allow_html=True)
            with header_cols[3]: st.markdown("<strong>Min Order (AED)</strong>", unsafe_allow_html=True)
            with header_cols[4]: st.markdown("<strong>Charge (AED)</strong>", unsafe_allow_html=True)
            with header_cols[5]: st.markdown("<strong>Free At (AED)</strong>", unsafe_allow_html=True)
            with header_cols[6]: st.markdown("<strong>Actions</strong>", unsafe_allow_html=True)
            st.markdown("---")

            for index, row in fees_df_sorted.iterrows():
                row_cols = st.columns([0.5, 2, 1.5, 1.5, 1.5, 1.5, 1.5])
                with row_cols[0]: st.write(row['id'])
                with row_cols[1]: st.write(row['location'])
                with row_cols[2]: st.write(row['zone'] if row['zone'] else '-')
                with row_cols[3]: st.write(f"AED {row['min_order_amount']:.2f}")
                with row_cols[4]: st.write(f"AED {row['delivery_charge']:.2f}")
                with row_cols[5]: st.write(f"AED {row['amount_for_free_delivery']:.2f}" if row['amount_for_free_delivery'] and row['amount_for_free_delivery'] > 0 else '-')
                with row_cols[6]:
                    edit_button_col, delete_button_col = st.columns(2)
                    with edit_button_col:
                        st.button(
                            "✏️", 
                            key=f"edit_fee_add_edit_{row['id']}", # Unique key for this tab's button
                            help="Edit this entry",
                            on_click=set_edit_fee_state,
                            args=(row['id'],)
                        )
                    with delete_button_col:
                        st.button(
                            "🗑️", 
                            key=f"delete_fee_add_edit_{row['id']}", # Unique key for this tab's button
                            help="Delete this entry",
                            on_click=delete_and_rerun_fee,
                            args=(row['id'],)
                        )
            st.markdown("---")
        else:
            st.info("No delivery fee entries yet. Add one using the form above!")


elif selected_page == "Price Calculator":
    # --- Cake Price Calculator Page ---
    st.markdown("---")
    st.header("🎂 Customize Cake Calculator")
    st.markdown("Use the options below to build your perfect custom cake and get an estimated price.")
    
    # Define prices for cake complexity and toy complexity
    cake_complexity_prices = {
        "Design by Cream Easy": 126.00,
        "Design by Cream Medium": 147.00,
        "Design by Cream Hard": 157.50,
        "Design by Cream Super Hard": 183.75,
        "Design by Sugarpaste Medium": 183.75,
        "Design by Sugarpaste Hard": 204.75,
        "Design by Sugarpaste Super Hard": 225.75,
        "Design by Sugarpaste VIP": 246.75,
    }

    toy_complexity_prices = {
        "Easy": 26.25,
        "Medium": 52.50,
        "Hard": 84.00,
    }
    
    # User inputs for cake customization, using session state for values
    st.subheader("1. Cake Base & Quantity")
    
    # Dropdown for cake complexity
    complexity_options = ["--- Select a Complexity ---"] + list(cake_complexity_prices.keys())
    
    if st.session_state.selected_complexity not in complexity_options:
        st.session_state.selected_complexity = "--- Select a Complexity ---"
        
    selected_complexity = st.selectbox(
        "Choose Complexity:",
        options=complexity_options,
        index=complexity_options.index(st.session_state.selected_complexity),
        key='selected_complexity'
    )
    
    # Input for Real Cake Size
    real_cake_size = st.number_input(
        "Real Cake Size (kg):",
        min_value=0.0,
        step=0.1,
        key='real_cake_size'
    )
    
    # Input for Dummy cake size
    dummy_cake_size = st.number_input(
        "Dummy Cake Size (kg):",
        min_value=0.0,
        step=0.1,
        key='dummy_cake_size'
    )
    
    st.markdown("---")

    st.subheader("2. Flavors & Toys")
    
    # Checkbox for flavor charge
    add_flavor_charge = st.checkbox("Add flavor charge (AED 21 per kg)", key='add_flavor_charge')

    # Dropdown for toy complexity
    toy_complexity_options = ["--- Select a Toy Complexity ---"] + list(toy_complexity_prices.keys())
    
    if st.session_state.selected_toy_complexity not in toy_complexity_options:
        st.session_state.selected_toy_complexity = "--- Select a Complexity ---"
        
    selected_toy_complexity = st.selectbox(
        "Choose Toy Complexity:",
        options=toy_complexity_options,
        index=toy_complexity_options.index(st.session_state.selected_toy_complexity),
        key='selected_toy_complexity'
    )
    
    # Input for toy quantity
    toy_quantity = st.number_input(
        "Quantity of Toys:",
        min_value=0,
        step=1,
        key='toy_quantity'
    )
    
    st.markdown("---")

    st.subheader("3. Discount")
    
    # Checkbox for discount
    apply_discount = st.checkbox("Apply 10% discount to overall price", key='apply_discount')

    st.markdown("---")
    
    st.subheader("Total Price")
    
    # Initialize all costs to zero
    total_cake_price = 0
    total_dummy_price = 0
    total_price_flavor = 0
    total_toy_price = 0
    
    # Get the base price based on selection
    base_price = cake_complexity_prices.get(selected_complexity, 0.0)

    # 1. Calculate Real Cake Price
    # This calculation now happens as soon as a base price is available
    if base_price > 0:
        total_cake_price = base_price * real_cake_size
        st.markdown(f"**Real Cake Price:** AED {total_cake_price:.2f}")

    # 2. Calculate Dummy Cake Price
    if dummy_cake_size > 0:
        if base_price > 0:
            total_dummy_price = (base_price / 2) * dummy_cake_size
            st.markdown(f"**Dummy Cake Price:** AED {total_dummy_price:.2f}")
        else:
            st.info("Please select a cake complexity to calculate the dummy cake price.")
            
    # 3. Calculate Flavor Charge
    if add_flavor_charge:
        total_price_flavor = 21 * real_cake_size
        st.markdown(f"**Flavor Charge:** AED {total_price_flavor:.2f}")

    # 4. Calculate Toy Price
    toy_price_per_unit = toy_complexity_prices.get(selected_toy_complexity, 0.0)
    total_toy_price = toy_price_per_unit * toy_quantity
    st.markdown(f"**Toy Price:** AED {total_toy_price:.2f}")
    
    # Final Total Calculation based on the new formula
    total_price = total_cake_price + total_dummy_price + total_price_flavor + total_toy_price

    # Apply the 10% discount if selected
    discount_amount = 0
    if apply_discount:
        discount_amount = total_price * 0.10
        total_price -= discount_amount
        
    st.markdown(f"### Final Price: **AED {total_price:.2f}**")
    
    st.markdown("---")
    
    # Add a button to generate the report
    if st.button("Generate Report"):
        st.session_state.generate_report = True

    if st.session_state.generate_report:
        st.markdown("---")
        st.subheader("📋 Price Calculation Report")
        
        # Build the report string with markdown
        report_content = ""
        report_content += "#### Calculation Breakdown\n\n"
        
        report_content += f"- **Cake Base Price ({selected_complexity}):** AED {cake_complexity_prices.get(selected_complexity, 0.0):.2f}\n"
        report_content += f"- **Real Cake Cost ({real_cake_size:.1f} kg):** AED {total_cake_price:.2f}\n"
        if dummy_cake_size > 0:
            report_content += f"- **Dummy Cake Cost ({dummy_cake_size:.1f} kg):** AED {total_dummy_price:.2f}\n"
        if add_flavor_charge:
            report_content += f"- **Flavor Charge ({real_cake_size:.1f} kg):** AED {total_price_flavor:.2f}\n"
        if toy_quantity > 0:
            report_content += f"- **Toy Cost ({toy_quantity} x {selected_toy_complexity}):** AED {total_toy_price:.2f}\n"
        
        report_content += "\n***\n"
        
        if apply_discount:
            report_content += f"- **Total Before Discount:** AED {(total_price + discount_amount):.2f}\n"
            report_content += f"- **Discount Applied (10%):** - AED {discount_amount:.2f}\n"
        
        report_content += f"### Grand Total: **AED {total_price:.2f}**\n"
        
        st.markdown(report_content)
        st.info("To print or save this report, use your browser's print function (`Ctrl+P` or `Cmd+P`).")
        
    st.button("Reset Inputs", on_click=reset_price_calculator_inputs)
        
# This is the entry point for the Streamlit app.
if __name__ == "__main__":
    def main():
        pass
    
    # Running the main content of the app is handled by the `selected_page` logic above.
    # The `main` function is just a placeholder here.
    main()

# --- Footer ---
st.markdown("<div class='footer'>Katrina Knowledge base by Jude Sepe Jr</div>", unsafe_allow_html=True)
