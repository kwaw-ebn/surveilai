
import sqlite3, os, io, zipfile, yaml
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import numpy as np
from sklearn.cluster import DBSCAN

DB = os.path.join(os.path.dirname(__file__), "surveilai.db")
CONFIG = os.path.join(os.path.dirname(__file__), "config.yaml")

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT,
                name TEXT,
                role TEXT DEFAULT 'user'
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                name TEXT,
                sex TEXT,
                age INTEGER,
                reporter TEXT,
                region TEXT,
                district TEXT,
                community TEXT,
                onset_date TEXT,
                lab_positive INTEGER,
                symptoms TEXT,
                classification TEXT,
                coords TEXT
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS thresholds (
                name TEXT PRIMARY KEY,
                value REAL
                )""")
    conn.commit()
    conn.close()
    # ensure config file exists
    if not os.path.exists(CONFIG):
        default = {
            'classification_rules': {
                'confirmed': {'lab_positive': True},
                'probable': {'symptoms_required': ['fever','cough'], 'epidemiological_link_required': False},
                'suspected': {}
            },
            'alerts': {
                'recent_days': 7,
                'high_activity_threshold': 10
            }
        }
        with open(CONFIG,'w') as f:
            yaml.dump(default, f)

def create_user(username, password, name, role='user'):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        hashed = generate_password_hash(password)
        c.execute("INSERT INTO users (username,password,name,role) VALUES (?, ?, ?, ?)", (username, hashed, name, role))
        conn.commit()
        return True, "Account created. Please login."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def get_user(username):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT username,password,name,role FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"username": row[0], "password": row[1], "name": row[2], "role": row[3]}
    return None

def get_all_users():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT username,name,role FROM users", conn)
    conn.close()
    return df

def set_user_role(username, role):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET role=? WHERE username=?", (role, username))
    conn.commit()
    conn.close()

def check_password(password, hashed):
    return check_password_hash(hashed, password)

def add_case(entry):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""INSERT INTO cases (case_id,name,sex,age,reporter,region,district,community,onset_date,lab_positive,symptoms,classification,coords)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (entry.get('case_id'), entry.get('name'), entry.get('sex'), entry.get('age'), entry.get('reporter'),
               entry.get('region'), entry.get('district'), entry.get('community'), entry.get('onset_date'),
               entry.get('lab_positive'), entry.get('symptoms'), entry.get('classification'), entry.get('coords')))
    conn.commit()
    conn.close()

def query_summary():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT * FROM cases", conn)
    conn.close()
    if 'onset_date' in df.columns:
        try:
            df['onset_date'] = pd.to_datetime(df['onset_date'])
        except:
            pass
    return df

def load_shapefile_from_zip(zipped_file):
    # zipped_file is a UploadedFile
    bytes_data = zipped_file.read()
    z = zipfile.ZipFile(io.BytesIO(bytes_data))
    tmpdir = os.path.join(os.path.dirname(__file__), "tmp_shp")
    if os.path.exists(tmpdir):
        import shutil
        shutil.rmtree(tmpdir)
    os.makedirs(tmpdir, exist_ok=True)
    z.extractall(tmpdir)
    shp = None
    for root,_,files in os.walk(tmpdir):
        for f in files:
            if f.endswith(".shp"):
                shp = os.path.join(root, f)
                break
    if not shp:
        raise ValueError("No .shp file found in zip")
    gdf = gpd.read_file(shp)
    # ensure consistent crs
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    else:
        gdf = gdf.to_crs(epsg=4326)
    return gdf

def assign_district_from_point(lat, lon, gdf):
    # returns metadata dict with region/district/community if found
    pt = Point(lon, lat)
    # ensure same crs
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    else:
        gdf = gdf.to_crs(epsg=4326)
    matches = gdf[gdf.contains(pt)]
    if matches.empty:
        return {}
    # pick first match and try common fields
    r = matches.iloc[0]
    out = {}
    for candidate in ['district','District','NAME_2','ADM2_NAME','ADM1_NAME','region','Region']:
        if candidate in r.index:
            out['district'] = r[candidate]
            break
    for candidate in ['region','Region','ADM1_NAME','NAME_1']:
        if candidate in r.index:
            out['region'] = r[candidate]
            break
    for candidate in ['community','COMMUNITY','NAME_3']:
        if candidate in r.index:
            out['community'] = r[candidate]
            break
    return out

def cluster_epicenters(df_coords, eps_meters=2000, min_samples=3, time_window_days=None):
    # df_coords: DataFrame with lat,lon and optional onset_date
    if df_coords.shape[0] < 3:
        return []
    coords_df = df_coords.copy()
    # filter by time window if provided
    if time_window_days is not None and 'onset_date' in coords_df.columns:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=int(time_window_days))
        coords_df = coords_df[coords_df['onset_date'] >= cutoff]
        if coords_df.shape[0] < 3:
            return []
    # convert degrees to radians for haversine DBSCAN
    coords = np.radians(coords_df[['lat','lon']].values)
    kms_per_radian = 6371.0088
    epsilon = eps_meters/1000.0 / kms_per_radian
    clustering = DBSCAN(eps=epsilon, min_samples=min_samples, metric='haversine').fit(coords)
    labels = clustering.labels_
    clusters = []
    for lbl in set(labels):
        if lbl == -1:
            continue
        members = coords_df[labels==lbl]
        # temporal weighting: compute mean date as timestamp and convert to iso
        mean_date = None
        if 'onset_date' in members.columns:
            try:
                mean_date = pd.to_datetime(members['onset_date']).mean()
            except:
                mean_date = None
        clusters.append({'lat': float(members['lat'].mean()), 'lon': float(members['lon'].mean()),
                         'count': int(len(members)), 'mean_date': str(mean_date)})
    return clusters


def classify_case(entry, config_rules=None):
    """
    Classify a case based on config rules dict.
    Expected config_rules structure (example):
    {
      'confirmed': {'lab_positive': True},
      'probable': {'symptoms_required': ['fever','cough'], 'epi_link_required': False},
      'suspected': {}
    }
    Entry keys: lab_positive (int/bool), symptoms (string semicolon or comma separated), epi_link (bool, optional)
    """
    if config_rules is None:
        # fallback: basic rules
        if entry.get('lab_positive'):
            return "Confirmed"
        if 'fever' in (entry.get('symptoms') or "").lower() and 'cough' in (entry.get('symptoms') or "").lower():
            return "Probable"
        return "Suspected"
    # Confirmed
    conf = config_rules.get('confirmed', {})
    if conf.get('lab_positive') and entry.get('lab_positive'):
        return "Confirmed"
    # Probable
    prob = config_rules.get('probable', {})
    symptoms_required = [s.lower() for s in prob.get('symptoms_required', [])]
    symptoms_present = [s.strip().lower() for s in (entry.get('symptoms') or "").replace(';',',').split(',') if s.strip()]
    if symptoms_required:
        if all(s in symptoms_present for s in symptoms_required):
            # check epi link if required
            if prob.get('epi_link_required'):
                if entry.get('epi_link'):
                    return "Probable"
            else:
                return "Probable"
    # default
    return "Suspected"
