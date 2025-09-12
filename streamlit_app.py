# streamlit_app.py
# SurveilAI — with email alerts, shapefile/geojson support, signup/login, geolocation, reports

import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import plotly.express as px
import geopandas as gpd
import os
import random, string, bcrypt, json
from datetime import datetime, date, timedelta
from sklearn.cluster import DBSCAN
from folium.plugins import HeatMap
import streamlit_authenticator as stauth
import smtplib
from email.message import EmailMessage

st.set_page_config(layout="wide", page_title="SurveilAI — Epi Dashboard")

# ---------------------------
# Files & simple ensures
# ---------------------------
USERS_FILE = "users.csv"
DATA_FILE = "cases.csv"
GEOJSON_FILE = "districts.geojson"  # optional pre-converted geojson

if not os.path.exists(USERS_FILE):
    pd.DataFrame(columns=["username","name","password"]).to_csv(USERS_FILE, index=False)

if not os.path.exists(DATA_FILE):
    cols = ["case_id","name","age","age_group","sex","onset_date","reporting_date","date_of_entry",
            "fever","cough","vomiting","diarrhea","rash","difficulty_breathing","bleeding",
            "contact_with_case","travel_recent","lab_positive",
            "latitude","longitude","region","district","community","town","landmark","role","reporter_name",
            "score","category","epi_year","epi_week"]
    pd.DataFrame(columns=cols).to_csv(DATA_FILE, index=False)

# ---------------------------
# User helpers
# ---------------------------
def load_users_df():
    return pd.read_csv(USERS_FILE) if os.path.exists(USERS_FILE) else pd.DataFrame(columns=["username","name","password"])

def save_user(username, plain_password, name):
    users = load_users_df()
    if username in users['username'].values:
        st.error("Username already exists")
        return False
    hashed = bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()
    new = pd.DataFrame([[username, name, hashed]], columns=["username","name","password"])
    users = pd.concat([users, new], ignore_index=True)
    users.to_csv(USERS_FILE, index=False)
    st.success("Account created — you can now log in")
    return True

def build_credentials():
    users = load_users_df()
    credentials = {"usernames": {}}
    for _, r in users.iterrows():
        credentials["usernames"][r['username']] = {"name": r['name'], "password": r['password']}
    return credentials

# ---------------------------
# Auth init
# ---------------------------
COOKIE_KEY = st.secrets.get("cookie_key", "dev_cookie_key_for_demo_replace_this")
authenticator = stauth.Authenticate(build_credentials(),
                                    "SurveilAI_Cookie",
                                    COOKIE_KEY,
                                    cookie_expiry_days=30)

# ---------------------------
# Risk scoring and classification
# ---------------------------
def compute_risk_and_category(record):
    score = 0
    weights = {
        'fever': 25,
        'cough': 10,
        'vomiting': 5,
        'diarrhea': 5,
        'rash': 10,
        'difficulty_breathing': 30,
        'bleeding': 40
    }
    for k,w in weights.items():
        if record.get(k):
            score += w
    if record.get('contact_with_case'):
        score += 15
    if record.get('travel_recent'):
        score += 10
    if record.get('lab_positive'):
        return 100, 'confirmed'
    score = min(100, score)
    if score >= 70:
        cat = 'probable'
    elif score >= 25:
        cat = 'suspected'
    else:
        cat = 'unlikely'
    return score, cat

# ---------------------------
# Shapefile / GeoJSON loaders & point-in-polygon
# ---------------------------
def load_shapefile_from_zipobj(zip_bytes, extract_dir="./temp_shp"):
    import zipfile, io, shutil
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        z.extractall(extract_dir)
    shp_files = [os.path.join(extract_dir,f) for f in os.listdir(extract_dir) if f.lower().endswith('.shp')]
    if not shp_files:
        return None
    gdf = gpd.read_file(shp_files[0])
    return gdf

def load_geojson_if_present(path=GEOJSON_FILE):
    if os.path.exists(path):
        try:
            return gpd.read_file(path)
        except Exception:
            return None
    return None

