# Almaweb "Vorlesungsverzeichnis" Parser & API
## Setup
1. Clone the repository and open the repo in a terminal
2. Setup a Python virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1
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
## Notes
The crawler currently parses the pages linked from the page of the "SoSe 2026/10 - Fakultät für Mathematik und Informatik".  
To change the starting page, modify the `start_urls` attribute in `src/crawler/spiders/lecture_spider.py` and the url of your desired starting page.  
  
The crawler currently takes 10 minutes to crawl through all the pages and extract the relevant information. This is because it needs to make a lot of requests to the server and parse the HTML of each page.  
Also it currently uses for the extraction of the module and course data a concurrent approach of 4 maximum concurrent requests for module and 8 for course data. The crawler uses the AutoThrottle extension to automatically adjust the crawling speed based on the load of the server. You can adjust the settings in `src/crawler/settings.py` and the concurrent requests in `src/parser/module_parser.py` and `src/parser/course_parser.py`.