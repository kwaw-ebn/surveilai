# streamlit_app.py
import streamlit as st
from utils import (
    init_db,
    get_user,
    create_user,
    check_password,
    add_case,
    query_summary,
    load_shapefile_from_zip,
    cluster_epicenters,
    assign_district_from_point,
    get_all_users,
    set_user_role,
)
import sqlite3
import uuid
import pandas as pd
import geopandas as gpd
from datetime import datetime, date
import folium
from streamlit_folium import st_folium
import base64
import yaml
import os
import plotly.express as px

# ---------- CONFIG ----------
st.set_page_config(page_title="Surveilai", layout="wide", initial_sidebar_state="expanded")
init_db()
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
else:
    config = {}

# ---------- UTIL SESSION SETUP ----------
if "user" not in st.session_state:
    st.session_state["user"] = None
if "shapefile_gdf" not in st.session_state:
    st.session_state["shapefile_gdf"] = None
if "cases_df" not in st.session_state:
    # load existing cases from DB if query_summary exists
    try:
        st.session_state["cases_df"] = query_summary()  # expected to return pandas DataFrame
    except Exception:
        st.session_state["cases_df"] = pd.DataFrame()

# ---------- SIDEBAR: show auth only when not logged in ----------
if not st.session_state["user"]:
    st.sidebar.title("Surveilai — Login / Sign up")
    st.sidebar.markdown("Created by LIMA Group")

    # Optional logo upload
    logo_upload = st.sidebar.file_uploader("Upload official logo (lima.jpg)", type=["jpg", "jpeg", "png"], key="logo_upload")
    if logo_upload:
        os.makedirs("assets", exist_ok=True)
        with open("assets/lima.jpg", "wb") as out:
            out.write(logo_upload.read())

    try:
        st.sidebar.image("assets/lima.jpg", width=120)
    except Exception:
        st.sidebar.write("LIMA Group")

    # Choose auth method
    st.sidebar.markdown("---")
    auth_method = st.sidebar.radio("Auth method", ["Username & Password", "5-digit code"], index=0)

    # Signup
    with st.sidebar.expander("Sign up"):
        new_user = st.text_input("Username", key="signup_username")
        new_pass = st.text_input("Password", type="password", key="signup_password")
        display_name = st.text_input("Full name", key="signup_fullname")
        role_choice = st.selectbox("Role", ["user", "investigator", "admin"], key="signup_role")
        if st.button("Create account", key="signup_button"):
            ok, msg = create_user(new_user, new_pass, display_name, role_choice)
            if ok:
                st.success(msg)
            else:
                st.error(f"Error: {msg}")

    st.sidebar.markdown("---")
    # Login area
    if auth_method == "Username & Password":
        username = st.sidebar.text_input("Username", key="login_username")
        password = st.sidebar.text_input("Password", type="password", key="login_password")
        if st.sidebar.button("Login", key="login_button"):
            user = get_user(username)
            if user and check_password(password, user["password"]):
                st.session_state["user"] = {"username": username, "name": user.get("name", username), "role": user.get("role", "user")}
                st.experimental_rerun()
            else:
                st.sidebar.error("Invalid credentials")
    else:
        # Simple 5-digit code flow (this is an example; recommend linking to SMS/OTP service)
        code_username = st.sidebar.text_input("Username for code login", key="code_username")
        # For demo: pressing "Send code" will generate a code and we store it in session_state.
        if st.sidebar.button("Send 5-digit code", key="send_code"):
            # NOTE: In production you'd send via SMS/Email. Here we generate and show it for testing.
            code = str(uuid.uuid4().int)[:5]
            st.session_state["_5code"] = {"username": code_username, "code": code, "created": datetime.utcnow()}
            st.sidebar.success(f"Code (demo): {code}")
            st.sidebar.info("In production, you'd receive this by SMS/Email.")
        entered_code = st.sidebar.text_input("Enter 5-digit code", key="enter_code")
        if st.sidebar.button("Login with code", key="login_with_code"):
            stored = st.session_state.get("_5code")
            if stored and entered_code and entered_code.strip() == stored.get("code") and stored.get("username") == code_username:
                user = get_user(code_username)
                if not user:
                    # optionally create a minimal user record
                    create_user(code_username, "code-login", code_username, "user")
                    user = get_user(code_username)
                st.session_state["user"] = {"username": code_username, "name": user.get("name", code_username), "role": user.get("role", "user")}
                st.experimental_rerun()
            else:
                st.sidebar.error("Invalid code or username")

    st.stop()  # stops rendering further parts until user logs in

