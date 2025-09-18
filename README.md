# Surveilai - Streamlit MVP (Outbreak risk dashboard)

This scaffold provides a minimum viable product for the "Surveilai" app described.

## Features included
- User signup & login (SQLite + werkzeug password hashing)
- Case reporting form (demographics, symptoms, reporter, optional coords)
- Simple classification: Suspected / Probable / Confirmed
- Store cases in local SQLite database (`surveilai.db`)
- Upload zipped shapefile (.zip) to enable district polygons display
- Epi curve and simple case counts
- Map with points and DBSCAN-based clusters (epicenters)
- CSV export

## How to run locally
1. Install Python 3.9+.
2. Create venv and activate.
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   Note: geopandas and fiona may require system packages (GDAL). On Ubuntu:
   ```
   sudo apt-get update
   sudo apt-get install -y gdal-bin libgdal-dev
   pip install -r requirements.txt
   ```
4. Initialize DB (creates admin user):
   ```
   python db_init.py
   ```
5. Run Streamlit:
   ```
   streamlit run streamlit_app.py
   ```

## Deploy to Streamlit Cloud (GitHub -> Streamlit)
1. Create a new GitHub repo and push these files.
2. On Streamlit Cloud, connect your GitHub repo and deploy `streamlit_app.py`.
3. Ensure required system libraries for geopandas are available on the cloud. If geopandas causes issues, consider using simpler geo-processing or pre-processing on your local machine and uploading GeoJSON.

## Notes & next steps
- Replace `assets/lima.jpg` with your official logo.
- For production, migrate auth to a managed identity provider (Firebase Auth, Auth0) and DB to Postgres / Firebase.
- To implement district auto-detection from coords, use the uploaded shapefile and a point-in-polygon query with GeoPandas.

## Additional features added in v2
- Configurable `config.yaml` for classification rules and alerts.
- Logo upload via UI (overwrites assets/lima.jpg).
- Auto-assign region/district/community from uploaded shapefile using point-in-polygon.
- Role-based access (user/investigator/admin) and admin pages for user management & alerts.
- Enhanced clustering: time-windowed DBSCAN & temporal outputs.
- Training scaffold for LightGBM district risk model (`train_model.py`).

## Production migration notes
- Postgres migration: use `psycopg2` or `sqlalchemy` to move from SQLite to Postgres. Create equivalent tables and copy data.
- Firebase: consider using Firestore for case storage and Firebase Auth for user management. Export SQLite to CSV and import to Firestore, or implement a sync script.
- Auth0/Firebase Auth: replace local auth with secure provider; update Streamlit app to use OAuth/OpenID Connect and restrict pages by role.
- Scheduled jobs:
  - Use GitHub Actions to run a weekly job to pull latest cases and compute district risk scores, then store results in DB or cloud storage.
  - Alternatively deploy an Airflow DAG or cron job on a server to run scoring notebooks.

## v3 additions
- Admin UI to edit `config.yaml` inside the app (admin only).
- Postgres migration script: `migrate_to_postgres.py` (set DATABASE_URL env var).
- Firebase scaffold: `firebase_integration.py` (requires service account JSON and Google credentials).
- Weekly GitHub Actions workflow: `.github/workflows/weekly_scoring.yml` runs `score_districts.py` and uploads results.
- Scoring script `score_districts.py` and model usage scaffold.

## v4 additions
- WHO-style case definitions added to `config.yaml`.
- Hotspot detection (rolling 7-day) with in-app alerts and hotspot list.
- `notifications.py` for SMTP/Twilio scaffolds.
- Admin UI to configure notification settings and send test email/SMS.
- `.env.template` added for credential placeholders.
