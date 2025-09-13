# streamlit_app.py
# SurveilAI — Full Integrated App with Signup/Login, Case Entry, Clustering, Dashboard, and Reports

import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import plotly.express as px
import geopandas as gpd
import os
import random, string, bcrypt
from datetime import datetime, timedelta
from sklearn.cluster import DBSCAN
from folium.plugins import HeatMap
import streamlit_authenticator as stauth
import smtplib
from email.message import EmailMessage

# ✅ MUST BE FIRST STREAMLIT CALL
st.set_page_config(layout="wide", page_title="SurveilAI — Epi Dashboard")

# ===============================
# 1️⃣ USER & DATA FILE MANAGEMENT
# ===============================
USERS_FILE = "users.csv"
DATA_FILE = "cases.csv"
GEOJSON_FILE = "districts.geojson"

def load_users_df():
    if not os.path.exists(USERS_FILE) or os.path.getsize(USERS_FILE) == 0:
        df = pd.DataFrame(columns=["username", "name", "password"])
        df.to_csv(USERS_FILE, index=False)
        return df
    try:
        df = pd.read_csv(USERS_FILE)
        required_columns = {"username", "name", "password"}
        if not required_columns.issubset(df.columns):
            df = pd.DataFrame(columns=list(required_columns))
            df.to_csv(USERS_FILE, index=False)
        return df
    except Exception:
        df = pd.DataFrame(columns=["username", "name", "password"])
        df.to_csv(USERS_FILE, index=False)
        return df

def ensure_admin_user():
    users = load_users_df()
    if users.empty:
        admin_username = st.secrets.get("ADMIN_USERNAME", "admin")
        admin_password = st.secrets.get("ADMIN_PASSWORD", "admin123")
        admin_name = st.secrets.get("ADMIN_NAME", "System Admin")
        hashed_pw = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()
        new_row = pd.DataFrame([[admin_username, admin_name, hashed_pw]],
                               columns=["username", "name", "password"])
        users = pd.concat([users, new_row], ignore_index=True)
        users.to_csv(USERS_FILE, index=False)
    return users

def build_credentials():
    users = ensure_admin_user()
    creds = {"usernames": {}}
    for _, row in users.iterrows():
        creds["usernames"][row["username"]] = {
            "name": row["name"],
            "password": row["password"]
        }
    return creds

# Ensure data file exists
if not os.path.exists(DATA_FILE):
    cols = ["case_id","name","age","age_group","sex","onset_date","reporting_date","date_of_entry",
            "fever","cough","vomiting","diarrhea","rash","difficulty_breathing","bleeding",
            "contact_with_case","travel_recent","lab_positive",
            "latitude","longitude","region","district","community","town","landmark","role","reporter_name",
            "score","category","epi_year","epi_week"]
    pd.DataFrame(columns=cols).to_csv(DATA_FILE, index=False)

# ===============================
# 2️⃣ AUTHENTICATION
# ===============================
COOKIE_KEY = st.secrets.get("cookie_key", "dev_cookie_key_for_demo_replace_this")
authenticator = stauth.Authenticate(
    build_credentials(),
    "SurveilAI_Cookie",
    COOKIE_KEY,
    cookie_expiry_days=30
)

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

# Sidebar & Login
st.sidebar.image("lima.jpg", width=140)
st.sidebar.title("SurveilAI")
st.sidebar.caption("Smarter Surveillance, Faster Response — Lima 2 Group")

st.title("SurveilAI — Epi Surveillance & Early Warning")

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

# ===============================
# 3️⃣ CASE ENTRY FORM
# ===============================
df = pd.read_csv(DATA_FILE)
st.subheader("📋 New Case Entry")
with st.form("case_form", clear_on_submit=True):
    case_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    name_input = st.text_input("Patient Name")
    age = st.number_input("Age", 0, 120)
    sex = st.selectbox("Sex", ["Male","Female"])
    onset_date = st.date_input("Onset Date", value=datetime.today())
    lat = st.number_input("Latitude", format="%.6f")
    lon = st.number_input("Longitude", format="%.6f")
    fever = st.checkbox("Fever")
    cough = st.checkbox("Cough")
    diarrhea = st.checkbox("Diarrhea")
    submit = st.form_submit_button("Save Case")
    if submit:
        new_row = pd.DataFrame([{
            "case_id": case_id,
            "name": name_input,
            "age": age,
            "sex": sex,
            "onset_date": onset_date,
            "reporting_date": datetime.today(),
            "date_of_entry": datetime.today(),
            "fever": fever,
            "cough": cough,
            "diarrhea": diarrhea,
            "latitude": lat,
            "longitude": lon,
            "reporter_name": name
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(DATA_FILE, index=False)
        st.success(f"✅ Case {case_id} saved")

# ===============================
# 4️⃣ DASHBOARD + MAP
# ===============================
st.subheader("📊 Surveillance Dashboard")
if df.empty:
    st.info("No cases yet.")
else:
    st.metric("Total Cases", len(df))
    st.metric("Fever %", f"{100 * df['fever'].mean():.1f}%")
    # Map
    m = folium.Map(location=[df["latitude"].mean() if not df["latitude"].isna().all() else 5.55,
                             df["longitude"].mean() if not df["longitude"].isna().all() else -0.2],
                   zoom_start=8)
    for _, row in df.iterrows():
        if not pd.isna(row["latitude"]) and not pd.isna(row["longitude"]):
            folium.CircleMarker([row["latitude"], row["longitude"]],
                                radius=5, color="red", fill=True).add_to(m)
    st_folium(m, width=700, height=500)

    # Epidemic curve
    df["reporting_date"] = pd.to_datetime(df["reporting_date"])
    epi_curve = df.groupby(df["reporting_date"].dt.date).size().reset_index(name="cases")
    fig = px.bar(epi_curve, x="reporting_date", y="cases", title="Epidemic Curve")
    st.plotly_chart(fig, use_container_width=True)

# ===============================
# END OF APP
# ===============================

