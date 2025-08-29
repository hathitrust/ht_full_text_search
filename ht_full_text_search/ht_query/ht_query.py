import yaml

from functools import reduce
from typing import Text, List, Dict
from ht_full_text_search.utils.helpers import build_joined_query
from ht_full_text_search.utils.ht_logger import get_ht_logger
import json,re

logger = get_ht_logger(name=__name__)

class HTSearchQuery:
    def __init__(
            self,
            config_query: Text = "all",
            config_query_path: Text = None,
            user_id: Text = None,
            config_facet_field: Text = None,
            config_facet_field_path: Text = None,
    ):
        """
        Constructor to create the Solr query
        :param config_query: Name of the query defined in the config_query.yaml file
        :param config_query_path: Path to the config_query.yaml file
        :param user_id: Use to set up the filters
        :param config_facet_field: Name of the entry with facets and filters in config_facet_field.yaml file.
        If None, then not facet or filter will be used in the query
        :param config_facet_field_path: Path to the config_facet_field.yaml file
        :param internal: # TODO Parameter extracted from the perl code. I should check if it is necessary
        """

        # TODO: Define default values to initialize the query
        self.config_query = config_query

        try:
            self.solr_parameters = HTSearchQuery.initialize_solr_query(
                config_query_path, self.config_query
            )
        except Exception as e:
            print(f"File {config_query_path} to create Solr query does not exist. Exception: {e}")
            self.solr_parameters = {}  # Empty dictionary
        try:
            self.solr_facet_filters = HTSearchQuery.initialize_solr_query(
                config_facet_field_path, config_facet_field
            )
        except Exception as e:
            print(f"File {config_facet_field} to get the filters does not exist. Exception: {e}")
            self.solr_facet_filters = {}  # Empty dictionary
            pass

        self.user_id = user_id  # parameter used to set up the filters

    # TODO: perl method that probably we will remove
    @staticmethod
    def initialize_solr_query(config_file, conf_query: Text = "all"):
        with open(config_file, "r") as file:
            data = yaml.safe_load(file)

        return data[conf_query]

    # Function to convert a string in a dictionary
    @staticmethod
    def query_string_to_dict(string_query):
        return dict(
            qc.split("=") if qc[0] != "q" else [qc[0], "=".join(qc.split("=")[1:])]
            for qc in string_query.split("&")
        )

    @staticmethod
    def create_boost_query_fields(query_fields: List[List]) -> List:
        """
        This function create the solr qf (query fields).
        Each field is assigned a boost factor to increase or decrease their importance in the query
        Transform a list of fields and their boost factor in Solr format"""

        return ["^".join(map(str, field)) for field in query_fields]

    @staticmethod
    def create_boost_phrase_fields(query_fields):
        # phrase fields ==> Once the list of matching documents has been identified using the fq and qf parameters,
        # the pf parameter can be used to "boost" the score of documents in cases where all the terms
        # in the q parameter appear in close proximity.
        formatted_boosts = ["^".join(map(str, field)) for field in query_fields]
        return " ".join(formatted_boosts)

    @staticmethod
    def facet_creator(facet_dictionary: Dict = None) -> Dict:
        return reduce(lambda key, value: {**key, **value}, facet_dictionary)

    @staticmethod
    def query_filter_creator_string(filter_name, filter_value):

        # '\\"dog food\\" OR prices OR \\"good eats\\"'
        # This is the way of creating a list of string query filters
        filter_string = (
            "\" OR \"".join(map(str, filter_value))
            if isinstance(filter_value, list)
            else filter_value
        )
        filter_string = '"'.join(("", filter_string, ""))
        query_filters = f"{filter_name}:({filter_string})"
        return query_filters

    @staticmethod
    def query_filter_creator_rights(filter_name, filter_value):

        # This is the way of creating a list of integer query filters
        filter_string = (
            " OR ".join(map(str, filter_value))
            if isinstance(filter_value, list)
            else filter_value
        )
        query_filters = f"{filter_name}:({filter_string})"
        return query_filters

    @staticmethod
    def get_exact_phrase_query(q_string: Text) -> Text:
        return '"'.join(("", q_string, ""))
    
    @staticmethod
    def build_and_or_onephrase(lookfor=None):
        values = {}

        if lookfor is None:
            return False

        # Remove illegal characters
        illegal = ['.', '{', '}', '/', '!', ':', ';', '[', ']', '(', ')', '+ ', '&', '- ']
        for ch in illegal:
            lookfor = lookfor.replace(ch, '')

        lookfor = lookfor.strip()

        # Replace fancy quotes with normal "
        lookfor = lookfor.replace('“', '"').replace('”', '"')

        # If it looks like "..."*, pull out the quotes
        match = re.match(r'^\s*"(.*)"\*\s*$', lookfor)
        if match:
            em = match.group(1)
            lookfor = em + "*"            
        
        lookfor = HTSearchQuery.validateInput(lookfor)

        if not re.search(r'\S', lookfor):  # If no non-space char
            return False

        # Tokenize Input
        tokenized = HTSearchQuery.tokenizeInput(lookfor)

        values['onephrase'] = '"' + " ".join(tokenized).replace('"', '') + '"'
        values['and'] = " AND ".join(tokenized)
        values['or'] = " OR ".join(tokenized)
        values['asis'] = lookfor
        values['compressed'] = re.sub(r'\s+', '', lookfor)
        values['exactmatcher'] = HTSearchQuery.exactmatcherify(lookfor)
        values['emstartswith'] = values['exactmatcher'] + "*"
        
        return values

    @staticmethod
    def validateInput(text):        
        return text.strip()

    @staticmethod
    def tokenizeInput(text):
        return text.split()

    @staticmethod
    def exactmatcherify(text):        
        return text.lower().strip()

    @staticmethod
    def manage_string_query(input_phrase: Text, operator: Text = None) -> Dict:

        """
        This function transform a query_string in Solr string format

        e.g. information OR issue # boolean opperator (any of these words)
        e.g. '"information issue"' # exact phrase query
        e.g. "information issue" # all these words
        :param input_phrase:
        :param operator: It could be, all, exact_match or boolean_opperator
        :return:
        """

        if operator is None:
            return {"q": HTSearchQuery.get_exact_phrase_query(input_phrase)}
        else:
            phrase = f" {operator} ".join(input_phrase.split())
            query_string_dict = {"q": phrase, "q.op": operator}
            return query_string_dict

    @staticmethod
    def get_criteria_fields_query(criterias, field_operators, config_data):
        # Process each criterion and collect all results
        logger.info(f"get_criteria_fields_query - params : {criterias},{field_operators},{config_data}")
        query_fields = []
        fields = []        
        field_search_map = config_data["field_search_map"]

        for criteria in criterias:
            field = field_search_map.get(criteria.field, criteria.field)
            fields.append(field)
            
            # Map match_type to operator
            operator = None  # Default for exact phrase
            if criteria.match_type == "all of these words":
                operator = "AND"
            elif criteria.match_type == "any of these words":
                operator = "OR"

            # Get the formatted query using HTSearchQuery            
            formatted_query = HTSearchQuery.manage_string_query_solr6(criteria.query, operator, field if len(criterias)>1 else None)
            query_fields.append(formatted_query)
            # Get results for this criterion

        joined_query = build_joined_query(query_fields, field_operators)
        logger.info(f"build_joined_query - output : {joined_query}")

        # query_fields = " OR ".join(query_fields)
        return fields, joined_query

    @staticmethod
    def standard_search_components(search, field_operators, config_data):
        searchComponents = {}
        queries_lst=[]     

        query = ""

        # Iterating over search config fields        
        for tvb in search:                       
            type_ = tvb[0]            

            values = HTSearchQuery.build_and_or_onephrase(tvb[1])                        

            if type_ in config_data and values:
                comp = "(" + HTSearchQuery.build_query_string(config_data[type_], values) + ")"
                queries_lst.append(comp)                                        

        joined_query = build_joined_query(queries_lst,field_operators)

        if re.search(r"\S", joined_query): 
            searchComponents["q"] = joined_query
        else:
            searchComponents["q"] = "*:*"            

        return searchComponents

    def build_query_string(structure, values, joiner="OR"):
        clauses = []

        for field, clausearray in structure.items():
            
            if isinstance(field, int) or str(field).isdigit():
                # First item gives operator + weight
                opweight = clausearray.pop(0)
                op = opweight[0]
                weight = opweight[1]

                sstring = "(" + HTSearchQuery.build_query_string({i: v for i, v in enumerate(clausearray)}, values, op) + ")"

                if weight and weight > 0:
                    sstring += f"^{weight}"

                clauses.append(sstring)
                continue

            # Case 2: Normal field: clausearray is list of [val, weight]
            for valweight in clausearray:
                val = valweight[0]
                weight = valweight[1]

                # Ensure value exists
                if val not in values:
                    if val == "lcnormalized":                        
                        normalized = HTSearchQuery.LCCallNumberNormalizer(values.get("asis", ""), False)
                        if normalized:
                            values[val] = normalized
                        else:
                            continue

                    if val == "stdnum":
                        match = re.match(r'^\s*0*([\d\-\.]+[xX]?).*$', values.get("asis", ""))
                        if match:
                            stdnum = match.group(1)
                            # stdnum = re.sub(r'[\.\-]', '', stdnum)  # original code commented
                            stdnum = HTSearchQuery.Normalize_stdnum(stdnum)
                            values[val] = stdnum

                if val not in values or values[val] == "":
                    continue

                # Build field clause
                sstring = f"{field}:({values[val]})"
                if weight and weight > 0:
                    sstring += f"^{weight}"

                clauses.append(sstring)

        newq = f" {joiner} ".join(clauses)
        return newq

    # -----------------------
    # Stub helpers for PHP equivalents
    # -----------------------

    @staticmethod
    def LCCallNumberNormalizer(text, strict=False):
        # TODO: implement call number normalization logic
        # For now, just return text unchanged
        return text.strip() if text else None

    @staticmethod
    def Normalize_stdnum(stdnum):
        # TODO: implement actual stdnum normalization logic
        # For now, strip spaces, uppercase X
        return stdnum.replace(" ", "").upper()

    @staticmethod
    def manage_string_query_solr6(input_phrase: Text, operator: Text = None, field:str=None) -> str| None:
        """
        This function transform a query_string in Solr string format

        e.g. information OR issue # boolean opperator (any of these words)
        e.g. "\"information issue\"" # exact phrase query
        e.g. "information AND issue" # all these words
        :param input_phrase:
        :param operator: It could be, all, exact_match or boolean_opperator
        :return:
        """
        logger.info(f"manage_string_query_solr6 - params : {input_phrase},{operator},{field}")
       
        # query_string_dict = {"q": HTSearchQuery.get_exact_phrase_query(input_phrase)}
        formatted_query = ""
        if operator == "OR" or operator == "AND":
            # " AND ".join(input_phrase.split())
            formatted_query = f" {operator} ".join(input_phrase.split())            
        elif operator is None:
            formatted_query = "\"" + input_phrase + "\""

        if field:
            return f"({field}:{formatted_query})"
        return formatted_query


    def create_params_dict(self, start: int = 0, rows: int = 100) -> Dict:

        params = {
            "defType": self.solr_parameters.get("parser") if self.solr_parameters.get("parser") else "edismax",
            "start": start,
            "rows": rows,
            "fl": self.solr_parameters.get("fl") if self.solr_parameters.get("fl") else [],
            "indent": "on",
            "debug": self.solr_parameters.get("debug"),
            "mm": self.solr_parameters.get("mm"),  # 100 % 25, # mm = minimum match
            "tie": self.solr_parameters.get("tie"),  # "0.9", # tie = tie breaker qf = query fields. Each field is
            # assigned a boost factor to increase or decrease their importance in the query
            "qf": HTSearchQuery.create_boost_phrase_fields(self.solr_parameters.get("qf")),
            "pf": HTSearchQuery.create_boost_phrase_fields(self.solr_parameters.get("pf"))
            if self.solr_parameters.get("pf") else []
        }
        return params

    def make_solr_query(
            self,
            q_string: Text = None,
            operator: Text = None,
            start: int = 0,
            rows: int = 100,
            fl: List = None,
            query_filter: bool = False,
            filter_dict: Dict = None
    ):
        """
        This function create the Solr query
        :param q_string: Query string
        :param operator: It could be, None (exact_match), "AND" (all these words) or "OR" (any of these words)
        :param start: Start
        :param rows:
        :param fl:
        :param query_filter:If the query is using filter, then use config_facet_filters.yaml to create the fq parameter
        :param filter_dict: Pass as a parameter or use the config_facet_filters.yaml if filter is True. It should have this format: {"id": [1,2,3,4,5]}
        :return:
        """

        params = self.create_params_dict(start, rows)

        if not q_string:
            params.update({"q": "*:*"})
        else:
            params.update(HTSearchQuery.manage_string_query(q_string, operator))

        if self.solr_facet_filters:
            params.update(HTSearchQuery.facet_creator(self.solr_facet_filters.get("facet")))

        print(params)
        if fl:
            params.update({"fl": fl})

        # Add the filter query
        # The HT rights should be automatically retrieved on this function (Check the code the perl code)
        if query_filter:
            if filter_dict:
                params.update({"fq": HTSearchQuery.query_filter_creator_string("id",
                                                                                   filter_dict.get("id"))})
            else:  # Will retrieve the default filters defined in config_facet_filters.yaml
                params.update(
                    {"fq": HTSearchQuery.query_filter_creator_rights("rights",
                                                                     [25, 15, 18, 1, 21, 23, 19, 13, 11, 20, 7, 10, 24,
                                                                      14, 17, 22, 12])})
        return params


if __name__ == "__main__":
    # Example usage
    query_string = "Natural history"
    # internal = [[1, 234, 4, 456, 563456, 43563, 3456345634]]
    Q = HTSearchQuery(config_query="all")
    solr_query = Q.make_solr_query(q_string=query_string, operator="OR")

    print(solr_query)