def point_to_admin(lat, lon, gdf):
    if gdf is None or lat is None or lon is None:
        return None, None, None
    try:
        pt = gpd.GeoDataFrame(geometry=gpd.points_from_xy([lon],[lat]), crs="EPSG:4326")
        shp = gdf.to_crs("EPSG:4326")
        join = gpd.sjoin(pt, shp, how="left", predicate="within")
        if join.empty:
            return None, None, None
        row = join.iloc[0]
        region = None; district = None; community = None
        for c in ['region','Region','NAME_1','NAME_0','NAME1','ADM1_NAME']:
            if c in row.index and pd.notna(row[c]):
                region = row[c]; break
        for c in ['district','District','NAME_2','ADM2_NAME','NAME2']:
            if c in row.index and pd.notna(row[c]):
                district = row[c]; break
        for c in ['community','COMMUNITY','NAME_3','ADM3_NAME','NAME3']:
            if c in row.index and pd.notna(row[c]):
                community = row[c]; break
        return region, district, community
    except Exception:
        return None, None, None

# ---------------------------
# Data store helpers
# ---------------------------
def load_cases_df():
    return pd.read_csv(DATA_FILE)

def save_case(record: dict):
    df = load_cases_df()
    df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

# ---------------------------
# Clustering & district risk
# ---------------------------
def cluster_cases(df_coords, eps_m=500, min_samples=3):
    if df_coords.shape[0] < 2:
        return np.array([-1]*df_coords.shape[0])
    g = gpd.GeoDataFrame(df_coords.copy(), geometry=gpd.points_from_xy(df_coords.longitude, df_coords.latitude)).set_crs(epsg=4326)
    try:
        g = g.to_crs(epsg=32630)
    except Exception:
        try:
            g = g.to_crs(g.estimate_utm_crs())
        except Exception:
            return np.array([-1]*df_coords.shape[0])
    coords = np.vstack([g.geometry.x, g.geometry.y]).T
    db = DBSCAN(eps=eps_m, min_samples=min_samples, metric='euclidean')
    labels = db.fit_predict(coords)
    return labels

def district_risk_scores(cases_df, days=7):
    today = pd.to_datetime(date.today())
    start = today - pd.Timedelta(days=days-1)
    df = cases_df.copy()
    df['reporting_date'] = pd.to_datetime(df['reporting_date'], errors='coerce')
    recent = df[(df['reporting_date'] >= start) & (df['reporting_date'] <= today)]
    prev = df[(df['reporting_date'] >= (start - pd.Timedelta(days=days))) & (df['reporting_date'] < start)]
    scores = {}
    for dist in pd.unique(df['district'].fillna('unspecified')):
        r = recent[recent['district']==dist]
        p = prev[prev['district']==dist]
        recent_count = len(r)
        prev_count = len(p)
        growth = (recent_count - prev_count) / (prev_count+1)
        score = recent_count * (1 + max(0,growth))
        if recent_count >= 20 or score >= 30:
            level='High'
        elif recent_count >= 7 or score >= 10:
            level='Medium'
        else:
            level='Low'
        scores[dist] = {"recent_count": int(recent_count), "prev_count": int(prev_count),
                        "growth": float(growth), "score": float(score), "level": level}
    return scores

def detect_hotspots(scores, case_threshold=10, growth_threshold=0.5):
    hotspots = []
    for d, info in scores.items():
        if info['recent_count'] >= case_threshold and info['growth'] >= growth_threshold and info['level']=='High':
            hotspots.append(d)
    return hotspots

# ---------------------------
# Email alerting
# ---------------------------
def send_alert_email(subject, body):
    # read SMTP secrets from st.secrets
    smtp_server = st.secrets.get("smtp_server")
    smtp_port = st.secrets.get("smtp_port")
    smtp_user = st.secrets.get("smtp_user")
    smtp_password = st.secrets.get("smtp_password")
    from_email = st.secrets.get("from_email")
    to_list = st.secrets.get("alert_to")
    if not (smtp_server and smtp_port and smtp_user and smtp_password and from_email and to_list):
        st.error("Email alert not configured in secrets (smtp_server, smtp_port, smtp_user, smtp_password, from_email, alert_to)")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = [x.strip() for x in to_list.split(",")]
        msg.set_content(body)
        server = smtplib.SMTP(smtp_server, int(smtp_port))
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Failed sending alert email: {e}")
        return False

