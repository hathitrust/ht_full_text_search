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
from ht_full_text_search.config_search import default_solr_params, FULL_TEXT_SOLR_URL
from ht_full_text_search.utils.helpers import build_joined_query
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


def solr_query_params(query_config_file=None, conf_query="ocr"):

    """ Prepare the Solr query parameters
    :param query_config_file: str, path to the config file with the queries
    :param conf_query: str, query configuration name. Each query has a name to identify it.
    :return: str, formatted Solr query parameters
    """
    logger.info(f"solr_query_params - params : {query_config_file} {conf_query}")
    if isinstance(conf_query,str):
        conf_query = [conf_query]
    params = {}
    mm = []
    tie = []
    pf = []
    qf = []
    for query in conf_query:
        with open(query_config_file, "r") as file:
            data = yaml.safe_load(file)[query]

            mm.append(data["mm"])
            tie.append(data["tie"])
            

            if "pf" in data:
                pf.append(SolrExporter.create_boost_phrase_fields(data["pf"]))
            if "qf" in data:
                qf.append(SolrExporter.create_boost_phrase_fields(data["qf"]))


    params = {
        "mm" : mm[0],
        "tie" : tie[0],
        "pf": " ".join(pf),
        "qf": " ".join(qf),
    }

    return " ".join([f"{k}='{v}'" for k, v in params.items()])


def make_query(query, query_config_file=None, conf_query="ocr"):

    """ Prepare the Solr query string
        :param conf_query:
        :param query_config_file:
        :param query: str, query string
        :return: str, formatted Solr query string
    """
    logger.info(f"make_query - params : {query} {query_config_file} {conf_query}")
    return f"{{!edismax {solr_query_params(query_config_file=query_config_file, conf_query=conf_query)}}} {query}"




class SolrExporter:

    def __init__(self, ft_solr_url: str, env: str, user=None, password=None):

        """ Initialize the SolrExporter class
        :param solr_url: str, Solr URL
        :param env: str, environment. It could be dev or prod
        """

        # TODO: We should load in memory the query configuration file to avoid reading it each time we run a query.
        # SolrExporter should be re-implemented following the design of ht_query/ht_query.py, ht_search/ht_search.py
        # We should create an exporter as part of this structure and we should create separate classes to manage the
        # Catalog and FullText Solr clusters.
        # url = http://solr-sdr-catalog:9033/solr
        # full_url =  http://solr-sdr-catalog:9033/solr/catalog/

        self.ft_solr_url = f"{ft_solr_url}/query"        
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
                          
        response = requests.post(
                url=self.ft_solr_url, params=params, headers=self.headers, stream=True,
                auth=self.auth
            )        

        return response

    def run_cursor(self, query_string, field_operators, query_config_path=None, conf_query="ocr", list_output_fields: list = None,fq_formatted=None,file_type=""):

        # TODO: This function will receive the query string and the query type (ocr or all). From memory, it will
        # instantiate the query parameters (params["q"]) and run the query.
        # See below how the params dictionary is created. As the fields about the query are already in memory, we should
        # update the field q in the params dictionary with the query string and run the query.

        """ Run the cursor to export all results

        params = {'cursorMark': '*',
        'debugQuery': 'true',
        'fl': 'title,author,id,shard,score',
        'q': "{!edismax mm='100%' tie='0.9' qf='title^500000'} health",
        'rows': 500,
        'sort': 'id asc',
        'wt': 'json'}

        The cursorMark parameter is used to keep track of the current position in the result set.
        :param list_output_fields:
        :param conf_query:
        :param query_config_path:
        :param query_string: Str, query string
        :return: generator
        """
        logger.info(f"run_cursor - params : {query_string} {query_config_path} {conf_query} {list_output_fields} {fq_formatted} {file_type}")

        params = dict(default_solr_params(self.environment))
        logger.info(f"default_solr_params - output : {params}")
       
        # print(params,end="\n")
        # Replace the default list of fields with the one passed as a parameter
        if list_output_fields is not None:
            params["fl"] = ",".join(list_output_fields)
        else:
            list_output_fields = params["fl"].split(",")
        params["cursorMark"] = "*"        
        params["debugQuery"] = "true"                
        
        queries = []
        for i, val in enumerate(conf_query):            
            q = make_query(query_string[i], query_config_path, conf_query=conf_query[i])
             # Escape quotes inside q, otherwise _query_:"..." breaks
            q_safe = q.replace("\\", "\\\\").replace('"', '\\"')
            queries.append(f"_query_:\"{q_safe}\"")
        
        # params["q"] = " AND ".join(queries)
        params["q"] = build_joined_query(queries, field_operators)
        
        # params["q"]='(title_ab:(political drama)^25000 OR title_a:(political drama)^15000 OR titleProper:(political drama*)^8000 OR titleProper:("political drama")^1200 OR titleProper:(political AND drama)^120 OR title_topProper:("political drama")^600 OR title_topProper:(political AND drama)^60 OR title_restProper:("political drama")^400 OR title_restProper:(political AND drama)^40 OR series:("political drama")^500 OR series:(political AND drama)^50 OR series2:("political drama")^500 OR series2:(political AND drama)^50 OR title:(political AND drama)^30 OR title_top:(political AND drama)^20 OR title_rest:(political AND drama)^1)'
        # params["fq"]='ht_availability:"Full text"'

        # {'rows': 500, 'sort': 'id asc', 'fl': 'title,author,id,shard,score', 'wt': 'json', 
        #  'shards': 'http://solr-sdr-search-1:8081/solr/core-1x,http://solr-sdr-search-2:8081/solr/core-2x,http://solr-sdr-search-3:8081/solr/core-3x,http://solr-sdr-search-4:8081/solr/core-4x,http://solr-sdr-search-5:8081/solr/core-5x,http://solr-sdr-search-6:8081/solr/core-6x,http://solr-sdr-search-7:8081/solr/core-7x,http://solr-sdr-search-8:8081/solr/core-8x,http://solr-sdr-search-9:8081/solr/core-9x,http://solr-sdr-search-10:8081/solr/core-10x,http://solr-sdr-search-11:8081/solr/core-11x', 
        #  'cursorMark': '*', 'debugQuery': 'true', 
        #  'q': '(title_ab:(political drama)^25000 OR title_a:(political drama)^15000 OR titleProper:(political drama*)^8000 OR titleProper:("political drama")^1200 OR titleProper:(political AND drama)^120 OR title_topProper:("political drama")^600 OR title_topProper:(political AND drama)^60 OR title_restProper:("political drama")^400 OR title_restProper:(political AND drama)^40 OR series:("political drama")^500 OR series:(political AND drama)^50 OR series2:("political drama")^500 OR series2:(political AND drama)^50 OR title:(political AND drama)^30 OR title_top:(political AND drama)^20 OR title_rest:(political AND drama)^1)'}

        # logger.info(f'make_query - output : {params["q"]}')
        if fq_formatted:            
            params["fq"] = fq_formatted

        print("print the query:1 ", params)
