"""Rebuild the catalog snapshot shipped with the package."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from uex_market import catalog
data = catalog.build(pause=0.25)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "uex_market", "data", "catalog.json.gz")
catalog.save(data, out)
print(len(data["items"]), "items,", len(data["categories"]), "categories ->", out)
