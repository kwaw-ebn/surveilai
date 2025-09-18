
import streamlit as st
from utils import init_db, get_user, create_user, check_password, add_case, query_summary, load_shapefile_from_zip, cluster_epicenters, assign_district_from_point, get_all_users, set_user_role
import sqlite3
import uuid
import pandas as pd
import geopandas as gpd
from datetime import datetime
import folium
from streamlit_folium import st_folium
import base64
import yaml
import os

st.set_page_config(page_title="Surveilai", layout="wide", initial_sidebar_state="expanded")

# --- INIT ---
init_db()
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

# --- SIDEBAR ---
# allow user to upload official logo; if not uploaded we use assets/lima.jpg
st.sidebar.title("Surveilai")
logo_upload = st.sidebar.file_uploader("Upload official logo (lima.jpg)", type=['jpg','jpeg','png'])
if logo_upload:
    with open("assets/lima.jpg","wb") as out:
        out.write(logo_upload.read())
try:
    st.sidebar.image("assets/lima.jpg", width=120)
except:
    st.sidebar.write("LIMA Group")

st.sidebar.markdown("Created by LIMA Group")

# Auth UI
auth_mode = st.sidebar.radio("Auth", ["Login", "Sign up"])
if auth_mode == "Sign up":
    st.sidebar.subheader("Create account")
    new_user = st.sidebar.text_input("Username")
    new_pass = st.sidebar.text_input("Password", type="password")
    display_name = st.sidebar.text_input("Full name")
    role_choice = st.sidebar.selectbox("Role", ["user","investigator","admin"])
    if st.sidebar.button("Create account"):
        ok, msg = create_user(new_user, new_pass, display_name, role_choice)
        st.sidebar.success(msg if ok else f"Error: {msg}")

st.sidebar.markdown("---")

st.sidebar.markdown("---")
if st.sidebar.button("About Surveilai"):
    st.session_state["page"] = "about"

username = st.sidebar.text_input("Username")
password = st.sidebar.text_input("Password", type="password")
if st.sidebar.button("Login"):
    user = get_user(username)
    if user and check_password(password, user["password"]):
        st.session_state["user"] = {"username": username, "name": user["name"], "role": user.get("role","user")}
        st.sidebar.success(f"Welcome {user['name']} ({user.get('role','user')})")
    else:
        st.sidebar.error("Invalid credentials")

if "user" not in st.session_state:
    st.info("Please login or sign up to use the app.")
    st.stop()

if st.session_state.get("page") == "about":
    st.header("About Surveilai")
    st.markdown("""
    **Surveilai** — an outbreak surveillance MVP built for rapid situational awareness.

    **Purpose & Outcomes**
    - AI-powered outbreak risk scores (district-level), updated weekly.
    - Interactive dashboard: heatmaps, epi curves, time-series forecasts.
    - Automated alerts for high-risk areas and hotspot detection.
    - Faster detection, better preparedness, and reduced outbreak burden.

    **MVP features**
    - Case capture (suspected/probable/confirmed) with auto geocoding and district assignment.
    - Upload shapefiles for polygon mapping.
    - Admin UI for user & notification management.
    - Scoring scaffold and GitHub Actions for weekly scoring jobs.

    **Created by** Lima Group
    """)
    st.stop()

# Admin menu
if st.session_state["user"]["role"] == "admin":
    st.sidebar.markdown("## Admin")
    if st.sidebar.button("User management"):
        st.session_state["admin_page"] = "users"
    if st.sidebar.button("Alerts & thresholds"):
        st.session_state["admin_page"] = "alerts"

# --- MAIN APP ---

    # --- Disease Selection ---
    st.sidebar.subheader("Case Definition Settings")
    disease_options = list(config.get("case_definitions", {}).keys())
    if disease_options:
        selected_disease = st.sidebar.selectbox("Select active disease", disease_options)
        st.session_state["active_disease"] = selected_disease
    else:
        selected_disease = None
    
