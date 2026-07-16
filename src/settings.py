BOT_NAME = "almaweb_lecture_parser"

SPIDER_MODULES = ["src.parser"]
NEWSPIDER_MODULE = "src.parser"

# Be polite: identify ourselves and throttle requests
USER_AGENT = "AlmaWebParser/1.0 (+https://github.com/natureFrameworkManager/almaweb-parser)"
BOT_NAME = "almaweb_lecture_parser"
ROBOTSTXT_OBEY = True

# Throttle to avoid overloading the server
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_TARGET_CONCURRENCY = 16
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
# DOWNLOAD_DELAY = 1
# CONCURRENT_REQUESTS = 10
# CONCURRENT_REQUESTS_PER_DOMAIN = 10

# Disable cookies (we use the anonymous session ID)
COOKIES_ENABLED = False

# Respect HTTP caching
HTTPCACHE_ENABLED = True
HTTPCACHE_DIR = "httpcache"

# Logging
LOG_LEVEL = "INFO"

# Twisted reactor for Windows compatibility
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"

DNS_TIMEOUT = 5
DOWNLOAD_TIMEOUT = 30

# Limit crawled pages
# CLOSESPIDER_PAGECOUNT = 20  # Stop after 10 responses