import inspect
import os
import sys
from ht_full_text_search.utils.ht_logger import get_ht_logger

logger = get_ht_logger(name=__name__)

current_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.insert(0, current_dir)

# Full-text search config parameters
FULL_TEXT_SOLR_URL = {
    "prod": "http://macc-ht-solr-lss-1.umdl.umich.edu:8081/solr/core-1x",
    "dev": "http://solr-lss-dev:8983/solr/core-x"
}

CATALOG_SOLR_URL = {
    "dev": "http://localhost:8983"
}

FULL_TEXT_SEARCH_SHARDS_X = ','.join([f"http://solr-sdr-search-{i}:8081/solr/core-{i}x" for i in range(1, 12)])
FULL_TEXT_SEARCH_SHARDS_Y = ','.join([f"http://solr-sdr-search-{i}:8081/solr/core-{i}y" for i in range(1, 12)])

QUERY_PARAMETER_CONFIG_FILE = os.path.join(current_dir, "config_files", "full_text_search", "config_query.yaml")
FACET_FILTERS_CONFIG_FILE = os.path.join(current_dir, "config_files", "full_text_search", "config_facet_filters.yaml")

DEFAULT_SOLR_PARAMS = {
    "rows": 500,
    "sort": "id asc",
    "fl": ",".join(["title", "author", "id", "shard", "score"]),
    # "fl": ",".join([ "id" ]),
    "wt": "json"
}


def default_solr_params(env: str = "prod",is_full_text: bool = True):
    # TODO: Add shards is only for prod environment and full-text search, then I have to change this function to
    # ensure we have access to Catalog in prod environment.
    """
    Return the default solr parameters
    :param env:
    :return:
    """
    logger.info(f"default_solr_params - params : {env}")
    if env == "prod" and is_full_text:
        add_shards(DEFAULT_SOLR_PARAMS)
    return DEFAULT_SOLR_PARAMS


def add_shards(params: dict):
    """
    Add shards to the params
    :param params:
    :return:
    """
    params.update({"shards": FULL_TEXT_SEARCH_SHARDS_X})
    return params
