# streamlit_app.py
"""
SurveilAI — Upgraded app
Features added:
- Simple login (username/password)
- Auto-generated unique case IDs (UUID)
- Date of entry and selectable onset/reporting dates
- Region / District / Town / Landmark / Role
- "Get current location (experimental)" HTML widget to capture browser coords
- Spatial lookup of district/region if shapefile provided
- Epi-week counts and "cases this epi week" metric
- Summary reports: totals, by sex, age group, district, classification
- Epi curve and charts
- Logo at top of sidebar
"""
import streamlit as st
import pandas as pd
import numpy as np
import geopandas as gpd
import uuid
import zipfile, io, os
from shapely.geometry import Point
from datetime import datetime, date
from sklearn.cluster import DBSCAN
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import plotly.express as px

import streamlit as st
import json, os
from datetime import datetime

# =======================
# 🔐 SIMPLE AUTH SYSTEM
# =======================
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

def register_user():
    st.subheader("Create an Account")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    role = st.selectbox("Role", ["Health Worker", "Admin"])

    if st.button("Register"):
        users = load_users()
        if username in users:
            st.error("Username already exists!")
        else:
            users[username] = {"password": password, "role": role, "created": str(datetime.now())}
            save_users(users)
            st.success("✅ Account created! You can now log in.")

def login_user():
    st.subheader("Login")
    username = st.text_input("Username", key="login_user")
    password = st.text_input("Password", type="password", key="login_pass")
    if st.button("Login"):
        users = load_users()
        if username in users and users[username]["password"] == password:
            st.session_state["auth"] = True
            st.session_state["user"] = username
            st.session_state["role"] = users[username]["role"]
            st.success(f"✅ Welcome {username}!")
        else:
            st.error("Invalid username or password")

def logout_user():
    st.session_state.clear()
    st.experimental_rerun()

# -------------------------
# Configuration / Simple Auth
# -------------------------
st.set_page_config(layout="wide", page_title="SurveilAI — Epi Dashboard")

# === Simple credentials (for prototyping only) ===
# Replace or connect to a proper user store for production (database + password hashing).
CREDENTIALS = {
    "surveil_admin": "ChangeMe123",   # change this
    "worker1": "password1"            # example secondary user
}

def login_widget():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None

    if st.session_state.logged_in:
        st.sidebar.success(f"Logged in as: {st.session_state.username}")
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.experimental_rerun()
        return True

    st.sidebar.header("")  # spacing
    st.sidebar.image("lima.jpg", width=150)  # logo (put lima.jpg in app folder)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Login")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Sign in"):
        if username in CREDENTIALS and CREDENTIALS[username] == password:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.sidebar.success(f"Welcome, {username}")
            return True
        else:
            st.sidebar.error("Invalid credentials")
            return False
    return False

if not login_widget():
    st.stop()

# -------------------------
# Helper functions
# -------------------------
def load_shapefile_from_zip(uploaded_zip_bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(uploaded_zip_bytes)) as z:
            extract_dir = "./temp_shapefile"
            if os.path.exists(extract_dir):
                for f in os.listdir(extract_dir):
                    try:
                        os.remove(os.path.join(extract_dir, f))
                    except Exception:
                        pass
            else:
                os.makedirs(extract_dir, exist_ok=True)
            z.extractall(extract_dir)
            shp_files = [f for f in os.listdir(extract_dir) if f.lower().endswith('.shp')]
            if not shp_files:
                st.error("No .shp file found in ZIP.")
                return None
            shp_path = os.path.join(extract_dir, shp_files[0])
            gdf = gpd.read_file(shp_path)
            return gdf
    except Exception as e:
        st.error(f"Failed to read shapefile zip: {e}")
        return None

