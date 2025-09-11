import json
import os
import requests
import yaml
import csv
import time
from pathlib import Path
from argparse import ArgumentParser
from requests.auth import HTTPBasicAuth

from ht_full_text_search.config_files import config_files_path
# Add the parent directory ~/ht_full_text_search into the PYTHONPATH.
from ht_full_text_search.config_search import default_catalog_solr_params, FULL_TEXT_SOLR_URL
from ht_full_text_search.utils.ht_logger import get_ht_logger

logger = get_ht_logger(name=__name__)


# This is a quick attempt to do a query to solr more or less as we issue it in
# production and to then export all results using the cursorMark results
# streaming functionality.

# This assumes the 'production' config with all shards available.

# Usage:
#
# poetry run python3 ht_full_text_search/export_all_results.py 'your query string'
#
# If you want to do a phrase query, be sure to surround it in double quotes, e.g.
# poetry run python3 ht_full_text_search/export_all_results.py '"a phrase"'

# TODO: ht_full_text_search should change to become the python library we use for querying our Solr clusters. Right now,
# the code is implemented to run queries only in the full text search cluster. We should have a more generic way to
# query any Solr cluster we have, including the catalog ones.
# We should have a way:
#  to configure the Solr cluster we want to query, the environment, the collection, etc.
#  to configure the fields we want to return in the query results
#  to configure the fields we want to use in the query
#  to configure the fields we want to use in the query to boost the results

# We should have generic classes to Search, make queries, filters, and facets and print the query results.
# We should create specific classes/endpoints (catalog => catalog-api, catalog-monitoring, fulltext => fulltext-api,
# fulltext-monitoring) children of the generic ones that have their own ways to make queries

# TODO: Implement the class to manage Solr query results.
# Specify the fields to show in the query result
# Specify if the Solr debug output will be show.Create our onw debug dictionary with fields we decide,
# e.g. QTime, status, shards, etc.
def process_results(item: dict, list_output_fields: list) -> str:

    """ Prepare the dictionary with Solr results to be exported as JSON
    Args:
        item (dict): The Solr result item.
        list_output_fields (list): List of fields to include in the output.
    Returns:
        str: JSON string of the processed result.
    """
    # logger.info(f"process_results - params : {item} {list_output_fields}")
    result = {field: item.get(field, None) for field in list_output_fields}
    
    return json.dumps(result)