st.header("Surveilai — District outbreak risk & case reporting")

col1, col2 = st.columns([1,1])

with col1:
    st.subheader("Report a case")
    with st.form("case_form", clear_on_submit=True):
        name = st.text_input("Patient name (optional)")
        sex = st.selectbox("Sex", ["Unknown","Male","Female","Other"])
        age = st.number_input("Age", min_value=0, max_value=120, value=0)
        reporter = st.selectbox("Reporter", ["Frontline worker", "Community volunteer", "Citizen"])
        region = st.text_input("Region (optional)")
        district = st.text_input("District (optional)")
        community = st.text_input("Community (optional)")
        onset_date = st.date_input("Onset / report date", value=datetime.today())
        lab_positive = st.checkbox("Lab-confirmed positive")
        fever = st.checkbox("Fever")
        cough = st.checkbox("Cough")
        rash = st.checkbox("Rash")
        other_symptoms = st.text_area("Other symptoms (comma-separated)")
        use_coords = st.radio("Location input", ["Manual", "Auto-detect (ask browser)"])
        coords = None
        if use_coords == "Auto-detect (ask browser)":
            st.write("Click the button below and paste coordinates if auto-detect is not available.")
            coords_btn = st.button("Get my current coordinates")
            coords_text = st.text_input("Paste coordinates as lat,lon (e.g. -1.234,36.78)")
            if coords_text:
                try:
                    lat, lon = coords_text.split(",")
                    coords = (float(lat.strip()), float(lon.strip()))
                except:
                    st.warning("Invalid coords format.")
        else:
            coords_text = st.text_input("Coordinates (lat,lon) optional")

        submit = st.form_submit_button("Submit case")
        if submit:
            case_id = str(uuid.uuid4())[:8]
            # classification using config rules (simple)
            classification = "Suspected"
            rules = config.get('classification_rules', {})
            if rules.get('confirmed', {}).get('lab_positive') and lab_positive:
                classification = "Confirmed"
            else:
                prob_rule = rules.get('probable', {})
                required = prob_rule.get('symptoms_required', [])
                symptoms_list = [s.strip().lower() for s in (other_symptoms.split(",") if other_symptoms else [])]
                if fever and cough:
                    classification = "Probable"
                elif any(r in symptoms_list for r in required):
                    classification = "Probable"
            entry = dict(
                case_id=case_id,
                name=name,
                sex=sex,
                age=int(age),
                reporter=reporter,
                region=region,
                district=district,
                community=community,
                onset_date=str(onset_date),
                lab_positive=int(lab_positive),
                symptoms=";".join([s for s in ["fever" if fever else "", "cough" if cough else "", "rash" if rash else "", other_symptoms] if s]),
                classification=classification,
                coords=coords_text if not coords else f"{coords[0]},{coords[1]}"
            )
            # if shapefile loaded in session, assign district automatically
            if "shapefile_gdf" in st.session_state and entry.get('coords'):
                try:
                    latlon = entry['coords'].split(",")
                    lat = float(latlon[0].strip())
                    lon = float(latlon[1].strip())
                    assign = assign_district_from_point(lat, lon, st.session_state['shapefile_gdf'])
                    if assign.get('district'):
                        entry['district'] = assign.get('district')
                    if assign.get('region'):
                        entry['region'] = assign.get('region')
                    if assign.get('community'):
                        entry['community'] = assign.get('community')
                except Exception as e:
                    st.warning(f"Auto assign failed: {e}")
            add_case(entry)
            st.success(f"Case {case_id} saved as {classification}")

