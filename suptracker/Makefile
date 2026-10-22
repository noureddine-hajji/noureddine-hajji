.PHONY: install data verify serve test docker
install: ; pip install -r requirements.txt
data: ; python -m suptracker.ingest && python -m suptracker.build
verify: ; python scripts/verify_ground_truth.py --live 25 --strict
serve: ; uvicorn suptracker.api:app --host 0.0.0.0 --port $${PORT:-8000}
test: ; python -m pytest -q
docker: ; docker build -t suptracker-sies . && docker run --rm -p 8000:8000 -v suptracker-data:/data suptracker-sies
refresh: ; python -m suptracker.ingest --force && python -m suptracker.build
