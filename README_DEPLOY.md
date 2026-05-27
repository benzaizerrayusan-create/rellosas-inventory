Deploying to Render and Railway

This project is ready for deployment. Below are short instructions for Render and Railway (free tiers). Use a managed MySQL database for production — SQLite is not recommended on cloud.

Common setup
- Ensure the repository is on GitHub and push your branch.
- Set the following environment variables on the host (Render or Railway):
  - `DB_TYPE` = `mysql`
  - `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`
  - `FLASK_SECRET` (a long random value)
  - Optional SMTP vars: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`

Files added
- `Procfile` — for gunicorn startup: `web: gunicorn app:app --bind 0.0.0.0:$PORT`
- `requirements.txt` updated with `gunicorn`.
- `manage.py` — helper script to initialize the DB and seed admin.
- `.env.example` — example env vars.

Render (quick)
1. Push the repo to GitHub.
2. Create a Render account and "New Web Service" → connect your GitHub repo.
3. Choose branch and environment (Python runtime detected).
4. Render will use `render.yaml` and `runtime.txt` in the repo.
5. In Render dashboard, under Environment, add the environment variables above.
6. Deploy. After deploy completes, run a one-off shell command in Render dashboard to initialize the DB:

   python manage.py

7. (Optional) Add a managed MySQL instance via Railway or ClearDB and fill `MYSQL_*` with connection details.

Railway (quick)
1. Push the repo to GitHub.
2. Create a Railway project and link the GitHub repo for Deployments.
3. Add a MySQL plugin (or external MySQL) and set the environment variables from its connection string.
4. In Railway deploy settings, ensure the start command uses `gunicorn` or leave Procfile.
5. Deploy and run `python manage.py` as a one-off command to initialize the DB.

Notes
- Use the host dashboard to run `python manage.py` once to create tables and seed admin.
- After deploy, customer portal links will be public at `https://<your-host>/portal/order/<id>?token=<token>` and rider portal at `https://<your-host>/rider/portal/<rider_token>`.
- Rotate tokens or add an admin UI if tokens are compromised.

Render GitHub Actions
- A GitHub Actions workflow is included at `.github/workflows/render-deploy.yml`.
- Add `RENDER_API_KEY` and `RENDER_SERVICE_ID` as GitHub repository secrets to trigger Render deploys on push to `master`.

If you want, I can prepare a `render.yaml` for automatic Render setup or a step-by-step Railway guide specific to your account.
