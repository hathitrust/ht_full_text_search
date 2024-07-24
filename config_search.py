import inspect
import os
import sys

current = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parent = os.path.dirname(current)
sys.path.insert(0, parent)

# Full-text search config parameters
SOLR_URL = {
    "prod": "http://localhost:8081/solr/core-1y/query",
    "dev": "http://localhost:8983/solr/core-x/query"  # "http://localhost:64108/solr/#/core-x/", #,
}

FULL_TEXT_SEARCH_SHARDS_X = ','.join([f"http://solr-sdr-search-{i}:8081/solr/core-{i}x" for i in range(1, 12)])
FULL_TEXT_SEARCH_SHARDS_Y = ','.join([f"http://solr-sdr-search-{i}:8081/solr/core-{i}y" for i in range(1, 12)])

current_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.insert(0, current_dir)

QUERY_PARAMETER_CONFIG_FILE = "/".join(
    [current_dir, "config_files/full_text_search/config_query.yaml"]
)
FACET_FILTERS_CONFIG_FILE = "/".join(
    [current_dir, "config_files/full_text_search/config_facet_filters.yaml"]
)
