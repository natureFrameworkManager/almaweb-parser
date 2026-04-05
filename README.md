# Almaweb "Vorlesungsverzeichnis" Parser & API
## Setup
1. Clone the repository and open the repo in a terminal
2. Setup a Python virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run crawler to find all modules, courses and events and store them in the database:  
This takes a while, as it needs to crawl through all the pages of the "Vorlesungsverzeichnis" and extract the relevant information.
   ```bash
   scrapy crawl lecture_spider
   ```
5. Start the API server:
   ```bash
   fastapi dev src/api/main.py
   ```
## API Documentation
Once the server is running, you can access the interactive API documentation at `http://localhost:8000/docs`.