with col2:
    st.subheader("Uploads & shapefile")
    st.markdown("Upload a zipped shapefile (.zip) with region/district polygons to enable district detection and choropleth maps.")
    shp_zip = st.file_uploader("Upload shapefile .zip", type=["zip"])
    if shp_zip:
        try:
            gdf = load_shapefile_from_zip(shp_zip)
            st.session_state['shapefile_gdf'] = gdf
            st.success("Shapefile read successfully. Sample polygons: ")
            st.write(gdf.head())
        except Exception as e:
            st.error(f"Failed to read shapefile: {e}")

    st.subheader("Analytics & dashboard")
    df = query_summary()
    st.metric("Total cases", len(df))
    st.write("Cases by classification")
    st.write(df['classification'].value_counts().to_frame())

    st.subheader("Epi curve")
    if not df.empty:
        df['onset_date'] = pd.to_datetime(df['onset_date'])
        epi = df.groupby(df['onset_date'].dt.date).size().reset_index(name='cases')
        st.line_chart(epi.rename(columns={'onset_date':'index'}).set_index('index'))

    st.subheader("Map - case points & clusters")
    map_df = df.dropna(subset=['coords']).copy()
    if not map_df.empty:
        coords = map_df['coords'].str.split(",", expand=True).astype(float)
        map_df['lat'] = coords[0]
        map_df['lon'] = coords[1]
        m = folium.Map(location=[map_df['lat'].mean(), map_df['lon'].mean()], zoom_start=6)
        for _, r in map_df.iterrows():
            folium.CircleMarker(location=[r['lat'], r['lon']], radius=4, popup=r['case_id']).add_to(m)
        # clusters with time window if config set
        tw = config.get('alerts', {}).get('cluster_time_window_days', None)
        clusters = cluster_epicenters(map_df[['lat','lon','onset_date']], eps_meters=2000, min_samples=3, time_window_days=tw)
        for c in clusters:
            folium.Circle(location=[c['lat'], c['lon']], radius=2000, color='red', fill=False).add_to(m)
        st_folium(m, width=700, height=450)
    else:
        st.info("No geocoded case points to show. Add cases with coordinates.")

    st.subheader("Alerts")
    # use thresholds from config
    recent_days = config.get('alerts', {}).get('recent_days', 7)
    high_threshold = config.get('alerts', {}).get('high_activity_threshold', 10)
    last7 = df[df.get('onset_date', pd.Timestamp.now()) >= (pd.Timestamp.now() - pd.Timedelta(days=recent_days))] if not df.empty else pd.DataFrame()
    if len(last7) > high_threshold:
        st.error(f"High activity: {len(last7)} cases in last {recent_days} days")
    elif len(last7) > 0:
        st.warning(f"{len(last7)} cases in last {recent_days} days")

# Admin pages
if st.session_state["user"]["role"] == "admin" and st.session_state.get("admin_page") == "users":
    st.header("User management (admin)")
    users_df = get_all_users()
    st.table(users_df)
    st.subheader("Change user role")
    uname = st.text_input("Username to change role")
    newrole = st.selectbox("New role", ["user","investigator","admin"])
    if st.button("Set role"):
        set_user_role(uname, newrole)
        st.success("Role updated. Refresh to see changes.")

if st.session_state["user"]["role"] == "admin" and st.session_state.get("admin_page") == "alerts":

    st.header("Alerts & thresholds / Config editor")
    st.write("Edit `config.yaml` below and click Save to persist.")
    cfg_text = open(CONFIG_PATH).read()
    edited = st.text_area("config.yaml", value=cfg_text, height=300)
    if st.button("Save config.yaml"):
        try:
            with open(CONFIG_PATH, "w") as f:
                f.write(edited)
            st.success("Saved config.yaml. Reloading...")
            st.experimental_rerun()
        except Exception as e:
            st.error(f"Failed to save: {e}")

    if st.button("Reload config"):
        st.experimental_rerun()

st.sidebar.markdown("---")
st.sidebar.write("Export & admin")
if st.sidebar.button("Download CSV of cases"):
    df = query_summary()
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="cases.csv">Download cases.csv</a>'
    st.sidebar.markdown(href, unsafe_allow_html=True)