def compute_risk_score(row):
    score = 0
    weights = {
        'fever': 20, 'cough': 10, 'vomiting': 10, 'diarrhea': 10,
        'rash': 15, 'difficulty_breathing': 20
    }
    for s, w in weights.items():
        if row.get(s):
            score += w
    if row.get('contact_with_case'):
        score += 15
    if row.get('travel_recent'):
        score += 10
    if row.get('lab_positive'):
        score = 100
    score = min(100, score)
    if row.get('lab_positive'):
        category = 'confirmed'
    elif score >= 60:
        category = 'probable'
    elif score >= 20:
        category = 'suspected'
    else:
        category = 'unlikely'
    return score, category

def cluster_cases(df_coords, eps_m=500, min_samples=3):
    if df_coords.shape[0] < 2:
        return pd.Series([-1]*len(df_coords), index=df_coords.index)
    g = gpd.GeoDataFrame(df_coords.copy(), geometry=gpd.points_from_xy(df_coords.longitude, df_coords.latitude)).set_crs(epsg=4326)
    try:
        g = g.to_crs(epsg=32630)
    except Exception:
        try:
            g = g.to_crs(g.estimate_utm_crs())
        except Exception:
            return pd.Series([-1]*len(df_coords), index=df_coords.index)
    coords = np.vstack([g.geometry.x, g.geometry.y]).T
    db = DBSCAN(eps=eps_m, min_samples=min_samples, metric='euclidean')
    labels = db.fit_predict(coords)
    return pd.Series(labels, index=df_coords.index)

def plot_map_with_cases(gdf_cases, base_gdf=None):
    if gdf_cases.empty:
        m = folium.Map(location=[7.9465, -1.0232], zoom_start=6)
        if base_gdf is not None:
            folium.GeoJson(base_gdf.to_json(), name='districts').add_to(m)
        return m
    mid_lat = gdf_cases.geometry.y.mean()
    mid_lon = gdf_cases.geometry.x.mean()
    m = folium.Map(location=[mid_lat, mid_lon], zoom_start=10)
    if base_gdf is not None:
        folium.GeoJson(base_gdf.to_json(), name='districts',
                       style_function=lambda x: {'fillColor': 'none','color':'#444','weight':1}).add_to(m)
    heat_data = [[pt.y, pt.x] for pt in gdf_cases.geometry]
    if len(heat_data) > 0:
        HeatMap(heat_data, radius=15).add_to(m)
    for _, r in gdf_cases.iterrows():
        popup_html = f"<b>{r.get('case_id','case')}</b><br>category: {r.get('category')}<br>score: {r.get('score')}"
        folium.CircleMarker(location=[r.geometry.y, r.geometry.x], radius=5,
                            popup=folium.Popup(popup_html, max_width=250)).add_to(m)
    return m

def auto_assign_admin_fields_from_coords(lat, lon, shapefile_gdf):
    """Return (region, district) if shapefile available and coordinates given."""
    if shapefile_gdf is None or lat is None or lon is None:
        return None, None
    try:
        pt = gpd.GeoDataFrame([[1]], geometry=gpd.points_from_xy([lon], [lat]), crs="EPSG:4326")
        shp = shapefile_gdf.to_crs("EPSG:4326")
        join = gpd.sjoin(pt, shp, predicate="within", how="left")
        if not join.empty:
            # heuristic: look for common district/region fields
            for col in ['NAME_2', 'district', 'District', 'DISTRICT', 'NAME_1', 'region', 'Region']:
                if col in join.columns:
                    val = join.iloc[0].get(col)
                    if pd.notna(val):
                        # try to map district vs region
                        # return district and region heuristically
                        return (join.iloc[0].get('NAME_1') if 'NAME_1' in join.columns else None,
                                join.iloc[0].get('NAME_2') if 'NAME_2' in join.columns else val)
        return None, None
    except Exception:
        return None, None

# -------------------------
# Sidebar - branding and uploads
# -------------------------
st.sidebar.title("SurveilAI")
st.sidebar.markdown("**Smarter Surveillance, faster response.**")
st.sidebar.markdown("---")
st.sidebar.markdown("### Created by Lima 2 Group")

# ==========================
# 🛡 AUTH GATE
# ==========================
if "auth" not in st.session_state:
    choice = st.radio("Select", ["Login", "Register"])
    if choice == "Login":
        login_user()
    else:
        register_user()

