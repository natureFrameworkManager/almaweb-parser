import signal
from threading import Event
from typing import Any

import scrapy
from scrapy.http import Response
from src.database.database import create_db_and_tables

class TreeNode:
    def __init__(self, name, parent=None):
        self.name = name
        self.children = []
        self.parent = parent

    def add_child(self, child_node):
        self.children.append(child_node)
    
    def getPath(self):
        path = []
        node = self
        while node:
            path.append(node.name)
            node = node.parent
        return list(reversed(path))
class ModuleLink():
    def __init__(self, name, url, path):
        self.name = name
        self.url = url
        self.path = path
    def tostring(self):
        return f"{self.name} (Path: {' > '.join(self.path)})"

from .module_parser import handleModuleList
class LectureSpider(scrapy.Spider):
    name = "lecture_spider"
    start_urls = [
        "https://almaweb.uni-leipzig.de/scripts/mgrqispi.dll?APPNAME=CampusNet&PRGNAME=ACTION&ARGUMENTS=-AlRW1lJ7lEvlq1bJQaAgjNEoc7vcO5zFz0B~Zb5dZYR0Zp0w1ooM5YOTdd71WTwtfKY7If6lHLVqnj8cOibo582kdF0~khXvOSn8194IYKybtU7nB2jhM3oMQjf6MFQk5vR2aFRVwgZghYk2qUx1KFj~pewVTVSYKMVtfVnnFKsWVxqFItbrJQJ6vpXVv5g2TcLXKa3FUqjRjAPg_"
        # "https://almaweb.uni-leipzig.de/scripts/mgrqispi.dll?APPNAME=CampusNet&PRGNAME=ACTION&ARGUMENTS=-AukXTJvXHp6VtynaLEXA7YoOnZYiFw1hBKp~IhHHOJ0Fr8jK0j~gQ3Yrlx7TIlvwcSOd-Bx1qknvSqqYxTOycZUbUetCGPSJVaotazcgsv6Gswzl1FYRuihwZ96IppD5Jfp0m9bp1zmiuUQV-LKlgugpuNT-cLv01iTNyKTLD6KkN~-RdxKGujfLrRQ__"
    ]
    root_node = TreeNode("Root")
    found_modules = []

    def __init__(self, name: str | None = None, **kwargs: Any):
        super().__init__(name, **kwargs)
        create_db_and_tables()

    def parse(self, response: Response, parent_node: TreeNode|None = None):
        if parent_node is None:
            parent_node = self.root_node

        navigationNodes = response.css('a.auditRegNodeLink')
        moduleNodes = [x for x in response.css("a[name='eventLink']") if "MODULEDETAILS" in x.attrib.get("href", "")]

        for anchor in navigationNodes:
            text = anchor.css("::text").get()
            if not text:
                continue
            name = text.strip()
            url = anchor.attrib.get("href")
            if not url:
                continue
            child_node = TreeNode(name, parent=parent_node)
            parent_node.add_child(child_node)

            yield response.follow(url, callback=self.parse, cb_kwargs={"parent_node": child_node})
        for anchor in moduleNodes:
            text = anchor.css("::text").get()
            if not text:
                continue
            name = text.strip()
            url = anchor.attrib.get("href")
            if not url:
                continue
            if not url.startswith("http"):
                url = response.urljoin(url)
            module_link = ModuleLink(name, url, parent_node.getPath())
            self.found_modules.append(module_link)
    
    def closed(self, reason):
        print("Crawling finished.")
        if reason in {"shutdown", "cancelled"}:
            print("Parsing cancelled. Skipping module parsing.")
            return
        cancel_event = Event()
        previous_sigint_handler = signal.getsignal(signal.SIGINT)

        def _request_cancel(signum, frame):
            cancel_event.set()
            print("Cancellation requested. Stopping parsing after running tasks finish.")

        try:
            signal.signal(signal.SIGINT, _request_cancel)
            handleModuleList(self.found_modules, cancel_event=cancel_event)
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)

    def tree_to_dict(self, node):
        return {
            "name": node.name,
            "children": [self.tree_to_dict(child) for child in node.children]
        }