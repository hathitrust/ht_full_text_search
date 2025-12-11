import csv, json, tempfile, pathlib
from typing import Iterable, Mapping, Sequence, Any
from datetime import datetime
import os

@staticmethod
def get_criteria_fields_query(criterias, field_operators, config_data):
    # Process each criterion and collect all results

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

    joined_query = query_fields[0]
    for i in range(1, len(query_fields)):
        if i - 1 < len(field_operators):  # check if operator at i-1 exists
            op = field_operators[i - 1]
        else:   
            op = "AND"
        joined_query += f" {op} {query_fields[i]}"
    # query_fields = " OR ".join(query_fields)
    return fields, joined_query



def build_date_filter(date_value, field_facet_mapping): 
    """
    Returns Solr fq values for date filtering 
    """
    start_date, end_date, in_date = date_value.get("start_year"),date_value.get("end_year"),date_value.get("in_year")      
    date_range_facet = field_facet_mapping['date_range_facet']
    date_trie_facet = field_facet_mapping['date_trie_facet']

    fq = ""
    if in_date is not None and in_date.strip() != "":
        # During year
        facet = f'{date_range_facet}:"{in_date}"'                
        fq = facet

    elif (start_date is not None and start_date.strip() != "") or (end_date is not None and end_date.strip() != ""):
        # in between / After / before dates
        start_date = start_date if start_date and start_date.strip() != "" else "*"
        end_date = end_date if end_date and end_date.strip() != "" else "*"
        fq = f'{date_trie_facet}:[ {start_date} TO {end_date} ]'
    else:
        return ""        

    return fq


def build_field_filters(field,values:list|str, field_facet_mapping):       
    """
    Creates filter query for generic list/str input
    -- Ex. (location : (US OR NY))
    """                  
    facet = field_facet_mapping.get(field)
    fq = ""
    if isinstance(values,str):
        return f'{facet}:"{values}"'
    if facet and values:
        facet_value = " OR ".join(values)
        fq = f"{facet}:({facet_value})"        

    return fq


def build_fq_query(filter_fields,config_data):     
    """
    Handles fq generation logic, based on filter fields (date, language, format and location)
    """
    filters_list = []
    for field,value in filter_fields.items():  
        field_fq = ""
        if value:             
            if field=="date":
                field_fq = build_date_filter(value,config_data["field_facet_mapping"])
            else:
                field_fq = build_field_filters(field,value,config_data["field_facet_mapping"])
        if field_fq:
            filters_list.append(field_fq)
                
    return " AND ".join(filters_list)

def write_csv_and_get_path(
    rows: Iterable[Any],                 # rows can be dicts or JSON strings
    required_fields: Sequence[str] | None = None,
    out_dir: str | pathlib.Path | None = None,
    filename: str = "export.csv",
) -> dict:
    """
    Write ONLY the required fields to a CSV on disk and return path + meta.
    """
    if required_fields is None:
        required_fields = ("id",)        # safe default
    
    # ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    # stem, ext = os.path.splitext(filename)
    # filename_ts = f"{stem}_{ts}{ext or '.csv'}"
    filename_ts = filename
    out_dir = pathlib.Path(out_dir or tempfile.gettempdir())
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename_ts

    total = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=required_fields, extrasaction="ignore")
        writer.writeheader()

        for row in rows:
            # Normalize to dict
            if isinstance(row, (bytes, bytearray)):
                row = row.decode()
            if isinstance(row, str):
                row = json.loads(row)

            # Keep only required fields (fill missing with "")
            filtered = {k: row.get(k, "") for k in required_fields}
            writer.writerow(filtered)
            total += 1

    return {
        "file_path": str(path),
        "total_records": total,
    }


def build_joined_query(query_fields, field_operators):
    """
    Builds a Solr query with parentheses around every pair:
    (A OR B) OR C
    (A OR B) OR (C OR D)
    """

    default_op = "AND"
    grouped = []
    i = 0

    while i < len(query_fields):
        # If a pair exists, group it
        if i + 1 < len(query_fields):
            op = (
                field_operators[i]
                if i < len(field_operators)
                else default_op
            )
            grouped.append(f"({query_fields[i]} {op} {query_fields[i+1]})")
            i += 2
        else:
            # Single leftover element without a pair
            grouped.append(query_fields[i])
            i += 1

    # Now join the grouped chunks using remaining operators
    final_query = grouped[0]
    op_index = 1

    for j in range(1, len(grouped)):
        op = (
            field_operators[op_index]
            if op_index < len(field_operators)
            else default_op
        )
        final_query += f" {op} {grouped[j]}"
        op_index += 1

    return final_query
