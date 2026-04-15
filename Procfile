web: python seed_data.py && gunicorn backend.main_v2:app -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