else:
    st.sidebar.success(f"Logged in as: {st.session_state['user']} ({st.session_state['role']})")
    if st.sidebar.button("Logout"):
        logout_user()

    # ==========================
    # 📊 YOUR DASHBOARD CONTENT
    # ==========================
    st.title("SMCintel Dashboard")
    # <-- keep all your charts/maps/tables below this
shapefile_zip = st.sidebar.file_uploader("Upload Ghana shapefile ZIP (optional)", type=['zip'])
if shapefile_zip is not None:
    shapefile_gdf = load_shapefile_from_zip(shapefile_zip.read())
    if shapefile_gdf is not None:
        st.sidebar.success(f"Loaded shapefile ({len(shapefile_gdf)} features).")
else:
    shapefile_gdf = None

st.sidebar.markdown("---")
st.sidebar.header("Settings")
alert_threshold = st.sidebar.number_input("Alert threshold (7-day cases)", min_value=1, value=20)
cluster_eps_m = st.sidebar.number_input("Cluster radius (meters)", min_value=50, max_value=5000, value=500, step=50)
min_cluster_samples = st.sidebar.number_input("Min samples for cluster", min_value=2, value=3)

# -------------------------
# Session store
# -------------------------
if 'cases' not in st.session_state:
    st.session_state['cases'] = []

# -------------------------
# Main UI - case entry
# -------------------------
st.header("Enter a new case")

with st.form("case_entry"):
    # auto id and entry date
    generated_case_id = str(uuid.uuid4())[:8]  # short uuid
    st.write(f"**Case ID:** {generated_case_id}")

    name = st.text_input("Name (optional)")
    age = st.number_input("Age", min_value=0, max_value=120, value=25)
    sex = st.selectbox("Sex", options=["male", "female", "other"])
    # onset and reporting dates
    onset_date = st.date_input("Date of onset", value=date.today())
    reporting_date = st.date_input("Reporting date (date of entry)", value=date.today())
    # symptoms
    st.write("Symptoms")
    fever = st.checkbox("Fever")
    cough = st.checkbox("Cough")
    vomiting = st.checkbox("Vomiting")
    diarrhea = st.checkbox("Diarrhea")
    rash = st.checkbox("Rash")
    difficulty_breathing = st.checkbox("Difficulty breathing")
    contact_with_case = st.checkbox("Contact with known case")
    travel_recent = st.checkbox("Recent travel to high-risk area")
    lab_positive = st.checkbox("Lab-confirmed (positive)")

    # location inputs + auto-detect
    st.write("Location")
    colA, colB = st.columns([2,1])
    with colA:
        latitude = st.number_input("Latitude (decimal)", format="%.6f", value=0.0)
        longitude = st.number_input("Longitude (decimal)", format="%.6f", value=0.0)
    with colB:
        st.write("Geolocation")
        # Experimental auto-detect: show a small HTML widget that attempts to get coords and displays them for user to copy-paste
        if st.button("Get current location (experimental)"):
            st.info("A browser window widget will try to read your device location and show coordinates. Copy them into the Latitude/Longitude fields if allowed by browser.")
            geoloc_html = """
            <div id="status">Click 'Allow' if your browser asks for location permission.</div>
            <button onclick="getLocation()">Get location</button>
            <pre id="out"></pre>
            <script>
            function getLocation() {
                const out = document.getElementById('out');
                if (!navigator.geolocation) {
                    out.textContent = 'Geolocation not supported';
                    return;
                }
                navigator.geolocation.getCurrentPosition(function(pos) {
                    const lat = pos.coords.latitude;
                    const lon = pos.coords.longitude;
                    out.textContent = 'Latitude: ' + lat + '\\nLongitude: ' + lon + '\\n\\nCopy these values into the app form fields.';
                }, function(err){
                    out.textContent = 'ERROR: ' + err.message;
                });
            }
            </script>
            """
            st.components.v1.html(geoloc_html, height=200)
        st.write("Or paste coords above")

    # admin fields
    st.write("Administrative / reporting details")
    region_select = st.text_input("Region (optional)")
    district_select = st.text_input("District (optional)")
    town = st.text_input("Town / Community")
    landmark = st.text_input("Landmark (optional)")
    role = st.selectbox("Reporter role", options=["Frontline worker", "Community volunteer", "Other"])
    frontline_worker_name = st.text_input("Frontline worker / reporter name (optional)")

    submit = st.form_submit_button("Submit case")

