#!/usr/bin/env python3
# elasticsearch_grok_indexer.py
import pandas as pd
import json
import requests
import urllib3
import logging
import sys
import os
from requests.auth import HTTPBasicAuth
import re

# Suppress insecure HTTPS warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Elasticsearch connection settings
ES_HOST = "https://localhost:9200"
ES_USER = "elastic"
ES_PASSWORD = os.environ.get('ES_PASS')
if not ES_PASSWORD:
    logging.error("ES_PASS environment variable not set. Please set it before running this script.")
    sys.exit(1)
ES_HEADERS = {"Content-Type": "application/json"}
ES_AUTH = HTTPBasicAuth(ES_USER, ES_PASSWORD)
index_name = "restaurants"

def create_pipeline():
    """Create the grok-based ingestion pipeline"""
    pipeline_id = "restaurants_grok_pipeline"
    pipeline_def = {
        "description": "Pipeline for processing restaurant data using grok patterns",
        "processors": [
            {
                "grok": {
                    "field": "raw_data",
                    "patterns": [
                        "%{DATA:SerialNumber};%{DATA:RestaurantName};%{NUMBER:AverageCostForTwo};%{NUMBER:AggregateRating};%{DATA:RatingText};%{NUMBER:Votes};%{TIMESTAMP_ISO8601:Date};\\[%{SPACE}*%{NUMBER:lat}%{SPACE}*,%{SPACE}*%{NUMBER:lon}%{SPACE}*\\];(?:(?<City1>%{DATA})/)?(?<City2>%{DATA})/(?<Country>%{DATA})/(?<Continent>%{DATA})"
                    ],
                    "ignore_missing": True
                }
            },
            {
                "convert": {
                    "field": "SerialNumber",
                    "type": "long",
                    "ignore_missing": True
                }
            },
            {
                "convert": {
                    "field": "AverageCostForTwo",
                    "type": "long",
                    "ignore_missing": True
                }
            },
            {
                "convert": {
                    "field": "AggregateRating",
                    "type": "double",
                    "ignore_missing": True
                }
            },
            {
                "convert": {
                    "field": "Votes",
                    "type": "double",
                    "ignore_missing": True
                }
            },
            {
                "set": {
                    "field": "Coordinates",
                    "value": "{{lat}},{{lon}}",
                    "ignore_empty_value": True
                }
            },
            {
                "set": {
                    "field": "City",
                    "value": "{{City2}}",
                    "ignore_empty_value": True
                }
            },
            {
                "set": {
                    "field": "City/Country/Continent",
                    "value": "{{City2}}/{{Country}}/{{Continent}}",
                    "ignore_empty_value": True
                }
            },
            {
                "date": {
                    "field": "Date",
                    "target_field": "@timestamp",
                    "formats": ["yyyy-MM-dd'T'HH:mm:ss'Z'"],
                    "timezone": "UTC"
                }
            },
            {
                "remove": {
                    "field": ["raw_data", "lat", "lon", "City1", "City2"],
                    "ignore_missing": True
                }
            }
        ]
    }
    
    url = f"{ES_HOST}/_ingest/pipeline/{pipeline_id}"
    try:
        response = requests.put(url, auth=ES_AUTH, headers=ES_HEADERS, json=pipeline_def, verify=False)
        response.raise_for_status()
        logging.info(f"Pipeline {pipeline_id} created successfully")
        return pipeline_id
    except Exception as e:
        logging.error(f"Failed to create pipeline: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Response status: {e.response.status_code}")
            logging.error(f"Response body: {e.response.text}")
        sys.exit(1)

def create_index_template():
    """Create an index template with appropriate mappings"""
    template_id = "restaurants_template"
    template_def = {
        "index_patterns": ["restaurants*"],
        "template": {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            },
            "mappings": {
                "properties": {
                    "SerialNumber": {"type": "long"},
                    "RestaurantName": {"type": "keyword"},
                    "AverageCostForTwo": {"type": "long"},
                    "AggregateRating": {"type": "double"},
                    "RatingText": {"type": "keyword"},
                    "Votes": {"type": "double"},
                    "Date": {"type": "date", "format": "iso8601"},
                    "@timestamp": {"type": "date", "format": "strict_date_optional_time"},
                    "Coordinates": {"type": "geo_point"},
                    "City": {"type": "keyword"},
                    "Country": {"type": "keyword"},
                    "Continent": {"type": "keyword"},
                    "City/Country/Continent": {"type": "keyword"}
                }
            }
        }
    }
    
    url = f"{ES_HOST}/_index_template/{template_id}"
    try:
        response = requests.put(url, auth=ES_AUTH, headers=ES_HEADERS, json=template_def, verify=False)
        response.raise_for_status()
        logging.info(f"Index template {template_id} created successfully")
    except Exception as e:
        logging.error(f"Failed to create index template: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Response status: {e.response.status_code}")
            logging.error(f"Response body: {e.response.text}")
        sys.exit(1)