# ---------- Sidebar after login ----------
st.sidebar.title("Surveilai")
try:
    st.sidebar.image("assets/lima.jpg", width=120)
except Exception:
    pass
st.sidebar.markdown("Created by LIMA Group")
st.sidebar.write(f"Signed in as: **{st.session_state['user']['name']}** ({st.session_state['user'].get('role','user')})")
st.sidebar.markdown("---")

# Admin links
if st.session_state["user"]["role"] == "admin":
    st.sidebar.markdown("## Admin")
    if st.sidebar.button("User management", key="admin_users"):
        st.session_state["admin_page"] = "users"
    if st.sidebar.button("Alerts & thresholds", key="admin_alerts"):
        st.session_state["admin_page"] = "alerts"

# Common sidebar actions
if st.sidebar.button("About Surveilai", key="about_button"):
    st.session_state["page"] = "about"
if st.sidebar.button("Logout", key="logout_button"):
    st.session_state["user"] = None
    st.experimental_rerun()

# Download CSV
if st.sidebar.button("Download CSV of cases", key="download_csv"):
    df = st.session_state.get("cases_df", pd.DataFrame())
    if df.empty:
        st.sidebar.warning("No cases to download")
    else:
        csv = df.to_csv(index=False).encode("utf-8")
        st.sidebar.download_button("Download cases.csv", data=csv, file_name="cases.csv", mime="text/csv")

st.sidebar.markdown("---")

# ---------- ABOUT PAGE ----------
if st.session_state.get("page") == "about":
    st.header("About Surveilai")
    st.markdown(
        """
        **Surveilai** — an outbreak surveillance MVP built for rapid situational awareness.

        Features:
        - Simple case reporting (with coordinates, district detection from shapefile)
        - Admin user management
        - Epiweek analytics & epicurve
        - CSV export
        """
    )
    st.stop()

# ---------- MAIN LAYOUT ----------
st.header("Surveilai — District outbreak risk & case reporting")
col1, col2 = st.columns([1, 1])