if submit:
    # Replace 0.0 sentinel with None
    lat_val = None if float(latitude) == 0.0 else float(latitude)
    lon_val = None if float(longitude) == 0.0 else float(longitude)

    # If shapefile provided, try to auto-fill region/district
    if shapefile_gdf is not None and (lat_val is not None and lon_val is not None):
        auto_region, auto_district = auto_assign_admin_fields_from_coords(lat_val, lon_val, shapefile_gdf)
        if auto_region and not region_select:
            region_select = auto_region
        if auto_district and not district_select:
            district_select = auto_district

    record = {
        "case_id": generated_case_id,
        "name": name,
        "age": int(age),
        "age_group": f"{(int(age)//10)*10}-{(int(age)//10)*10+9}",
        "sex": sex,
        "onset_date": str(onset_date),
        "reporting_date": str(reporting_date),
        "date_of_entry": datetime.utcnow().isoformat(),
        "fever": fever,
        "cough": cough,
        "vomiting": vomiting,
        "diarrhea": diarrhea,
        "rash": rash,
        "difficulty_breathing": difficulty_breathing,
        "contact_with_case": contact_with_case,
        "travel_recent": travel_recent,
        "lab_positive": lab_positive,
        "latitude": lat_val,
        "longitude": lon_val,
        "region": region_select,
        "district": district_select,
        "town": town,
        "landmark": landmark,
        "role": role,
        "reporter_name": frontline_worker_name,
        "submitted_by": st.session_state.username
    }
    score, category = compute_risk_score(record)
    record["score"] = score
    record["category"] = category
    # epi week (ISO week) derived from onset_date
    try:
        onset_dt = pd.to_datetime(record["onset_date"]).date()
        record["epi_year"], record["epi_week"], _ = onset_dt.isocalendar()
    except Exception:
        record["epi_year"], record["epi_week"] = None, None

    st.session_state.cases.append(record)
    st.success(f"Saved case {record['case_id']} — classification: {category} (score {score})")

# -------------------------
# Dataframe & analytics
# -------------------------
cases_df = pd.DataFrame(st.session_state.get("cases", []))

