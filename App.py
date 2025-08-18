import streamlit as st
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
import requests
import sqlite3
import os

# --- SQLite Database Setup ---
DB_FILE = "stores.db"

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
                store_status TEXT DEFAULT 'Operational',
                store_hours TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Using a safer approach for ALTER TABLE: check if column exists before adding
        columns_to_add = {
            "contact_number": "TEXT",
            "branch_supervisor": "TEXT",
            "store_status": "TEXT DEFAULT 'Operational'",
            "store_hours": "TEXT"
        }
        for col, col_type in columns_to_add.items():
            try:
                cursor.execute(f"ALTER TABLE stores ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    st.warning(f"Could not add column '{col}' (may already exist or another issue): {e}")
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
            name_lower = name.lower()
            address_lower = address.lower()

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
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            store_id_int = int(store_id)
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
    """Deletes a store from SQLite database by its ID."""
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

# Initialize Streamlit session state variables
if 'stores_df' not in st.session_state:
    st.session_state.stores_df = pd.DataFrame(columns=['id', 'name', 'address', 'latitude', 'longitude', 'contact_number', 'branch_supervisor', 'store_status', 'store_hours', 'timestamp'])
if 'editing_store_id' not in st.session_state:
    st.session_state.editing_store_id = None
if 'editing_store_details' not in st.session_state:
    st.session_state.editing_store_details = {}
# No delete_confirm_modal_active needed anymore as the modal is removed.
if 'store_id_to_confirm_delete' not in st.session_state:
    st.session_state.store_id_to_confirm_delete = None
if 'store_name_to_confirm_delete' not in st.session_state:
    st.session_state.store_name_to_confirm_delete = None

def fetch_stores_from_db_local():
    """Fetches all stores from SQLite and updates st.session_state.stores_df."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, address, latitude, longitude, contact_number, branch_supervisor, store_status, store_hours, timestamp FROM stores")
            rows = cursor.fetchall()
            cols = [description[0] for description in cursor.description]
            st.session_state.stores_df = pd.DataFrame(rows, columns=cols)
    except Exception as e:
        st.error(f"Error fetching stores from database: {e}")

# --- Streamlit App Layout ---
st.set_page_config(
    layout="wide",
    page_title="Katrina Knowledge Base Tools",
    page_icon="📍",
    initial_sidebar_state="collapsed"
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
    ["Find Nearest Store", "Add/Edit Store", "Delivery Fee", "Price Calculator"]
)

if selected_page == "Find Nearest Store":
    fetch_stores_from_db_local()
    st.markdown("---")
    st.markdown("<div class='input-section'>", unsafe_allow_html=True)
    st.markdown("<h3>Your Current Location</h3>", unsafe_allow_html=True)

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
            st.info("No locations to display on the map yet.")

        if user_lat is not None and user_lon is not None:
            user_location_df = pd.DataFrame([{
                'latitude': user_lat,
                'longitude': user_lon,
                'name': 'Your Location',
                'size': 200,
                'color': [255, 0, 0]
            }])

            stores_df_for_map = st.session_state.stores_df.copy()
            if not stores_df_for_map.empty and all(col in stores_df_for_map.columns for col in ['latitude', 'longitude']):
                stores_df_for_map['size'] = 50
                stores_df_for_map['color'] = [[0, 0, 255]] * len(stores_df_for_map)
            else:
                stores_df_for_map = pd.DataFrame(columns=['latitude', 'longitude', 'name', 'size', 'color'])


            map_data_stores = stores_df_for_map.dropna(subset=['latitude', 'longitude'])
            map_data = pd.concat([user_location_df, map_data_stores[['latitude', 'longitude', 'name', 'size', 'color']]])

            if not map_data.empty:
                st.map(map_data,
                    latitude='latitude',
                    longitude='longitude',
                    size='size',
                    color='color',
                    zoom=11)
            else:
                st.info("No locations to display on the map yet.")

elif selected_page == "Add/Edit Store":
    fetch_stores_from_db_local()
    st.markdown("---")
    mode = st.radio("Choose Mode", ["Add New Store", "Edit Existing Store"], key="add_edit_mode_selector")
    st.markdown("---")

    if mode == "Add New Store":
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Add New Store Location</h3>", unsafe_allow_html=True)

        with st.form("add_store_form", clear_on_submit=True):
            new_store_name = st.text_input("Store Name", key="add_name_form")
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
                            fetch_stores_from_db_local()
                    else:
                        st.error("Could not get coordinates for the new store. Please check the address and ensure your API key is correctly configured.")

        st.markdown("</div>", unsafe_allow_html=True)

    elif mode == "Edit Existing Store":
        st.markdown("<div class='input-section'>", unsafe_allow_html=True)
        st.markdown("<h3>Edit Existing Store Location</h3>", unsafe_allow_html=True)

        store_names = [""] + list(st.session_state.stores_df['name'].unique()) if not st.session_state.stores_df.empty else [""]
        selected_store_name_for_edit = st.selectbox(
            "Select Store to Edit",
            options=store_names,
            key="select_store_to_edit"
        )
        
        if selected_store_name_for_edit and selected_store_name_for_edit != "":
            selected_store_row_series = st.session_state.stores_df[
                st.session_state.stores_df['name'] == selected_store_name_for_edit
            ]
            if not selected_store_row_series.empty:
                selected_store_row = selected_store_row_series.iloc[0]
                st.session_state.editing_store_id = selected_store_row['id']
                st.session_state.editing_store_details = selected_store_row.to_dict()
            else:
                st.warning(f"Selected store '{selected_store_name_for_edit}' not found in current data. Please try again.")
                st.session_state.editing_store_id = None
                st.session_state.editing_store_details = {}
        else:
            st.session_state.editing_store_id = None
            st.session_state.editing_store_details = {}

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

            if st.button("Update Store Details", key="update_button", use_container_width=True):
                if st.session_state.editing_store_id is None:
                    st.warning("Please select a store to edit first.")
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
                st.info("Please select a store from the dropdown above to edit its details.")


        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    if mode == "Edit Existing Store":
        st.markdown("<h3>All Saved Stores</h3>", unsafe_allow_html=True)
        if not st.session_state.stores_df.empty:
            cols_config = st.columns([0.5, 2, 3, 1.5, 1.5, 1.2, 2, 0.8])

            with cols_config[0]: st.markdown("**ID**")
            with cols_config[1]: st.markdown("**Name**")
            with cols_config[2]: st.markdown("**Address**")
            with cols_config[3]: st.markdown("**Contact**")
            with cols_config[4]: st.markdown("**Supervisor**")
            with cols_config[5]: st.markdown("**Status**")
            with cols_config[6]: st.markdown("**Hours**")
            with cols_config[7]: st.markdown("**Actions**")

            st.markdown("---")

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
                    # Directly call delete function, removing the modal activation
                    if st.button("🗑️", key=f"delete_row_{store['id']}", help=f"Delete {store['name']}", type="secondary"):
                        if delete_store_from_db(store['id']):
                            fetch_stores_from_db_local()
                            st.rerun()

                st.markdown("---")
        else:
            st.info("No stores currently in the database. Add some using 'Add New Store' tab!")

elif selected_page == "Delivery Fee":
    st.markdown("---")
    st.markdown("<div class='input-section'>", unsafe_allow_html=True)
    st.markdown("<h3>Delivery Fee Information</h3>", unsafe_allow_html=True)
    st.write("Click the button below to visit our delivery fee information page.")

    delivery_fee_url = "https://katrina-delivery.streamlit.app/"
    st.link_button("Go to Delivery Fee Page", delivery_fee_url)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_page == "Price Calculator":
    st.markdown("---")
    st.markdown("<div class='input-section'>", unsafe_allow_html=True)
    st.markdown("<h3>Price Calculator</h3>", unsafe_allow_html=True)
    st.write("This section will allow you to calculate prices.")
    item_price = st.number_input("Enter Item Price", min_value=0.0, format="%.2f", key="item_price_input")
    quantity = st.number_input("Enter Quantity", min_value=1, step=1, key="quantity_input")

    if st.button("Calculate Total Price", key="calculate_price_btn"):
        total_price = item_price * quantity
        st.success(f"The total price is: ${total_price:.2f}")

    st.markdown("</div>", unsafe_allow_html=True)

# --- Footer Section ---
st.markdown("<div class='footer'>", unsafe_allow_html=True)
st.markdown("Katrina Bakery LLC 2025 by Judy Sepe", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# Removed the entire conditional modal display block