# ---------------------------
# UI: sidebar & login/register
# ---------------------------
st.sidebar.image("lima.jpg", width=140)
st.sidebar.title("SurveilAI")
st.sidebar.caption("Smarter Surveillance, Faster Response — Lima 2 Group")

st.title("SurveilAI — Epi Surveillance & Early Warning")

# login (current API: no parameters)
name, authentication_status, username = authenticator.login()

with st.expander("Create an account"):
    with st.form("register_form", clear_on_submit=True):
        reg_user = st.text_input("Username")
        reg_name = st.text_input("Full name")
        reg_pass = st.text_input("Password", type="password")
        reg = st.form_submit_button("Create account")
        if reg:
            if not (reg_user and reg_name and reg_pass):
                st.error("Fill all fields")
            else:
                ok = save_user(reg_user, reg_pass, reg_name)
                if ok:
                    st.experimental_rerun()

if not authentication_status:
    if authentication_status is False:
        st.error("Invalid username/password")
    else:
        st.info("Please log in or register to continue")
    st.stop()

st.sidebar.success(f"Logged in as: {name}")
authenticator.logout("Logout", "sidebar")

# ---------------------------
# Sidebar controls (shapefile etc)
# ---------------------------
st.sidebar.header("Options")
shp_upload = st.sidebar.file_uploader("Upload shapefile ZIP (optional)", type=["zip"])
geoj = None
shapefile_gdf = None
if shp_upload is not None:
    try:
        shapefile_gdf = load_shapefile_from_zipobj(shp_upload.read())
        st.sidebar.success("Shapefile loaded")
    except Exception as e:
        st.sidebar.error(f"Could not load shapefile: {e}")
else:
    # try load pre-converted geojson in repo
    shapefile_gdf = load_geojson_if_present(GEOJSON_FILE)
    if shapefile_gdf is not None:
        st.sidebar.info(f"Loaded {GEOJSON_FILE}")

alert_threshold_7day = st.sidebar.number_input("Alert threshold (cases in 7 days)", value=20, min_value=1)
cluster_eps_m = st.sidebar.number_input("Cluster radius (meters)", value=500, min_value=50)
min_cluster_samples = st.sidebar.number_input("Min cluster samples", value=3, min_value=2)

# Test email send
st.sidebar.markdown("### Alerting")
if st.sidebar.button("Send test alert email"):
    ok = send_alert_email("SurveilAI test alert", "This is a test alert from SurveilAI.")
    if ok:
        st.sidebar.success("Test alert sent")

# ---------------------------
# Case entry
# ---------------------------
st.header("Enter new case / report")
with st.form("case_entry", clear_on_submit=True):
    case_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    st.markdown(f"**Case ID:** `{case_id}`")

    patient_name = st.text_input("Patient name (optional)")
    age = st.number_input("Age", min_value=0, max_value=120, value=25)
    # age group derived later
    sex = st.selectbox("Sex", ["male","female","other"])
    onset_date = st.date_input("Date of onset", value=date.today())
    reporting_date = st.date_input("Reporting date", value=date.today())
    # role & reporter
    role = st.selectbox("Reporter role", ["Frontline worker","Community volunteer","Other"])
    reporter_name = st.text_input("Reporter name (enter your name)")

    st.markdown("### Symptoms & exposures")
    fever = st.checkbox("Fever")
    cough = st.checkbox("Cough")
    vomiting = st.checkbox("Vomiting")
    diarrhea = st.checkbox("Diarrhea")
    rash = st.checkbox("Rash")
    diff_breath = st.checkbox("Difficulty breathing")
    bleeding = st.checkbox("Bleeding")
    contact_case = st.checkbox("Contact with known case")
    travel_recent = st.checkbox("Recent travel")
    labpos = st.checkbox("Lab-confirmed positive")

    st.markdown("### Location")
    lat_manual = st.number_input("Latitude (decimal) - leave 0.0 if unknown", format="%.6f", value=0.0)
    lon_manual = st.number_input("Longitude (decimal) - leave 0.0 if unknown", format="%.6f", value=0.0)

    auto_choice = st.radio("Get location automatically?", ("No","Use map click (recommended)","Use manual lat/lon"))
    sel_lat, sel_lon = None, None
    if auto_choice == "Use map click (recommended)":
        m = folium.Map(location=[5.55, -0.2], zoom_start=6)
        folium.TileLayer('openstreetmap').add_to(m)
        out = st_folium(m, width=800, height=350)
        if out and out.get("last_clicked"):
            sel_lat = out["last_clicked"]["lat"]
            sel_lon = out["last_clicked"]["lng"]
            st.info(f"Selected: {sel_lat:.6f}, {sel_lon:.6f}")
    elif auto_choice == "Use manual lat/lon":
        if float(lat_manual) != 0.0 and float(lon_manual) != 0.0:
            sel_lat = float(lat_manual)
            sel_lon = float(lon_manual)

    town = st.text_input("Town / community (optional)")
    landmark = st.text_input("Landmark (optional)")

    submit_case = st.form_submit_button("Submit case")

