import requests
import json
from ht_query.ht_query import HTSearchQuery
from typing import Text, List, Dict

"""
Perl
slip-lib::Search::Searcher

* slip-lib::Search::Searcher
     This class encapsulates the search interface to Solr/Lucene. It
    provides two interfaces.  One to handle user entered queries and one
    to handle queries generated internally by the application.

There is a logic to select Solr URL that with Solr Cloud probably we did not need it anymore
"""


class HTSearcher:
    """
    Inputs:
        - Solr url
        - query string

    This class encapsulates the search interface to Solr.

    In perl we have an input variable C, that is the context with the main set up to initialize the search
    We should identify what is the best way of doing it in python (if need it) => it probably makes sense to
    create a JSON ir YAML file with these parameters, default query, default urls, num_documents, pagination

    """

    def __init__(
            self,
            engine_uri: Text = None,
            timeout: int = None,
            ht_search_query: HTSearchQuery = None,
            use_shards: bool = False,
    ):
        self.engine_uri = engine_uri
        self.timeout = timeout
        self.use_shards = use_shards  # Not sure if we need it right now
        self.query_maker = ht_search_query

        # TODO HTTP request string and JSON object. We should transform the query string into a JSON object
        self.headers = {
            "Content-type": "application/json"
        }

    def get_documents_query_dict(self, url, query_dict, start: int = 0, rows: int = 100):

        print(url)
        print(f"{url.replace('#/', '')}query")
        query_dict.update({"start": start, "rows": rows})
        response = requests.post(
            url=f"{url.replace('#/', '')}query", params=query_dict, headers=self.headers, stream=True
        )
        return response

    def solr_result_query_dict(
            self, url,
            query_string: Text = None,
            fl: List = None,
            operator: Text = None,
            query_filter: bool = False,
            filter_dict: Dict = None,
            rows: int = 100,
            start: int = 0) -> Dict:

        """
        Query Solr and return the results

        :param url: Solr URL
        :param query_string: Query string
        :param fl: Fields to return
        :param operator: Operator, it could be, None (exact_match), "AND" (all these words) or "OR" (any of these words)
        :param query_filter: If the query is using filter, then use config_facet_filters.yaml to create the fq parameter
        :param filter_dict: Filter dictionary
        :param rows: Number of rows
        :param start: Start
        :return:
        """
        # query_string += "&wt=json&indent=off" if "wt=" not in query_string else ""

        query_dict = self.query_maker.make_solr_query(
            query_string=query_string, operator=operator, fl=fl, query_filter=query_filter, filter_dict=filter_dict
        )

        if self.use_shards:
            query_dict["shards"] = self.use_shards
            query_dict["shards.info"] = "true"
        print(query_dict)

        query_dict.update({"start": start, "rows": rows})

        # Counting total records
        response = self.get_documents_query_dict(url, query_dict)
        output = response.json()

        try:
            total_records = output.get("response").get("numFound")
            print(total_records)
        except Exception as e:
            print(f"Solr index {url} seems empty {e}")
            exit()
        count_records = 0
        while count_records < total_records:
            results = []

            response = self.get_documents_query_dict(url, query_dict, start, rows)

            output = json.loads(response.content.decode("utf-8"))

            count_records = count_records + len(output.get("response").get("docs"))

            print(f"Batch documents {count_records}")
            start += rows
            print(f"Result length {len(results)}")
            yield output