#         params["q"]="""{!edismax qf='titleProper^120 title_topProper^60 title_restProper^40 series^50 series2^50 title^30 title_top^20 title_rest^10 ' 
#  pf='title_ab^25000 title_a^15000 titleProper^1200 title_topProper^600 title_restProper^400 series^300 series2^300 ' 
#  mm='100%' tie='0.1' } dictionary new ships"""
        
        # params["q"] = """{!edismax mm='100%' tie='0.1' pf='author^25000 author2^20000 author_top^5000 author_rest^1000 title_ab^25000 title_a^15000 titleProper^1200 title_topProper^600 title_restProper^400 series^300 series2^300' qf='author^100 titleProper^120 title_topProper^60 title_restProper^40 series^50 series2^50 title^30 title_top^20 title_rest^10'} (title:Economic AND Theory) AND (author:Keynes)"""
                        #   !edismax mm='100%' tie='0.1' pf='author^25000 author2^20000 author_top^5000 author_rest^1000 title_ab^25000 title_a^15000 titleProper^1200 title_topProper^600 title_restProper^400 series^300 series2^300' qf='author^100 titleProper^120 title_topProper^60 title_restProper^40 series^50 series2^50 title^30 title_top^20 title_rest^10'} (author:keynes) OR (title:Economic AND Theory)
        # {!edismax mm='100%' tie='0.1' pf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1' qf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1'} (subject:Cultural AND Memory)
        # {!edismax mm='100%' tie='0.1' pf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1' qf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1'} Cultural AND Memory
        
        # print(params, end="\n")


        #When we want to check by id's
        # Provide Solr query to match specific ID.
        # NOTE
        # : Special characters like '.' and ':' must be escaped using '\\' to avoid Solr syntax errors.
        # params["q"]= "id:coo\\.31924001840028 OR id:coo\\.31924074225651 OR id:coo1\\.ark\\:/13960/t04x5w53p OR id:coo1\\.ark\\:/13960/t3dz0tz2f OR id:coo1\\.ark\\:/13960/t3fx7ts39 OR id:hvd\\.hb08ny OR id:hvd\\.hb0x5l OR id:hvd\\.hn7v5x OR id:hvd\\.hntxc1 OR id:hvd\\.hw2gvl OR id:mdp\\.39015002663139 OR id:mdp\\.39015010834789 OR id:mdp\\.39015020465244 OR id:mdp\\.39015020815620 OR id:mdp\\.39015027611170 OR id:mdp\\.39015058499875 OR id:mdp\\.39015063039674 OR id:mdp\\.39015064508032 OR id:mdp\\.39015067877996 OR id:njp\\.32101069160594 OR id:uc1\\.\\$b236521 OR id:uc1\\.\\$b237942 OR id:uc1\\.\\$b237943 OR id:uc1\\.\\$b237988 OR id:uc1\\.\\$b238063 OR id:uc1\\.\\$b280885 OR id:uc1\\.\\$b281359 OR id:uc1\\.\\$b666025 OR id:uc1\\.32106016668516 OR id:uc1\\.b3854713 OR id:uc1\\.b3909054 OR id:uc2\\.ark\\:/13960/t9m33077j OR id:ucbk\\.ark\\:/28722/h26m33n41 OR id:ufl\\.31262051116977 OR id:uiug\\.30112064708677"
        # "id:coo\\.31924001840028 OR id:coo\\.31924074225651 OR id:coo1\\.ark\\:/13960/t04x5w53p OR id:coo1\\.ark\\:/13960/t3dz0tz2f OR id:coo1\\.ark\\:/13960/t3fx7ts39 OR id:hvd\\.hb08ny OR id:hvd\\.hb0x5l OR id:hvd\\.hn7v5x OR id:hvd\\.hntxc1 OR id:hvd\\.hw2gvl OR id:mdp\\.39015002663139 OR id:mdp\\.39015010834789 OR id:mdp\\.39015020465244 OR id:mdp\\.39015020815620 OR id:mdp\\.39015027611170 OR id:mdp\\.39015058499875 OR id:mdp\\.39015063039674 OR id:mdp\\.39015064508032 OR id:mdp\\.39015067877996 OR id:njp\\.32101069160594 OR id:uc1\\.\\$b236521 OR id:uc1\\.\\$b237942 OR id:uc1\\.\\$b237943 OR id:uc1\\.\\$b237988 OR id:uc1\\.\\$b238063 OR id:uc1\\.\\$b280885 OR id:uc1\\.\\$b281359 OR id:uc1\\.\\$b666025 OR id:uc1\\.32106016668516 OR id:uc1\\.b3854713 OR id:uc1\\.b3909054 OR id:uc2\\.ark\\:/13960/t9m33077j OR id:ucbk\\.ark\\:/28722/h26m33n41 OR id:ufl\\.31262051116977 OR id:uiug\\.30112064708677"
        # params["q"] = "id:hvd\\.32044080083926"   
        
        # params["q"] = "id:loc\\.ark\\:/13960/t6ww7jd9g OR id:nyp\\.33433081903647 OR id:loc\\.ark\\:/13960/t3zs2wm38 OR id:hvd\\.hn5kja OR id:loc\\.ark\\:/13960/t3pv6wc2c OR id:coo1\\.ark\\:/13960/t83j41m0f OR id:wu\\.89099964868 OR id:hvd\\.32044018961201 OR id:mdp\\.39015035314320 OR id:wu\\.89054772421 OR id:hvd\\.hn1yy7"
        # params["q"] = "id:uc1\\.31822029010808 OR id:coo\\.31924071616928"
        
        
        while True:            
            results = self.send_query(params)  # send_query            
            # print("Printing result.content: ", results.content)            
            output = json.loads(results.content)
            # print("printing output", output, len(output))
            print(len(output['response']['docs']))
            # import pdb;pdb.set_trace()
            for result in output['response']['docs']:
                response_data = process_results(result, list_output_fields)                                  
                yield response_data                       

            if params["cursorMark"] != output["nextCursorMark"]:
                params["cursorMark"] = output["nextCursorMark"]
            else:
                break

               

    
    @staticmethod
    def create_boost_phrase_fields(query_fields):

        """ Create the boost phrase fields
        :param query_fields: list, list of field
        :return: str, formatted boost phrase fields
        """

        # phrase fields ==> Once the list of matching documents has been identified using the fq and qf parameters,
        # the pf parameter can be used to "boost" the score of documents in cases where all the terms
        # in the q parameter appear in close proximity.
        formatted_boosts = ["^".join(map(str, field)) for field in query_fields]
        return " ".join(formatted_boosts)

    def get_solr_status(self):

        """ Get the Solr status
        :return: response
        """
        response = requests.get(self.ft_solr_url, auth=self.auth)
        return response


if __name__ == "__main__":

    parser = ArgumentParser()
    parser.add_argument("--env", default=os.environ.get("HT_ENVIRONMENT", "dev"))
    parser.add_argument("--solr_host", help="Solr host", default=None)
    parser.add_argument("--collection_name", help="Name of the collection", default=None)
    parser.add_argument('--query', help='Query string', required=True)

    args = parser.parse_args()

    # Receive as a parameter an specific solr url
    if args.solr_host:
        solr_url = f"{args.solr_host}/solr/{args.collection_name}"
    else:  # Use the default solr url, depending on the environment. If prod environment, use shards
        solr_url = FULL_TEXT_SOLR_URL[args.env]
    solr_exporter = SolrExporter(solr_url, args.env,
                                 user=os.getenv("SOLR_USER"), password=os.getenv("SOLR_PASSWORD"))

    query_config_file_path = Path(
        config_files_path, "full_text_search/config_query.yaml"
    )
    

    # '"good"'
    # for x in solr_exporter.run_cursor(args.query, query_config_path=query_config_file_path, conf_query="ocr"):
    #     print(x)