if submit_case:
    latitude = sel_lat if sel_lat is not None else (None if float(lat_manual)==0.0 else float(lat_manual))
    longitude = sel_lon if sel_lon is not None else (None if float(lon_manual)==0.0 else float(lon_manual))
    rec = {
        "case_id": case_id,
        "name": patient_name,
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
        "difficulty_breathing": diff_breath,
        "bleeding": bleeding,
        "contact_with_case": contact_case,
        "travel_recent": travel_recent,
        "lab_positive": labpos,
        "latitude": latitude,
        "longitude": longitude,
        "region": None,
        "district": None,
        "community": town,
        "town": town,
        "landmark": landmark,
        "role": role,
        "reporter_name": reporter_name
    }
    score, category = compute_risk_and_category(rec)
    rec["score"] = score
    rec["category"] = category
    try:
        od = pd.to_datetime(rec["onset_date"]).date()
        iy, iw, _ = od.isocalendar()
        rec["epi_year"], rec["epi_week"] = iy, iw
    except Exception:
        rec["epi_year"], rec["epi_week"] = None, None

    if shapefile_gdf is not None and rec["latitude"] and rec["longitude"]:
        r, d, c = point_to_admin(rec["latitude"], rec["longitude"], shapefile_gdf)
        if r and not rec.get("region"):
            rec["region"] = r
        if d and not rec.get("district"):
            rec["district"] = d
        if c and not rec.get("community"):
            rec["community"] = c

    save_case(rec)
    st.success(f"Saved case {case_id} — category: {category} (score {score})")

# ---------------------------
# Load data & metrics
# ---------------------------
cases_df = load_cases_df()
if not cases_df.empty:
    cases_df['reporting_date'] = pd.to_datetime(cases_df['reporting_date'], errors='coerce')
    cases_df['onset_date'] = pd.to_datetime(cases_df['onset_date'], errors='coerce')

# epi week summary
today = pd.to_datetime(date.today())
yi, wi, _ = today.isocalendar()
cases_df['epi_week_tuple'] = cases_df.apply(lambda r: (r.get('epi_year'), r.get('epi_week')), axis=1)
cases_this_week = cases_df[(cases_df['epi_week_tuple'].apply(lambda t: t==(yi,wi)))]

# Sidebar quick stats
st.sidebar.header("Quick stats")
st.sidebar.metric("Total cases", len(cases_df))
st.sidebar.metric("This epi week", len(cases_this_week))

# District risk & hotspot check
scores = district_risk_scores(cases_df, days=7)
hotspots = detect_hotspots(scores, case_threshold=alert_threshold_7day, growth_threshold=0.5)
if hotspots:
    st.warning(f"⚠️ Hotspot(s) detected: {', '.join(hotspots)} — investigate immediately")
    # send email alert (one-time per detection cycle)
    if st.sidebar.button("Send hotspot alert email"):
        body = f"Hotspots detected: {', '.join(hotspots)}\n\nDetails:\n{json.dumps(scores, indent=2)}"
        ok = send_alert_email("SurveilAI: Hotspot Alert", body)
        if ok:
            st.sidebar.success("Alert email sent")