def recreate_index():
    """Delete and recreate the index"""
    # Check if index exists and delete it
    try:
        response = requests.head(f"{ES_HOST}/{index_name}", auth=ES_AUTH, headers=ES_HEADERS, verify=False)
        if response.status_code == 200:
            logging.info(f"Deleting existing index {index_name}")
            delete_response = requests.delete(f"{ES_HOST}/{index_name}", auth=ES_AUTH, headers=ES_HEADERS, verify=False)
            delete_response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # 404 is ok, index doesn't exist
        if e.response.status_code != 404:
            logging.error(f"Error checking/deleting index: {str(e)}")
            sys.exit(1)
    
    # Create the index
    try:
        response = requests.put(f"{ES_HOST}/{index_name}", auth=ES_AUTH, headers=ES_HEADERS, verify=False)
        response.raise_for_status()
        logging.info(f"Index {index_name} created successfully")
    except Exception as e:
        logging.error(f"Failed to create index: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Response status: {e.response.status_code}")
            logging.error(f"Response body: {e.response.text}")
        sys.exit(1)

def prepare_bulk_data(csv_file):
    """Read the CSV and prepare bulk indexing data"""
    try:
        df = pd.read_csv(csv_file, sep=';')
        logging.info(f"Read {len(df)} rows from {csv_file}")
        
        bulk_data = []
        for _, row in df.iterrows():
            # Extract coordinates
            coords_str = str(row['Coordinates'])
            match = re.search(r'\[\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\]', coords_str)
            if match:
                lat = float(match.group(1))
                lon = float(match.group(2))
                coordinates = f"{lat},{lon}"
            else:
                coordinates = "0,0"
            
            # Extract location parts
            location_parts = str(row['City/Country/Continent']).split('/')
            city = location_parts[0] if len(location_parts) > 0 else ''
            country = location_parts[1] if len(location_parts) > 1 else ''
            continent = location_parts[2] if len(location_parts) > 2 else ''
            
            # Build document
            doc = {
                "SerialNumber": int(row['SerialNumber']),
                "RestaurantName": str(row['RestaurantName']),
                "AverageCostForTwo": int(row['AverageCostForTwo']),
                "AggregateRating": float(row['AggregateRating']),
                "RatingText": str(row['RatingText']),
                "Votes": float(row['Votes']),
                "Date": str(row['Date']),
                "@timestamp": str(row['Date']),
                "Coordinates": coordinates,
                "City": city,
                "Country": country,
                "Continent": continent,
                "City/Country/Continent": f"{city}/{country}/{continent}"
            }
            
            # Add index action and document
            bulk_data.append(json.dumps({"index": {"_index": index_name}}))
            bulk_data.append(json.dumps(doc))
        
        return '\n'.join(bulk_data) + '\n'  # Add final newline
    except Exception as e:
        logging.error(f"Error preparing bulk data: {str(e)}")
        sys.exit(1)

def bulk_index(bulk_data, pipeline_id=None):
    """Perform bulk indexing with the pipeline"""
    url = f"{ES_HOST}/_bulk"  # Remove pipeline parameter
    headers = {"Content-Type": "application/x-ndjson"}
    
    try:
        response = requests.post(url, auth=ES_AUTH, headers=headers, data=bulk_data, verify=False)
        result = response.json()
        
        if result.get('errors', False):
            error_count = sum(1 for item in result.get('items', []) 
                             if item.get('index', {}).get('status', 200) >= 400)
            logging.error(f"Bulk indexing completed with {error_count} errors")
            for item in result.get('items', []):
                if item.get('index', {}).get('status', 200) >= 400:
                    logging.error(f"Error: {item['index'].get('error')}")
            return False
        else:
            took_ms = result.get('took', 0)
            count = len(result.get('items', []))
            logging.info(f"Bulk indexing completed successfully: {count} documents indexed in {took_ms}ms")
            return True
    except Exception as e:
        logging.error(f"Error during bulk indexing: {str(e)}")
        return False

def main(csv_file='restaurants_cleaned.csv'):
    logging.info("Starting Elasticsearch indexing")
    
    # Create the components and prepare data
    create_index_template()
    recreate_index()
    bulk_data = prepare_bulk_data(csv_file)
    
    # Perform the bulk indexing
    success = bulk_index(bulk_data)
    
    if success:
        logging.info("Indexing completed successfully")
        return 0
    else:
        logging.error("Indexing completed with errors")
        return 1

if __name__ == "__main__":
    # Accept command line argument for CSV file
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
        sys.exit(main(csv_file))
    else:
        sys.exit(main())