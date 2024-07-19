import json
import os
from argparse import ArgumentParser

from config_search import SOLR_URL, FULL_TEXT_SEARCH_SHARDS_X
from ht_full_text_search.ht_full_text_query import HTFullTextQuery
from ht_searcher.ht_searcher import HTSearcher
from typing import Text, List, Dict

"""
LS::Operation::Search ==> it contains all the logic about interleaved adn A/B tests
"""


class HTFullTextSearcher(HTSearcher):
    def __init__(
            self,
            engine_uri: Text = None,
            ht_search_query: HTFullTextQuery = None,
            use_shards: bool = False,
    ):
        super().__init__(
            engine_uri=engine_uri,
            ht_search_query=ht_search_query,
            use_shards=use_shards,
        )

    def solr_result_output(
            self, url, query_string: Text = None, fl: List = None, operator: Text = None, query_filter: bool = False,
            filter_dict: Dict = None):

        """With one query accumulate all the results"""

        list_docs = []
        result_explanation = []
        for response in self.solr_result_query_dict(url, query_string, fl, operator, query_filter, filter_dict):

            for record in response.get("response").get("docs"):
                list_docs.append(record)
            for key, value in response.get("debug").get("explain").items():
                result_explanation.append({key: value})

        return list_docs, result_explanation

    def retrieve_documents_from_file(self, list_ids: List = None, fl: List = None,
                                     solr_url: Text = None,
                                     query_filter: bool = False, query_string: Text = None,
                                     operator: Text = None):

        """
        This function create the Solr query using the ht_id from a list of ids
        :param list_ids: List of ids
        :param fl: Fields to return
        :param solr_url: Solr url
        :param query_filter: If the query is using filter, then use config_facet_filters.yaml to create the fq parameter
        :param query_string: Query string
        :param operator: Operator, it could be, None (exact_match), "AND" (all these words) or "OR" (any of these words)
        :return:
        """

        # Processing long queries
        if len(list_ids) > 100:
            # processing the query in batches
            while list_ids:
                chunk, list_ids = list_ids[:100], list_ids[100:]

                list_docs, list_debug = self.solr_result_output(
                    url=solr_url, query_string=query_string, fl=fl, operator=operator, filter_dict={"id": chunk},
                    query_filter=query_filter
                )
                print(f"One batch of results {len(chunk)}")

                yield list_docs, list_debug

        # TODO implement the of AB test and interleave, Check the logic in the LS::Operation::Search.
        #  In previous versions of this repository you will find the logic to implement this feature (perl code
        #  transform to python code)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--env", default=os.environ.get("HT_ENVIRONMENT", "dev"))
    parser.add_argument("--query_string", help="Query string", default="*:*")
    parser.add_argument(
        "--fl", help="Fields to return", default=["author", "id", "title", "score"]
    )
    parser.add_argument("--solr_url", help="Solr url", default=None)
    parser.add_argument("--operator", help="Operator", default="AND")
    parser.add_argument(
        "--query_config", help="Type of query ocronly or all", default="all"
    )
    parser.add_argument(
        "--use_shards", help="If the query should include shards", default=False, action="store_true"
    )
    parser.add_argument(
        "--filter_path", help="Path of a JSON file used to filter Solr results", default=None
    )

    # input:
    args = parser.parse_args()

    # Receive as a parameter an specific solr url
    if args.solr_url:
        solr_url = args.solr_url
    else:  # Use the default solr url, depending on the environment. If prod environment, use shards
        solr_url = SOLR_URL[args.env]

    query_string = args.query_string
    fl = args.fl
    use_shards = False

    if args.env == "prod":
        use_shards = FULL_TEXT_SEARCH_SHARDS_X
    else:
        use_shards = args.use_shards  # By default is False

    # Create query object
    Q = HTFullTextQuery(config_query=args.query_config)

    # Create full text searcher object
    ht_full_search = HTFullTextSearcher(
        engine_uri=solr_url, ht_search_query=Q, use_shards=use_shards
    )

    filter_dict = {}
    query_filter = False

    if args.filter_path:

        # Generate filter dictionary from JSON file
        filter_json_file = open(args.filter_path, "r")
        filter_dict = json.loads(filter_json_file.read())
        query_filter = True

        total_found = 0

        list_ids = [doc_id['id'] for doc_id in filter_dict.get('response', {}).get('docs', []) if doc_id.get('id')]

        # Processing long queries
        for doc, debug_info in ht_full_search.retrieve_documents_from_file(
                list_ids=list_ids, fl=fl, solr_url=solr_url, query_filter=query_filter, query_string=query_string,
                operator=args.operator):
            print('**********************************')
            print(doc)
            print(debug_info)
    else:
        solr_output = ht_full_search.solr_result_output(
            url=solr_url, query_string=query_string, fl=fl, operator=args.operator
        )
        print(f"Total found {len(solr_output)}")
        print(solr_output)