# ---------------------------
# Dashboard reports
# ---------------------------
st.header("Dashboard & Reports")

col1, col2, col3 = st.columns(3)
with col1:
    st.subheader("Summary")
    st.write(f"Total cases: {len(cases_df)}")
    st.write(f"Suspected: {len(cases_df[cases_df['category']=='suspected'])}")
    st.write(f"Probable: {len(cases_df[cases_df['category']=='probable'])}")
    st.write(f"Confirmed: {len(cases_df[cases_df['category']=='confirmed'])}")

with col2:
    st.subheader("By sex")
    if not cases_df.empty:
        s = cases_df['sex'].fillna('unknown').value_counts().reset_index()
        s.columns = ['sex','n']
        fig = px.pie(s, values='n', names='sex', title='Cases by sex')
        st.plotly_chart(fig, use_container_width=True)

with col3:
    st.subheader("By age group")
    if not cases_df.empty:
        ag = cases_df['age_group'].fillna('unknown').value_counts().reset_index()
        ag.columns=['age_group','n']
        fig2 = px.bar(ag, x='age_group', y='n', title='Cases by age group')
        st.plotly_chart(fig2, use_container_width=True)

# epi curve (onset)
st.subheader("Epi curve (by onset date)")
if not cases_df.empty:
    epi = cases_df.dropna(subset=['onset_date']).groupby(cases_df['onset_date'].dt.date).size().reset_index(name='count')
    if not epi.empty:
        fig_epi = px.area(epi, x='onset_date', y='count', title='Epi curve (by onset date)')
        st.plotly_chart(fig_epi, use_container_width=True)
    else:
        st.info("Not enough onset date data for epi curve")

# district table
st.subheader("District risk scores")
if scores:
    risk_df = pd.DataFrame.from_dict(scores, orient='index').reset_index().rename(columns={'index':'district'})
    st.dataframe(risk_df)
else:
    st.info("No district risk data")

# Map (heatmap + clusters)
st.subheader("Map: heatmap & clusters")
map_df = cases_df.dropna(subset=['latitude','longitude']).copy()
if not map_df.empty:
    gdf_cases = gpd.GeoDataFrame(map_df, geometry=gpd.points_from_xy(map_df.longitude, map_df.latitude)).set_crs(epsg=4326)
    coords_df = pd.DataFrame({'latitude': gdf_cases.geometry.y, 'longitude': gdf_cases.geometry.x})
    labels = cluster_cases(coords_df, eps_m=cluster_eps_m, min_samples=max(2,int(min_cluster_samples)))
    gdf_cases['cluster'] = labels
    mid_lat = gdf_cases.geometry.y.mean()
    mid_lon = gdf_cases.geometry.x.mean()
    m = folium.Map(location=[mid_lat, mid_lon], zoom_start=8)
    if shapefile_gdf is not None:
        folium.GeoJson(shapefile_gdf.to_json(), name='districts').add_to(m)
    elif os.path.exists(GEOJSON_FILE):
        folium.GeoJson(load_geojson_if_present(GEOJSON_FILE).to_json(), name='districts').add_to(m)
    heat_data = [[pt.y, pt.x] for pt in gdf_cases.geometry]
    HeatMap(heat_data, radius=15).add_to(m)
    for _, r in gdf_cases.iterrows():
        popup = f"ID: {r['case_id']}<br>cat: {r['category']}<br>score: {r['score']}"
        folium.CircleMarker(location=[r.geometry.y, r.geometry.x], radius=4,
                            popup=popup, color='red' if r['category']=='confirmed' else 'orange').add_to(m)
    st_folium(m, width=900, height=500)
else:
    st.info("No geolocated cases to show")

# Exports
st.sidebar.header("Export")
if st.sidebar.button("Download cases CSV"):
    st.sidebar.download_button("Download CSV", data=cases_df.to_csv(index=False).encode('utf-8'),
                               file_name='cases_export.csv', mime='text/csv')

st.sidebar.caption("SurveilAI — Lima 2 Group")
# End

