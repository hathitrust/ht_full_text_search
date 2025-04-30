import argparse
import csv
import json
import os


from contextlib import asynccontextmanager
from pathlib import Path
import re
import time
from typing import List
from fastapi.responses import StreamingResponse
from ht_full_text_search.ht_query.ht_query import HTSearchQuery
from main_test import SOLR_OUTPUT_SAMPLE
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ht_full_text_search.config_search import FULL_TEXT_SOLR_URL, default_solr_params
from ht_full_text_search.export_all_results import SolrExporter, make_query
from ht_full_text_search.config_files import config_files_path

from pydantic import BaseModel

class SearchRequest(BaseModel):
    field: str = "ocr"  # Default to ocr"
    query: str
    format: str = "json"  # Default to JSON, can be "csv"

# Models for advanced search
class SearchCriteria(BaseModel):
    field: str  # Field type (title, author, etc.)
    query: str  # Search term
    match_type: str  # "all of these words", "any of these words", "this exact phrase"

class AdvancedSearchRequest(BaseModel):
    criteria: List[SearchCriteria]
    field_operators: List[str]  # "AND" or "OR" between fields
    format: str = "json"  # Output format

exporter_api = {}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=os.environ.get("HT_ENVIRONMENT", "dev"))
    parser.add_argument("--solr_url", help="Solr url", default=None)

    args = parser.parse_args()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Startup the API to index documents in Solr
        """
        print("Connecting with Solr server")

        solr_url = FULL_TEXT_SOLR_URL[args.env]
        if args.solr_url:
            solr_url = args.solr_url
        exporter_api['obj'] = SolrExporter(solr_url, args.env, user=os.getenv("SOLR_USER"),
                                               password=os.getenv("SOLR_PASSWORD"))
        yield

        # Add some logic here to close the connection
    app = FastAPI(title="HT_FullTextSearchAPI", description="Search phrases in Solr full text index", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware, # type: ignore
        allow_origins=["http://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],)

    @app.get("/ping")
    def check_solr():
        """Check if the API is up"""
        response = exporter_api['obj'].get_solr_status()
        return {"status": response.status_code, "description": response.headers}

    @app.post("/query/")
    async def solr_query_phrases(request: SearchRequest):
        """
        Look for exact matches in the OCR text.
        :param query: Phrase to search
        :return: JSON with the results
        """

        # TODO: run_cursor, should receive the query_string and the query_type (ocr or all).
        # When the API is started the config file is loaded in memory,
        # so the query type can be used to select the kind of query to run and the params dict is updated with the query
        # string.

        query_config_file_path = Path(config_files_path, 'full_text_search/adv_config_query.yaml')

        # Use StreamingResponse to stream the results because run_cursor output is a generator, so data
        # is not loaded into memory and is sent in chunks.
        # return StreamingResponse(result, media_type="application/json")


        # streaming_response =  StreamingResponse(exporter_api['obj'].run_cursor(request.query, query_config_path=query_config_file_path,
        #                                                         conf_query=request.field), media_type="application/json")
        # response = await process_streaming_response(streaming_response, "/Users/umkatta/Desktop/CSV")

        # return StreamingResponse(exporter_api['obj'].run_cursor(request.query, query_config_path=query_config_file_path,
        #                                                         conf_query=request.field), media_type="application/json")

        # Option 1: returning the streaming response
        if request.format.lower() == "json":
            print("Generating Json output")
            return StreamingResponse(
                exporter_api['obj'].run_cursor(
                    request.query,
                    query_config_path=query_config_file_path,
                    conf_query=request.field
                ),
                media_type="application/json"
            )

        # Option 2: For CSV generation
        elif request.format.lower() == "csv":
            print("Generating CSV output")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = f"/Users/umkatta/Desktop/CSV/{request.query}_{timestamp}.csv"

            # This calls the new method in SolrExporter
            result = exporter_api['obj'].export_ids_to_csv(
                request.query,
                output_path,
                query_config_path=query_config_file_path,
                conf_query=request.field
            )
            return result

    @app.post("/advanced_search/")
    async def advanced_search(request: AdvancedSearchRequest):
        """
        Advanced search using edismax query syntax with proper field and operator handling.
        """
        query_config_file_path = Path(config_files_path, 'full_text_search/adv_config_query.yaml')
        facet_config_file_path = Path(config_files_path, 'full_text_search/config_facet_filters.yaml')

        if not request.criteria:
            return {"error": "No search criteria provided"}

        # Map field names
        field_map = {
            "Full Text & All Fields": "ocr",
            "All Fields": "all",
            "Title": "title",
            "Author": "author",
            "Subject": "subject"
        }

        # Process all criteria individually
        all_results = []

        # Process each criterion and collect all results
        for criteria in request.criteria:
            field = field_map.get(criteria.field, criteria.field)

            # Use HTSearchQuery to properly format the query
            ht_query = HTSearchQuery(
                config_query=field,
                config_query_path=str(query_config_file_path),
                config_facet_field="all",
                config_facet_field_path=str(facet_config_file_path)
            )

            # Map match_type to operator
            operator = None  # Default for exact phrase
            if criteria.match_type == "all of these words":
                operator = "AND"
            elif criteria.match_type == "any of these words":
                operator = "OR"

            # Get the formatted query using HTSearchQuery
            formatted_query = ht_query.manage_string_query_solr6(criteria.query, operator)

            # Get results for this criterion
            criterion_results = []
            try:
                for result in exporter_api['obj'].run_cursor(
                        formatted_query,
                        query_config_path=query_config_file_path,
                        conf_query=field
                ):
                    criterion_results.append(json.loads(result))

                print(f"Query for {field} with '{formatted_query}' returned {len(criterion_results)} results")
                all_results.append(criterion_results)
            except Exception as e:
                print(f"Error getting results for {field}: {e}")
                return {"error": f"Error with query: {str(e)}"}

        # Now combine results based on operators
        if not all_results:
            return {"error": "No results found for any criteria"}

        # Start with first criterion's results
        combined_results = all_results[0]
        combined_ids = {r.get("id") for r in combined_results}

        # Apply operators
        for i in range(1, len(all_results)):
            criterion_results = all_results[i]
            criterion_ids = {r.get("id") for r in criterion_results}

            operator = request.field_operators[i - 1] if i - 1 < len(request.field_operators) else "AND"

            if operator == "AND":
                # Keep only IDs that appear in both sets
                combined_ids = combined_ids.intersection(criterion_ids)
                combined_results = [r for r in combined_results if r.get("id") in combined_ids]
            else:  # OR
                # Add new IDs from this criterion
                new_ids = criterion_ids - combined_ids
                new_results = [r for r in criterion_results if r.get("id") in new_ids]
                combined_results.extend(new_results)
                combined_ids.update(criterion_ids)

        print(f"Final combined results: {len(combined_results)}")

        # Return results in requested format
        if request.format.lower() == "csv":
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = f"/Users/umkatta/Desktop/CSV/advanced_search_{timestamp}.csv"

            # Create CSV directly
            with open(output_path, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['id'])
                for result in combined_results:
                    writer.writerow([result.get("id", "")])

            return {
                "status": "success",
                "file_path": output_path,
                "total_records": len(combined_results)
            }
        else:
            # Return JSON directly
            return {"results": combined_results, "count": len(combined_results)}


    '''
    This function is working fine dont remove this
    '''
    # @app.post("/advanced_search/")
    # async def advanced_search(request: AdvancedSearchRequest):
    #     """
    #     Advanced search that works for both single and multiple criteria.
    #     """
    #     query_config_file_path = Path(config_files_path, 'full_text_search/adv_config_query.yaml')
    #
    #     if not request.criteria:
    #         return {"error": "No search criteria provided"}
    #
    #     # Map field names
    #     field_map = {
    #         "Full Text & All Fields": "ocr",
    #         "All Fields": "all",
    #         "Title": "title",
    #         "Author": "author",
    #         "Subject": "subject"
    #     }
    #
    #     # Process all criteria individually
    #     all_results = []
    #
    #     # Process each criterion and collect all results
    #     for criteria in request.criteria:
    #         field = field_map.get(criteria.field, criteria.field)
    #
    #         # Process query
    #         if criteria.match_type == "this exact phrase":
    #             query = f'"{criteria.query}"'
    #         elif criteria.match_type == "all of these words":
    #             query = " AND ".join(criteria.query.split())
    #         elif criteria.match_type == "any of these words":
    #             query = " OR ".join(criteria.query.split())
    #         else:
    #             query = criteria.query
    #
    #         # Get results for this criterion
    #         criterion_results = []
    #         try:
    #             for result in exporter_api['obj'].run_cursor(
    #                     query,
    #                     query_config_path=query_config_file_path,
    #                     conf_query=field
    #                     # list_output_fields=["id"]
    #             ):
    #                 criterion_results.append(json.loads(result))
    #
    #             print(f"Query for {field} with '{query}' returned {len(criterion_results)} results")
    #             all_results.append(criterion_results)
    #         except Exception as e:
    #             print(f"Error getting results for {field}: {e}")
    #             return {"error": f"Error with query: {str(e)}"}
    #
    #     # Now combine results based on operators
    #     if not all_results:
    #         return {"error": "No results found for any criteria"}
    #
    #     # Start with first criterion's results
    #     combined_results = all_results[0]
    #     combined_ids = {r.get("id") for r in combined_results}
    #
    #     # Apply operators
    #     for i in range(1, len(all_results)):
    #         criterion_results = all_results[i]
    #         criterion_ids = {r.get("id") for r in criterion_results}
    #
    #         operator = request.field_operators[i - 1] if i - 1 < len(request.field_operators) else "AND"
    #
    #         if operator == "AND":
    #             # Keep only IDs that appear in both sets
    #             combined_ids = combined_ids.intersection(criterion_ids)
    #             combined_results = [r for r in combined_results if r.get("id") in combined_ids]
    #         else:  # OR
    #             # Add new IDs from this criterion
    #             new_ids = criterion_ids - combined_ids
    #             new_results = [r for r in criterion_results if r.get("id") in new_ids]
    #             combined_results.extend(new_results)
    #             combined_ids.update(criterion_ids)
    #
    #     print(f"Final combined results: {len(combined_results)}")
    #
    #     # Return results in requested format
    #     if request.format.lower() == "csv":
    #         timestamp = time.strftime("%Y%m%d_%H%M%S")
    #         output_path = f"/Users/umkatta/Desktop/CSV/advanced_search_{timestamp}.csv"
    #
    #         # Create CSV directly
    #         with open(output_path, 'w', newline='') as csvfile:
    #             writer = csv.writer(csvfile)
    #             writer.writerow(['id'])
    #             for result in combined_results:
    #                 writer.writerow([result.get("id", "")])
    #
    #         return {
    #             "status": "success",
    #             "file_path": output_path,
    #             "total_records": len(combined_results)
    #         }
    #     else:
    #         # Return JSON directly
    #         return {"results": combined_results, "count": len(combined_results)}

    @app.post("/search_results/")
    def solr_search_results():
        """
        Look for exact matches in the OCR text.
        :return: JSON with the results
        """

        return SOLR_OUTPUT_SAMPLE

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
