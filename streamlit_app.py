# streamlit_app.py
"""
SurveilAI — Smarter Surveillance, Faster Response
Streamlit epidemic intelligence dashboard:
- Rule-based risk scoring & classification
- Case entry + CSV upload
- Shapefile overlay
- Heatmaps & clustering for epicentres
- Epi curves, summary stats, alerts
- Export to CSV/JSON
"""
import streamlit as st
import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
import zipfile
import io
import os
from sklearn.cluster import DBSCAN
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import plotly.express as px
from datetime import datetime

# -------------------------
# App Layout Config
# -------------------------
st.set_page_config(layout="wide", page_title="SurveilAI — Epi Dashboard")

# Header with logo and tagline
col_logo, col_title = st.columns([1,4])
with col_logo:
    try:
        st.image("lima.jpg", width=120)
    except Exception:
        st.warning("Logo file 'lima.jpg' not found in app folder.")
with col_title:
    st.title("SurveilAI")
    st.markdown("**Smarter Surveillance, faster response.**")

st.sidebar.markdown("---")
st.sidebar.markdown("### Created by Lima 2 Group")

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
    g = gpd.GeoDataFrame(df_coords.copy(), geometry=gpd.points_from_xy(df_coords.longitude, df_coords.latitude))
    g = g.set_crs(epsg=4326)
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

# -------------------------
# Sidebar Inputs
# -------------------------
st.sidebar.header("Uploads & Settings")
shapefile_zip = st.sidebar.file_uploader("Upload Ghana shapefile ZIP (optional)", type=['zip'])
csv_upload = st.sidebar.file_uploader("Upload cases CSV (optional)", type=['csv'])
alert_threshold = st.sidebar.number_input("Alert threshold (new cases in last 7 days)", min_value=1, value=20)
cluster_eps_m = st.sidebar.number_input("Cluster radius (meters)", min_value=50, max_value=5000, value=500, step=50)
min_cluster_samples = st.sidebar.number_input("Min samples for cluster", min_value=2, value=3)

shapefile_gdf = None
if shapefile_zip is not None:
    shapefile_gdf = load_shapefile_from_zip(shapefile_zip.read())
    if shapefile_gdf is not None:
        st.sidebar.success(f"Loaded shapefile with {len(shapefile_gdf)} features.")

if 'cases' not in st.session_state:
    st.session_state['cases'] = []

# -------------------------
# Case Entry Form
# -------------------------
st.header("Enter a new case")
with st.form('case_form'):
    name = st.text_input('Name (optional)')
    age = st.number_input('Age', min_value=0, max_value=120, value=25)
    sex = st.selectbox('Sex', options=['male','female','other'])
    onset_date = st.date_input('Date of onset', value=datetime.today())
    st.write('Symptoms')
    fever = st.checkbox('Fever')
    cough = st.checkbox('Cough')
    vomiting = st.checkbox('Vomiting')
    diarrhea = st.checkbox('Diarrhea')
    rash = st.checkbox('Rash')
    difficulty_breathing = st.checkbox('Difficulty breathing')
    contact_with_case = st.checkbox('Contact with known case')
    travel_recent = st.checkbox('Recent travel to high-risk area')
    lab_positive = st.checkbox('Lab-confirmed (positive)')
    latitude = st.number_input('Latitude', format="%.6f", value=0.0)
    longitude = st.number_input('Longitude', format="%.6f", value=0.0)
    notes = st.text_area('Notes (optional)')
    submitted = st.form_submit_button('Submit Case')

if submitted:
    case_id = f"case_{len(st.session_state['cases'])+1}"
    case_record = {
        'case_id': case_id, 'name': name, 'age': int(age), 'sex': sex,
        'onset_date': str(onset_date),
        'fever': fever, 'cough': cough, 'vomiting': vomiting, 'diarrhea': diarrhea,
        'rash': rash, 'difficulty_breathing': difficulty_breathing,
        'contact_with_case': contact_with_case, 'travel_recent': travel_recent,
        'lab_positive': lab_positive, 'latitude': latitude if latitude!=0 else None,
        'longitude': longitude if longitude!=0 else None, 'notes': notes
    }
    score, category = compute_risk_score(case_record)
    case_record['score'], case_record['category'] = score, category
    st.session_state['cases'].append(case_record)
    st.success(f"Saved {case_id} — {category} (score {score})")