# ---------------- LEFT: Case reporting ----------------
with col1:
    st.subheader("Report a case")
    # Show quick stats
    df_cases = st.session_state.get("cases_df", pd.DataFrame())
    st.write(f"Total cases recorded: **{len(df_cases)}**")

    with st.form("case_form", clear_on_submit=True):
        # Auto Case ID
        case_id = st.text_input("Case ID (auto)", value=str(uuid.uuid4())[:8], disabled=True)
        entry_date = st.date_input("Date of entry", value=date.today())
        onset_date = st.date_input("Onset / report date", value=date.today())
        name = st.text_input("Patient name (optional)")
        sex = st.selectbox("Sex", ["Unknown", "Male", "Female", "Other"])
        age = st.number_input("Age", min_value=0, max_value=120, value=0)
        reporter = st.selectbox("Reporter", ["Frontline worker", "Community volunteer", "Citizen"], index=0)
        reporter_name = st.text_input("Reporter name (optional)")

        # Location fields
        st.markdown("**Location**")
        use_coords = st.radio("Location input", ["Manual (type/paste)", "Paste coords (lat,lon)"], index=0)
        coords = None
        if use_coords == "Paste coords (lat,lon)":
            coords_text = st.text_input("Paste coordinates as lat,lon (e.g. -1.234,36.78)")
            if coords_text:
                try:
                    lat, lon = coords_text.split(",")
                    coords = (float(lat.strip()), float(lon.strip()))
                except Exception:
                    st.warning("Invalid coords format - expected lat,lon")
        else:
            # manual inputs for region/district/community/town/landmark
            region = st.text_input("Region (optional)")
            district = st.text_input("District (optional)")
            community = st.text_input("Community (optional)")
            town = st.text_input("Town (optional)")
            landmark = st.text_input("Landmark (optional)")

        # Symptoms / lab
        lab_positive = st.selectbox("Lab result", ["Unknown", "Negative", "Positive", "Presumed"], index=0)
        fever = st.checkbox("Fever")
        cough = st.checkbox("Cough")
        rash = st.checkbox("Rash")
        other_symptoms = st.text_area("Other symptoms (comma-separated)")

        submitted = st.form_submit_button("Submit case")
        if submitted:
            # Compose case record dict
            record = {
                "case_id": case_id,
                "entry_date": pd.to_datetime(entry_date),
                "onset_date": pd.to_datetime(onset_date),
                "patient_name": name,
                "sex": sex,
                "age": int(age),
                "reporter_type": reporter,
                "reporter_name": reporter_name,
                "lab_result": lab_positive,
                "fever": bool(fever),
                "cough": bool(cough),
                "rash": bool(rash),
                "other_symptoms": other_symptoms,
                "created_by": st.session_state["user"]["username"],
                "created_at": datetime.utcnow(),
            }

            # attach location info
            if coords:
                record["latitude"] = coords[0]
                record["longitude"] = coords[1]
                # try to detect district if shapefile loaded
                try:
                    gdf = st.session_state.get("shapefile_gdf")
                    if gdf is not None and hasattr(assign_district_from_point, "__call__"):
                        detected = assign_district_from_point(coords, gdf=gdf)
                        if detected:
                            record["district"] = detected
                            st.info(f"Detected district from shapefile: {detected}")
                        else:
                            record["district"] = None
                    else:
                        record["district"] = None
                except Exception as e:
                    record["district"] = None
            else:
                # manual fields fallback (use previously typed ones)
                record["region"] = locals().get("region", "")
                record["district"] = locals().get("district", "")
                record["community"] = locals().get("community", "")
                record["town"] = locals().get("town", "")
                record["landmark"] = locals().get("landmark", "")

            # Persist to DB using add_case if available, else append to session df
            try:
                add_case(record)
                st.success(f"Case {case_id} saved.")
                # refresh session cases
                try:
                    st.session_state["cases_df"] = query_summary()
                except Exception:
                    # append locally if query_summary not available
                    df = st.session_state.get("cases_df", pd.DataFrame())
                    new_row = record.copy()
                    # convert datetimes for CSV friendliness
                    new_row["entry_date"] = pd.to_datetime(new_row["entry_date"])
                    new_row["onset_date"] = pd.to_datetime(new_row["onset_date"])
                    st.session_state["cases_df"] = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            except Exception as e:
                # fallback: local store
                df = st.session_state.get("cases_df", pd.DataFrame())
                new_row = record.copy()
                new_row["entry_date"] = pd.to_datetime(new_row["entry_date"])
                new_row["onset_date"] = pd.to_datetime(new_row["onset_date"])
                st.session_state["cases_df"] = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                st.warning("Saved locally (DB save failed).")