class CatalogSolrExporter:

    def __init__(self, catalog_solr_url:str, env: str, user=None, password=None):

        """ Initialize the SolrExporter class
        :param catalog_solr_url: str, Solr URL
        :param env: str, environment. It could be dev or prod
        """

        # TODO: We should load in memory the query configuration file to avoid reading it each time we run a query.
        # SolrExporter should be re-implemented following the design of ht_query/ht_query.py, ht_search/ht_search.py
        # We should create an exporter as part of this structure and we should create separate classes to manage the
        # Catalog and FullText Solr clusters.
        # url = http://solr-sdr-catalog:9033/solr
        # full_url =  http://solr-sdr-catalog:9033/solr/catalog/

        self.catalog_solr_url = f"{catalog_solr_url}/query"
        self.environment = env
        self.headers = {"Content-Type": "application/json"}
        self.auth = HTTPBasicAuth(user, password) if user and password else None

    def send_query(self, params):

        """ Send the query to Solr
        :param params: dict, query parameters
        :return: response
        """
        # logger.info(f"send_query - params : {params}")
        # Use stream=True to avoid loading all the data in memory at once (useful for large responses)
        # In chunked transfer, the data stream is divided into a series of non-overlapping "chunks".                                 
        response = requests.post(self.catalog_solr_url,data=params)
        # response = requests.post("http://localhost:9033/solr/catalog/select",data=params)
        logger.info(f"response from Cataog Solr API : {response}")
        return response

    def run_cursor(self, query_string, conf_query="ocr", list_output_fields: list = None,fq_formatted=None,file_type=""):

        # TODO: This function will receive the query string and the query type (ocr or all). From memory, it will
        # instantiate the query parameters (params["q"]) and run the query.
        # See below how the params dictionary is created. As the fields about the query are already in memory, we should
        # update the field q in the params dictionary with the query string and run the query.        
        logger.info(f"run_cursor - params : {query_string} {conf_query} {list_output_fields} {fq_formatted} {file_type}")        
        params = dict(default_catalog_solr_params(self.environment))
        logger.info(f"default_solr_params - output : {params}")
       
        # Replace the default list of fields with the one passed as a parameter
        if list_output_fields is not None:
            params["fl"] = ",".join(list_output_fields)
        else:
            list_output_fields = params["fl"].split(",")
        params["cursorMark"] = "*"
        params["debugQuery"] = "true"       
        params.update(query_string)
        
        # params["q"]='(title_ab:(political drama)^25000 OR title_a:(political drama)^15000 OR titleProper:(political drama*)^8000 OR titleProper:("political drama")^1200 OR titleProper:(political AND drama)^120 OR title_topProper:("political drama")^600 OR title_topProper:(political AND drama)^60 OR title_restProper:("political drama")^400 OR title_restProper:(political AND drama)^40 OR series:("political drama")^500 OR series:(political AND drama)^50 OR series2:("political drama")^500 OR series2:(political AND drama)^50 OR title:(political AND drama)^30 OR title_top:(political AND drama)^20 OR title_rest:(political AND drama)^1)'
        # params["fq"]='ht_availability:"Full text"'
    
        if fq_formatted:            
            params["fq"] = fq_formatted

        logger.info(f"Params to Catalog Solr API: {params}")        


        #When we want to check by id's
        # Provide Solr query to match specific ID.
        # NOTE
        # : Special characters like '.' and ':' must be escaped using '\\' to avoid Solr syntax errors.
        # params["q"]= "id:coo\\.31924001840028 OR id:coo\\.31924074225651 OR id:coo1\\.ark\\:/13960/t04x5w53p OR id:coo1\\.ark\\:/13960/t3dz0tz2f OR id:coo1\\.ark\\:/13960/t3fx7ts39 OR id:hvd\\.hb08ny OR id:hvd\\.hb0x5l OR id:hvd\\.hn7v5x OR id:hvd\\.hntxc1 OR id:hvd\\.hw2gvl OR id:mdp\\.39015002663139 OR id:mdp\\.39015010834789 OR id:mdp\\.39015020465244 OR id:mdp\\.39015020815620 OR id:mdp\\.39015027611170 OR id:mdp\\.39015058499875 OR id:mdp\\.39015063039674 OR id:mdp\\.39015064508032 OR id:mdp\\.39015067877996 OR id:njp\\.32101069160594 OR id:uc1\\.\\$b236521 OR id:uc1\\.\\$b237942 OR id:uc1\\.\\$b237943 OR id:uc1\\.\\$b237988 OR id:uc1\\.\\$b238063 OR id:uc1\\.\\$b280885 OR id:uc1\\.\\$b281359 OR id:uc1\\.\\$b666025 OR id:uc1\\.32106016668516 OR id:uc1\\.b3854713 OR id:uc1\\.b3909054 OR id:uc2\\.ark\\:/13960/t9m33077j OR id:ucbk\\.ark\\:/28722/h26m33n41 OR id:ufl\\.31262051116977 OR id:uiug\\.30112064708677"
        # "id:coo\\.31924001840028 OR id:coo\\.31924074225651 OR id:coo1\\.ark\\:/13960/t04x5w53p OR id:coo1\\.ark\\:/13960/t3dz0tz2f OR id:coo1\\.ark\\:/13960/t3fx7ts39 OR id:hvd\\.hb08ny OR id:hvd\\.hb0x5l OR id:hvd\\.hn7v5x OR id:hvd\\.hntxc1 OR id:hvd\\.hw2gvl OR id:mdp\\.39015002663139 OR id:mdp\\.39015010834789 OR id:mdp\\.39015020465244 OR id:mdp\\.39015020815620 OR id:mdp\\.39015027611170 OR id:mdp\\.39015058499875 OR id:mdp\\.39015063039674 OR id:mdp\\.39015064508032 OR id:mdp\\.39015067877996 OR id:njp\\.32101069160594 OR id:uc1\\.\\$b236521 OR id:uc1\\.\\$b237942 OR id:uc1\\.\\$b237943 OR id:uc1\\.\\$b237988 OR id:uc1\\.\\$b238063 OR id:uc1\\.\\$b280885 OR id:uc1\\.\\$b281359 OR id:uc1\\.\\$b666025 OR id:uc1\\.32106016668516 OR id:uc1\\.b3854713 OR id:uc1\\.b3909054 OR id:uc2\\.ark\\:/13960/t9m33077j OR id:ucbk\\.ark\\:/28722/h26m33n41 OR id:ufl\\.31262051116977 OR id:uiug\\.30112064708677"
    


        while True:            
            results = self.send_query(params)  # send_query                  
            output = json.loads(results.content)
            print(len(output['response']['docs']))
            for result in output['response']['docs']:
                response_data = process_results(result, list_output_fields)                                  
                yield response_data                       

            if params["cursorMark"] != output["nextCursorMark"]:
                params["cursorMark"] = output["nextCursorMark"]
            else:
                break

               