# -------------------------
# Data Handling
# -------------------------
cases_df = pd.DataFrame(st.session_state['cases'])
if csv_upload is not None:
    try:
        uploaded_df = pd.read_csv(csv_upload)
        cases_df = pd.concat([cases_df, uploaded_df], ignore_index=True, sort=False)
        st.sidebar.success(f"CSV uploaded: {len(uploaded_df)} rows")
    except Exception as e:
        st.sidebar.error(f"Failed to read CSV: {e}")

if not cases_df.empty:
    cases_df['latitude'] = pd.to_numeric(cases_df.get('latitude'), errors='coerce')
    cases_df['longitude'] = pd.to_numeric(cases_df.get('longitude'), errors='coerce')
    cases_map = cases_df.dropna(subset=['latitude','longitude']).copy()
    if not cases_map.empty:
        gdf_cases = gpd.GeoDataFrame(cases_map,
                                     geometry=gpd.points_from_xy(cases_map.longitude, cases_map.latitude)).set_crs(epsg=4326)
    else:
        gdf_cases = gpd.GeoDataFrame(columns=['case_id','geometry'])
else:
    gdf_cases = gpd.GeoDataFrame(columns=['case_id','geometry'])

# -------------------------
# Layout: Map and Stats
# -------------------------
col1, col2 = st.columns((2,1))
with col1:
    st.subheader('Map — Cases & Heatmap')
    folium_map = plot_map_with_cases(gdf_cases, base_gdf=shapefile_gdf)
    st_data = st_folium(folium_map, width=700, height=500)
    st.subheader('Clusters / Epicentres')
    if not gdf_cases.empty:
        coords_df = pd.DataFrame({'latitude': gdf_cases.geometry.y, 'longitude': gdf_cases.geometry.x})
        labels = cluster_cases(coords_df, eps_m=cluster_eps_m, min_samples=int(min_cluster_samples))
        gdf_cases['cluster'] = labels
        st.write(gdf_cases[['case_id','onset_date','category','score','cluster']].head(30))
        cluster_counts = gdf_cases.groupby('cluster').size().reset_index(name='n').sort_values('n', ascending=False)
        st.write('Cluster sizes:')
        st.write(cluster_counts)
        if not cluster_counts[cluster_counts['cluster']!=-1].empty:
            fig = px.bar(cluster_counts[cluster_counts['cluster']!=-1], x='cluster', y='n')
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info('No geolocated cases.')

with col2:
    st.subheader('Summary statistics & Epi curve')
    if not cases_df.empty:
        cases_df['onset_date'] = pd.to_datetime(cases_df.get('onset_date'), errors='coerce')
        today = pd.Timestamp(datetime.today().date())
        last_7 = cases_df[cases_df['onset_date'] >= (today - pd.Timedelta(days=7))]
        st.metric('Cases (total)', len(cases_df))
        st.metric('Cases last 7 days', len(last_7))
        if len(last_7) >= alert_threshold:
            st.warning(f'ALERT: {len(last_7)} cases in last 7 days (threshold {alert_threshold})')
        epi = cases_df.dropna(subset=['onset_date']).groupby(cases_df['onset_date'].dt.date).size().reset_index(name='count')
        if not epi.empty:
            fig = px.area(epi, x='onset_date', y='count', title='Epi curve')
            st.plotly_chart(fig, use_container_width=True)
        cat_counts = cases_df.get('category').fillna('unspecified').value_counts().reset_index()
        cat_counts.columns = ['category','n']
        fig2 = px.pie(cat_counts, names='category', values='n', title='Classification')
        st.plotly_chart(fig2, use_container_width=True)
        st.subheader('Case line list')
        st.dataframe(cases_df.head(200))
    else:
        st.info('No cases yet.')

# -------------------------
# Export
# -------------------------
st.sidebar.header('Export')
if st.sidebar.button('Download cases CSV'):
    if not cases_df.empty:
        csv_bytes = cases_df.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button('Download CSV', data=csv_bytes,
                                   file_name='cases_export.csv', mime='text/csv')
    else:
        st.sidebar.info('No data to export')
if st.sidebar.button('Save session to local JSON'):
    if not cases_df.empty:
        out_path = 'cases_export.json'
        cases_df.to_json(out_path, orient='records', date_format='iso')
        st.sidebar.success(f'Saved to {out_path}')
    else:
        st.sidebar.info('No data to save')

