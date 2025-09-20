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
st.sidebar.title("Surveilai")
logo_upload = st.sidebar.file_uploader("Upload official logo (lima.jpg)", type=['jpg','jpeg','png'], key="logo_upload")
if logo_upload:
    with open("assets/lima.jpg", "wb") as out:
        out.write(logo_upload.read())
try:
    st.sidebar.image("assets/lima.jpg", width=120)
except:
    st.sidebar.write("LIMA Group")

st.sidebar.markdown("Created by LIMA Group")

# Auth UI
auth_mode = st.sidebar.radio("Auth", ["Login", "Sign up"], key="auth_mode")
if auth_mode == "Sign up":
    st.sidebar.subheader("Create account")
    new_user = st.sidebar.text_input("Username", key="signup_username")
    new_pass = st.sidebar.text_input("Password", type="password", key="signup_password")
    display_name = st.sidebar.text_input("Full name", key="signup_fullname")
    role_choice = st.sidebar.selectbox("Role", ["user","investigator","admin"], key="signup_role")
    if st.sidebar.button("Create account", key="signup_button"):
        ok, msg = create_user(new_user, new_pass, display_name, role_choice)
        st.sidebar.success(msg if ok else f"Error: {msg}")

st.sidebar.markdown("---")

if st.sidebar.button("About Surveilai", key="about_button"):
    st.session_state["page"] = "about"

username = st.sidebar.text_input("Username", key="login_username")
password = st.sidebar.text_input("Password", type="password", key="login_password")
if st.sidebar.button("Login", key="login_button"):
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
    ...
    """)
    st.stop()

# Admin menu
if st.session_state["user"]["role"] == "admin":
    st.sidebar.markdown("## Admin")
    if st.sidebar.button("User management", key="admin_users"):
        st.session_state["admin_page"] = "users"
    if st.sidebar.button("Alerts & thresholds", key="admin_alerts"):
        st.session_state["admin_page"] = "alerts"

# --- MAIN APP ---
st.header("Surveilai — District outbreak risk & case reporting")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Report a case")
    with st.form("case_form", clear_on_submit=True):
        name = st.text_input("Patient name (optional)", key="case_name")
        sex = st.selectbox("Sex", ["Unknown","Male","Female","Other"], key="case_sex")
        age = st.number_input("Age", min_value=0, max_value=120, value=0, key="case_age")
        reporter = st.selectbox("Reporter", ["Frontline worker", "Community volunteer", "Citizen"], key="case_reporter")
        region = st.text_input("Region (optional)", key="case_region")
        district = st.text_input("District (optional)", key="case_district")
        community = st.text_input("Community (optional)", key="case_community")
        onset_date = st.date_input("Onset / report date", value=datetime.today(), key="case_date")
        lab_positive = st.checkbox("Lab-confirmed positive", key="case_lab")
        fever = st.checkbox("Fever", key="case_fever")
        cough = st.checkbox("Cough", key="case_cough")
        rash = st.checkbox("Rash", key="case_rash")
        other_symptoms = st.text_area("Other symptoms (comma-separated)", key="case_other_symptoms")
        use_coords = st.radio("Location input", ["Manual", "Auto-detect (ask browser)"], key="case_location_input")
        coords = None
        if use_coords == "Auto-detect (ask browser)":
            st.write("Click the button below and paste coordinates if auto-detect is not available.")
            coords_btn = st.button("Get my current coordinates", key="coords_button")
            coords_text = st.text_input("Paste coordinates as lat,lon (e.g. -1.234,36.78)", key="coords_text_auto")
            if coords_text:
                try:
                    lat, lon = coords_text.split(",")
                    coords = (float(lat.strip()), float(lon.strip()))
                except:
                    st.warning("Invalid coords format.")
        else:
            coords_text = st.text_input("Coordinates (lat,lon) optional", key="coords_text_manual")

        submit = st.form_submit_button("Submit case", key="submit_case")
        if submit:
            ...
            st.success(f"Case {case_id} saved as {classification}")

with col2:
    st.subheader("Uploads & shapefile")
    shp_zip = st.file_uploader("Upload shapefile .zip", type=["zip"], key="shapefile_upload")
    if shp_zip:
        ...

    st.subheader("Analytics & dashboard")
    ...

# Admin pages
if st.session_state["user"]["role"] == "admin" and st.session_state.get("admin_page") == "users":
    st.header("User management (admin)")
    users_df = get_all_users()
    st.table(users_df)
    st.subheader("Change user role")
    uname = st.text_input("Username to change role", key="admin_change_username")
    newrole = st.selectbox("New role", ["user","investigator","admin"], key="admin_change_role")
    if st.button("Set role", key="admin_set_role"):
        set_user_role(uname, newrole)
        st.success("Role updated. Refresh to see changes.")

if st.session_state["user"]["role"] == "admin" and st.session_state.get("admin_page") == "alerts":
    st.header("Alerts & thresholds / Config editor")
    cfg_text = open(CONFIG_PATH).read()
    edited = st.text_area("config.yaml", value=cfg_text, height=300, key="config_text")
    if st.button("Save config.yaml", key="save_config"):
        ...
    if st.button("Reload config", key="reload_config"):
        st.experimental_rerun()

st.sidebar.markdown("---")
st.sidebar.write("Export & admin")
if st.sidebar.button("Download CSV of cases", key="download_csv"):
    ...