# Epi-week metric
st.header("Dashboard & Analytics")
if not cases_df.empty:
    # parse dates
    cases_df['onset_date'] = pd.to_datetime(cases_df['onset_date'], errors='coerce')
    cases_df['epi_week'] = cases_df.apply(lambda r: (r['epi_year'], r['epi_week']) if pd.notna(r.get('epi_week')) else (None, None), axis=1)
    # compute current ISO week
    today = date.today()
    yi, wi, _ = today.isocalendar()
    # count cases with same epi year/week
    def same_epi_week(row):
        try:
            return int(row.get('epi_year')) == yi and int(row.get('epi_week')) == wi
        except Exception:
            return False
    cases_this_week = cases_df[cases_df.apply(same_epi_week, axis=1)]
    st.metric("Cases this epi week", len(cases_this_week))

    # Summary stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Totals")
        st.write(f"Total cases: {len(cases_df)}")
        st.write(f"Suspected: {len(cases_df[cases_df['category']=='suspected'])}")
        st.write(f"Probable: {len(cases_df[cases_df['category']=='probable'])}")
        st.write(f"Confirmed: {len(cases_df[cases_df['category']=='confirmed'])}")
    with col2:
        st.subheader("By sex")
        sex_counts = cases_df['sex'].value_counts().reset_index()
        sex_counts.columns = ['sex','n']
        st.dataframe(sex_counts)
        fig_sex = px.pie(sex_counts, names='sex', values='n', title='Cases by sex')
        st.plotly_chart(fig_sex, use_container_width=True)
    with col3:
        st.subheader("By age group")
        ag = cases_df['age_group'].value_counts().reset_index()
        ag.columns = ['age_group','n']
        st.dataframe(ag)
        fig_age = px.bar(ag, x='age_group', y='n', title='Cases by age group')
        st.plotly_chart(fig_age, use_container_width=True)

    # By district
    st.subheader("By district")
    distr = cases_df['district'].fillna('unspecified').value_counts().reset_index()
    distr.columns = ['district','n']
    st.dataframe(distr)
    fig_d = px.bar(distr, x='district', y='n', title='Cases by district')
    st.plotly_chart(fig_d, use_container_width=True)

    # Epi curve
    st.subheader("Epi curve (by onset date)")
    epi = cases_df.dropna(subset=['onset_date']).groupby(cases_df['onset_date'].dt.date).size().reset_index(name='count')
    if not epi.empty:
        fig = px.area(epi, x='onset_date', y='count', title='Epi curve')
        st.plotly_chart(fig, use_container_width=True)

    # Line list
    st.subheader("Case line list (latest 200)")
    display_cols = ['case_id','name','age','sex','age_group','onset_date','reporting_date','date_of_entry',
                    'region','district','town','landmark','role','submitted_by','category','score','latitude','longitude']
    st.dataframe(cases_df[display_cols].sort_values('date_of_entry', ascending=False).head(200))
else:
    st.info("No cases yet. Use the form above or upload CSV.")

# -------------------------
# Mapping & clusters
# -------------------------
st.subheader("Map & Clusters")
if not cases_df.empty:
    # prepare gdf
    cases_map = cases_df.dropna(subset=['latitude','longitude']).copy()
    if not cases_map.empty:
        gdf_cases = gpd.GeoDataFrame(cases_map, geometry=gpd.points_from_xy(cases_map.longitude, cases_map.latitude)).set_crs(epsg=4326)
        folium_map = plot_map_with_cases(gdf_cases, base_gdf=shapefile_gdf)
        st_data = st_folium(folium_map, width=900, height=500)
        # clusters
        coords_df = pd.DataFrame({'latitude': gdf_cases.geometry.y, 'longitude': gdf_cases.geometry.x})
        labels = cluster_cases(coords_df, eps_m=cluster_eps_m, min_samples=int(min_cluster_samples))
        gdf_cases['cluster'] = labels
        st.write("Cluster assignments (sample)")
        st.dataframe(gdf_cases[['case_id','onset_date','category','score','cluster']].head(50))
    else:
        st.info("No geolocated cases to show on map.")
else:
    st.info("No data for map.")

# -------------------------
# Upload/Export
# -------------------------
st.sidebar.header("Upload / Export")
csv_upload = st.sidebar.file_uploader("Upload case CSV (optional)", type=['csv'])
if csv_upload is not None:
    try:
        uploaded_df = pd.read_csv(csv_upload)
        # append with simple harmonization
        st.session_state.cases = st.session_state.get('cases', []) + uploaded_df.to_dict(orient='records')
        st.sidebar.success(f"Uploaded {len(uploaded_df)} rows")
        st.experimental_rerun()
    except Exception as e:
        st.sidebar.error(f"Failed to read CSV: {e}")

if st.sidebar.button("Download cases CSV"):
    if not cases_df.empty:
        st.sidebar.download_button("Download CSV", data=cases_df.to_csv(index=False).encode('utf-8'),
                                   file_name='cases_export.csv', mime='text/csv')
    else:
        st.sidebar.info("No data to export")

if st.sidebar.button("Save session to JSON"):
    if not cases_df.empty:
        out_path = "cases_export.json"
        cases_df.to_json(out_path, orient='records', date_format='iso')
        st.sidebar.success(f"Saved to {out_path}")
    else:
        st.sidebar.info("No data to save")