# ---------------- RIGHT: Uploads / Shapefile / Analytics ----------------
with col2:
    st.subheader("Uploads & shapefile")
    shp_zip = st.file_uploader("Upload shapefile .zip (contains .shp/.dbf/.shx)", type=["zip"], key="shapefile_upload")
    if shp_zip:
        try:
            gdf = load_shapefile_from_zip(shp_zip)
            if isinstance(gdf, gpd.GeoDataFrame):
                st.session_state["shapefile_gdf"] = gdf
                st.success("Shapefile loaded into session.")
                st.write("First 5 polygons:")
                st.write(gdf.head())
            else:
                st.warning("shapefile loaded but not returned as GeoDataFrame.")
        except Exception as e:
            st.error(f"Failed to load shapefile: {e}")

    st.subheader("Analytics & dashboard")
    cases_df = st.session_state.get("cases_df", pd.DataFrame())
    if cases_df.empty:
        st.info("No cases recorded yet.")
    else:
        # ensure datetime conversion
        if "onset_date" in cases_df.columns:
            cases_df["onset_date"] = pd.to_datetime(cases_df["onset_date"])
        if "entry_date" in cases_df.columns:
            cases_df["entry_date"] = pd.to_datetime(cases_df["entry_date"])

        # Epiweek calculation (ISO week)
        if "onset_date" in cases_df.columns:
            cases_df["epiweek"] = cases_df["onset_date"].dt.isocalendar().week
            cases_df["year"] = cases_df["onset_date"].dt.isocalendar().year
            cases_df["epiweek_year"] = cases_df["year"].astype(str) + "-W" + cases_df["epiweek"].astype(str)

        st.markdown("### Summary reports")
        # total cases by epiweek
        if "epiweek" in cases_df.columns:
            epi_curve = (
                cases_df.groupby(["year", "epiweek"])
                .size()
                .reset_index(name="cases")
                .sort_values(["year", "epiweek"])
            )
            fig = px.bar(epi_curve, x=epi_curve.apply(lambda r: f"{int(r.year)}-W{int(r.epiweek)}", axis=1), y="cases", labels={"x": "Epiweek", "cases": "Number of cases"}, title="Epicurve (cases per epiweek)")
            st.plotly_chart(fig, use_container_width=True)

        # cases by sex
        if "sex" in cases_df.columns:
            sex_tbl = cases_df["sex"].value_counts().reset_index()
            sex_tbl.columns = ["sex", "count"]
            st.write("Cases by sex")
            st.table(sex_tbl)

        # cases by age group
        if "age" in cases_df.columns:
            bins = [0, 4, 9, 14, 24, 44, 64, 120]
            labels = ["0-4", "5-9", "10-14", "15-24", "25-44", "45-64", "65+"]
            cases_df["age_group"] = pd.cut(cases_df["age"].fillna(0).astype(int), bins=bins, labels=labels, right=True)
            age_tbl = cases_df["age_group"].value_counts().reindex(labels).reset_index()
            age_tbl.columns = ["age_group", "count"]
            st.write("Cases by age group")
            st.table(age_tbl)

        # suspected/probable/confirmed summary (use lab_result column)
        if "lab_result" in cases_df.columns:
            lab_tbl = cases_df["lab_result"].value_counts().reset_index()
            lab_tbl.columns = ["lab_result", "count"]
            st.write("Case classification (lab_result)")
            st.table(lab_tbl)

        # location summary
        loc_cols = [c for c in ["district", "town", "community"] if c in cases_df.columns]
        if loc_cols:
            loc_summary = (
                cases_df
                .groupby(loc_cols)
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
                .head(20)
            )
            st.write("Top locations")
            st.table(loc_summary)

        st.markdown("### Case list (preview)")
        st.dataframe(cases_df.sort_values("entry_date", ascending=False).head(200))

# ---------- ADMIN PAGES ----------
if st.session_state["user"]["role"] == "admin" and st.session_state.get("admin_page") == "users":
    st.header("User management (admin)")
    try:
        users_df = get_all_users()
        st.write("Registered users")
        st.dataframe(users_df)
    except Exception:
        st.info("Could not fetch users via get_all_users(). Ensure utils.get_all_users is implemented.")
        users_df = pd.DataFrame()

    st.subheader("Change user role")
    uname = st.text_input("Username to change role", key="admin_change_username")
    newrole = st.selectbox("New role", ["user", "investigator", "admin"], key="admin_change_role")
    if st.button("Set role", key="admin_set_role"):
        try:
            set_user_role(uname, newrole)
            st.success("Role updated.")
            # refresh users_df
            try:
                users_df = get_all_users()
                st.dataframe(users_df)
            except Exception:
                pass
        except Exception as e:
            st.error(f"Failed to update role: {e}")

if st.session_state["user"]["role"] == "admin" and st.session_state.get("admin_page") == "alerts":
    st.header("Alerts & thresholds / Config editor")
    try:
        cfg_text = open(CONFIG_PATH).read()
    except Exception:
        cfg_text = yaml.dump(config)
    edited = st.text_area("config.yaml", value=cfg_text, height=300, key="config_text")
    if st.button("Save config.yaml", key="save_config"):
        try:
            with open(CONFIG_PATH, "w") as f:
                f.write(edited)
            st.success("Config saved.")
        except Exception as e:
            st.error(f"Failed to save config: {e}")
    if st.button("Reload config", key="reload_config"):
        st.experimental_rerun()

# ---------- FOOTER ----------
st.markdown("---")
st.write("Surveilai — MVP. Created by LIMA Group.")
