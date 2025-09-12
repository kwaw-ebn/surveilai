import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import plotly.express as px
import random, string, os, secrets, bcrypt
from datetime import datetime

# -------------------------------
# 🔑 USER MANAGEMENT
# -------------------------------
USERS_FILE = "users.csv"
if not os.path.exists(USERS_FILE):
    pd.DataFrame(columns=["username", "name", "password"]).to_csv(USERS_FILE, index=False)

def load_users():
    return pd.read_csv(USERS_FILE) if os.path.exists(USERS_FILE) else pd.DataFrame(columns=["username", "password", "name"])

def save_user(username, plain_password, name):
    users = load_users()
    if username in users["username"].values:
        st.error("⚠️ Username already exists!")
        return False
    hashed = bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()
    new_row = pd.DataFrame([[username, hashed, name]], columns=["username", "password", "name"])
    users = pd.concat([users, new_row], ignore_index=True)
    users.to_csv(USERS_FILE, index=False)
    st.success(f"✅ User '{username}' created successfully!")
    st.info("🔑 You can now log in with your new account.")
    st.experimental_rerun()
    return True

users_df = load_users()

# Generate credentials dynamically from CSV
credentials = {"usernames": {}}
for _, row in users_df.iterrows():
    credentials["usernames"][row["username"]] = {
        "name": row["name"],
        "password": row["password"]
    }

cookie_key = "supersecurekey_123456"  # You can replace with secrets.token_urlsafe(64)
authenticator = stauth.Authenticate(credentials, "SurveilAI_Cookie", cookie_key, cookie_expiry_days=30)

# -------------------------------
# LOGIN FORM
# -------------------------------
st.title("🔐 SurveilAI Login")
name, authentication_status, username = authenticator.login("Login", "main")

# -------------------------------
# CREATE ACCOUNT FORM
# -------------------------------
with st.expander("👤 Create New Account"):
    with st.form("create_account_form", clear_on_submit=True):
        new_username = st.text_input("Choose a Username")
        new_name = st.text_input("Full Name")
        new_password = st.text_input("Choose a Password", type="password")
        submit = st.form_submit_button("Create Account")
        if submit:
            if new_username and new_name and new_password:
                save_user(new_username, new_password, new_name)
            else:
                st.error("⚠️ Please fill in all fields")

# -------------------------------
# MAIN APP
# -------------------------------
if authentication_status:
    st.sidebar.image("lima.jpg", use_column_width=True)
    st.sidebar.title("SurveilAI")
    st.sidebar.caption("Smarter Surveillance, Faster Response")
    authenticator.logout("🚪 Logout", "sidebar")

    st.title("📊 SurveilAI – Epi Surveillance Dashboard")

    # 📂 UPLOAD SHAPEFILE
    shapefile_zip = st.file_uploader("Upload Shapefile (.zip)", type=["zip"])
    gdf = None
    if shapefile_zip:
        with open("shapefile.zip", "wb") as f:
            f.write(shapefile_zip.read())
        try:
            gdf = gpd.read_file("zip://shapefile.zip")
            st.success("✅ Shapefile loaded successfully!")
        except Exception as e:
            st.error(f"❌ Could not read shapefile: {e}")

    # 🗂 DATA STORAGE
    DATA_FILE = "cases.csv"
    if not os.path.exists(DATA_FILE):
        df = pd.DataFrame(columns=["CaseID", "Date", "Reporter", "Region", "District", "Community",
                                   "Landmark", "Age", "Sex", "Classification", "Latitude", "Longitude"])
        df.to_csv(DATA_FILE, index=False)
    else:
        df = pd.read_csv(DATA_FILE)

    # 📝 CASE ENTRY FORM
    with st.form("case_entry"):
        st.subheader("🆕 Add New Case")
        case_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        st.text(f"Generated Case ID: {case_id}")

        date = st.date_input("Reporting Date", value=datetime.today())
        reporter = st.text_input("Frontline Worker / Volunteer")
        landmark = st.text_input("Nearest Landmark")
        age = st.number_input("Age (years)", min_value=0, max_value=120, step=1)
        sex = st.selectbox("Sex", ["Male", "Female"])
        classification = st.selectbox("Case Classification", ["Suspected", "Probable", "Confirmed"])

        st.markdown("**📍 Location**")
        latitude, longitude, region, district, community = None, None, None, None, None
        m = folium.Map(location=[5.55, -0.2], zoom_start=6)
        output = st_folium(m, width=700, height=400)
        if output and output.get("last_clicked"):
            latitude = output["last_clicked"]["lat"]
            longitude = output["last_clicked"]["lng"]

            if gdf is not None:
                point = gpd.GeoDataFrame(geometry=gpd.points_from_xy([longitude], [latitude]), crs=gdf.crs)
                join = gpd.sjoin(point, gdf, how="left", predicate="within")
                if not join.empty:
                    region = join.iloc[0].get("region", None)
                    district = join.iloc[0].get("district", None)
                    community = join.iloc[0].get("community", None)

        submitted = st.form_submit_button("💾 Save Case")
        if submitted:
            new_case = pd.DataFrame([{
                "CaseID": case_id, "Date": date, "Reporter": reporter,
                "Region": region, "District": district, "Community": community,
                "Landmark": landmark, "Age": age, "Sex": sex,
                "Classification": classification, "Latitude": latitude, "Longitude": longitude
            }])
            df = pd.concat([df, new_case], ignore_index=True)
            df.to_csv(DATA_FILE, index=False)
            st.success(f"✅ Case {case_id} saved successfully!")

    # 📊 SUMMARY DASHBOARD
    st.subheader("📊 Summary Statistics")
    st.metric("Total Cases", len(df))
    st.metric("Confirmed Cases", len(df[df["Classification"] == "Confirmed"]))

    if not df.empty:
        st.subheader("📈 Epi Curve")
        epi_curve = df.groupby("Date").size().reset_index(name="Cases")
        fig_epi = px.bar(epi_curve, x="Date", y="Cases", title="Epi Curve")
        st.plotly_chart(fig_epi, use_container_width=True)

        st.subheader("📋 Case Records")
        st.dataframe(df)

elif authentication_status is False:
    st.error("❌ Invalid username or password")
elif authentication_status is None:
    st.warning("ℹ️ Please log in or create an account")

