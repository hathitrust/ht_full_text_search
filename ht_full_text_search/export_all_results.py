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

    result = {field: item.get(field, None) for field in list_output_fields}
    
    return json.dumps(result)


def solr_query_params(query_config_file=None, conf_query="ocr"):

    """ Prepare the Solr query parameters
    :param query_config_file: str, path to the config file with the queries
    :param conf_query: str, query configuration name. Each query has a name to identify it.
    :return: str, formatted Solr query parameters
    """
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

    # import pdb;pdb.set_trace()

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
    return f"{{!edismax {solr_query_params(query_config_file=query_config_file, conf_query=conf_query)}}} {query}"


class SolrExporter:

    def __init__(self, solr_url: str, env: str, user=None, password=None):

        """ Initialize the SolrExporter class
        :param solr_url: str, Solr URL
        :param env: str, environment. It could be dev or prod
        """

        # TODO: We should load in memory the query configuration file to avoid reading it each time we run a query.
        # SolrExporter should be re-implemented following the design of ht_query/ht_query.py, ht_search/ht_search.py
        # We should create an exporter as part of this structure and we should create separate classes to manage the
        # Catalog and FullText Solr clusters.
        self.solr_url = f"{solr_url}/query"
        self.environment = env
        self.headers = {"Content-Type": "application/json"}
        self.auth = HTTPBasicAuth(user, password) if user and password else None

    def send_query(self, params):

        """ Send the query to Solr
        :param params: dict, query parameters
        :return: response
        """

        # Use stream=True to avoid loading all the data in memory at once (useful for large responses)
        # In chunked transfer, the data stream is divided into a series of non-overlapping "chunks".

        response = requests.post(
            url=self.solr_url, params=params, headers=self.headers, stream=True,
            auth=self.auth
        )

        return response

    def run_cursor(self, query_string, query_config_path=None, conf_query="ocr", list_output_fields: list = None):

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

        params = default_solr_params(self.environment)
        # print(params,end="\n")
        # Replace the default list of fields with the one passed as a parameter
        if list_output_fields is not None:
            params["fl"] = ",".join(list_output_fields)
        else:
            list_output_fields = params["fl"].split(",")
        params["cursorMark"] = "*"
        # TODO: Implement the feature to access to Solr debug using this python script
        params["debugQuery"] = "true"
        # print(params, end="\n")
        params["q"] = make_query(query_string, query_config_path, conf_query=conf_query)
        print("print the query:1 ", params["q"])
        # params["q"] = """{!edismax mm='100%' tie='0.1' pf='author^25000 author2^20000 author_top^5000 author_rest^1000 title_ab^25000 title_a^15000 titleProper^1200 title_topProper^600 title_restProper^400 series^300 series2^300' qf='author^100 titleProper^120 title_topProper^60 title_restProper^40 series^50 series2^50 title^30 title_top^20 title_rest^10'} (title:Economic AND Theory) AND (author:Keynes)"""
                        #   !edismax mm='100%' tie='0.1' pf='author^25000 author2^20000 author_top^5000 author_rest^1000 title_ab^25000 title_a^15000 titleProper^1200 title_topProper^600 title_restProper^400 series^300 series2^300' qf='author^100 titleProper^120 title_topProper^60 title_restProper^40 series^50 series2^50 title^30 title_top^20 title_rest^10'} (author:keynes) OR (title:Economic AND Theory)
        # {!edismax mm='100%' tie='0.1' pf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1' qf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1'} (subject:Cultural AND Memory)
        # {!edismax mm='100%' tie='0.1' pf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1' qf='topicProper^5 topic^1 fullgeographic^1 fullgenre^1 era^1'} Cultural AND Memory
        print("print the query:ws ", params["q"])
        # print(params, end="\n")

        while True:
            results = self.send_query(params)  # send_query
            # print("Printing result.content: ", results.content)

            output = json.loads(results.content)
            # print("printing output", output, len(output))
            print(len(output['response']['docs']))
            for result in output['response']['docs']:
                yield process_results(result, list_output_fields)
            if params["cursorMark"] != output["nextCursorMark"]:
                params["cursorMark"] = output["nextCursorMark"]
            else:
                break

    def export_ids_to_csv(self, query_string, output_path, query_config_path=None, conf_query="ocr"):
        """
        Export IDs directly to a CSV file for efficient processing

        Args:
            query_string: The search query
            output_path: Path to save the CSV file
            query_config_path: Path to config file
            conf_query: Configuration section to use

        Returns:
            Dict with results information
        """
        start_time = time.time()

        # Initialize params from default but OVERRIDE the "fl" field
        params = default_solr_params(self.environment)
        params["fl"] = "id"  # Always only request IDs regardless of default config
        params["cursorMark"] = "*"
        params["rows"] = 5000  # Larger batch size
        params["q"] = make_query(query_string, query_config_path, conf_query=conf_query)
        print(params["q"])
        

        # Make sure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Create CSV and write header
        with open(output_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['id'])

        total_ids = 0
        batch_size = 10000
        ids_batch = []

        while True:
            results = self.send_query(params)
            try:
                data = json.loads(results.content)

                # Process the batch - extract ONLY the ids regardless of what fields were returned
                for doc in data['response']['docs']:
                    if 'id' in doc:
                        ids_batch.append([doc['id']])
                        total_ids += 1

                # Write batch when it reaches size threshold
                if len(ids_batch) >= batch_size:
                    with open(output_path, 'a', newline='') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerows(ids_batch)
                    print(f"Wrote batch of {len(ids_batch)} IDs, total: {total_ids}")
                    ids_batch = []

                # Check if we've reached the end
                if params["cursorMark"] == data["nextCursorMark"]:
                    break

                # Update cursor for next batch
                params["cursorMark"] = data["nextCursorMark"]

            except json.JSONDecodeError as e:
                print(f"Error decoding JSON: {e}")
                print(f"Response content (first 200 chars): {results.content[:200]}")
                # Try to continue with next batch if possible
                if 'nextCursorMark' in params and params["cursorMark"] != params["nextCursorMark"]:
                    params["cursorMark"] = params["nextCursorMark"]
                else:
                    break

        # Write any remaining IDs
        if ids_batch:
            with open(output_path, 'a', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerows(ids_batch)

        total_time = time.time() - start_time

        return {
            "status": "success",
            "file_path": output_path,
            "total_records": total_ids,
            "processing_time_seconds": total_time
        }

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
        response = requests.get(self.solr_url, auth=self.auth)
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
