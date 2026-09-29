"""Import Netscape bookmarks as data; never execute the supplied HTML."""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


class Bookmarks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"id": "root", "name": "收藏夹", "children": []}
        self.stack = [self.root]
        self.pending = None
        self.capture = None
        self.serial = 0
        self.rejected = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag in ("h3", "a"):
            self.capture = {"tag": tag, "attrs": attr, "text": []}
        elif tag == "dl":
            self.stack.append(self.pending or self.stack[-1])
            self.pending = None

    def handle_data(self, data):
        if self.capture:
            self.capture["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "dl" and len(self.stack) > 1:
            self.stack.pop()
        if not self.capture or tag != self.capture["tag"]:
            return
        item = self.capture
        self.capture = None
        name = "".join(item["text"]).strip()
        self.serial += 1
        if tag == "h3":
            folder = {"id": f"folder-{self.serial}", "name": name, "children": []}
            self.stack[-1]["children"].append(folder)
            self.pending = folder
        else:
            url = item["attrs"].get("href", "")
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                self.rejected.append({"name": name, "reason": "非网页链接"})
                return
            query = parse_qs(parts.query)
            if parts.hostname == "search.weixin.qq.com" and ("exportkey" in query or "pass_ticket" in query):
                self.stack[-1]["children"].append({"id": f"bookmark-{self.serial}", "name": name, "entry": "在微信中搜索“微信指数”小程序", "note": "原收藏为临时微信跳转，使用应用内入口"})
                return
            if parts.username or parts.password or any(re.search(r"(^|_)(token|secret|password|authkey|api_key|access_token|pass_ticket|exportkey)(_|$)", key, re.I) for key in query):
                self.rejected.append({"name": name, "reason": "链接包含凭证字段"})
                return
            bookmark = {"id": f"bookmark-{self.serial}", "name": name or parts.hostname, "url": url}
            icon = item["attrs"].get("icon", "")
            if re.fullmatch(r"data:image/(png|jpeg|x-icon);base64,[A-Za-z0-9+/=]+", icon):
                bookmark["icon"] = icon
            self.stack[-1]["children"].append(bookmark)


source = Path(sys.argv[1])
target = Path(sys.argv[2])
parser = Bookmarks()
parser.feed(source.read_text(encoding="utf-8-sig"))
data = {"source": source.name, "folders": parser.root["children"], "excluded": parser.rejected}
target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize(nodes, depth=0):
    total = 0
    for node in nodes:
        if "children" in node:
            count = summarize(node["children"], depth + 1)
            print(f"{'  '*depth}{node['name']}: {count}")
            total += count
        else:
            total += 1
    return total


print("Total:", summarize(data["folders"]))
print("Excluded:", len(parser.rejected))
for item in parser.rejected:
    print(item)
