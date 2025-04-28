#!/usr/bin/env python3
# elasticsearch_grok_indexer.py
import pandas as pd
import json
import requests
import urllib3
import logging
import sys
import os
from tqdm import tqdm
from requests.auth import HTTPBasicAuth

# Suppress insecure HTTPS warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 读取ES连接信息
ES_HOST = "https://localhost:9200"
ES_USER = "elastic"
ES_PASSWORD = os.environ.get('ES_PASS')
if not ES_PASSWORD:
    logging.error("ES_PASS environment variable not set. Please set it before running this script.")
    sys.exit(1)
ES_AUTH = HTTPBasicAuth(ES_USER, ES_PASSWORD)

INDEX_NAME = "restaurants"
PIPELINE_ID = "restaurants_grok_pipeline"

# 创建grok pipeline
def create_grok_pipeline():
    """Create the grok-based ingestion pipeline"""
    pipeline_def = {
        "description": "Pipeline for processing restaurant data",
        "processors": [
            {
                "date": {
                    "field": "Date",
                    "target_field": "@timestamp",
                    "formats": ["yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", "strict_date_optional_time"]
                }
            }
        ]
    }
    
    url = f"{ES_HOST}/_ingest/pipeline/{PIPELINE_ID}"
    try:
        response = requests.put(url, auth=ES_AUTH, headers={"Content-Type": "application/json"}, json=pipeline_def, verify=False)
        response.raise_for_status()
        logging.info(f"Pipeline {PIPELINE_ID} created/updated.")
    except Exception as e:
        logging.error(f"Failed to create pipeline: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Response status: {e.response.status_code}")
            logging.error(f"Response body: {e.response.text}")
        sys.exit(1)

# 删除并重建索引
def recreate_index():
    idx_url = f"{ES_HOST}/{INDEX_NAME}"
    r = requests.head(idx_url, auth=ES_AUTH, verify=False)
    if r.status_code == 200:
        requests.delete(idx_url, auth=ES_AUTH, verify=False)
        logging.info(f"Index '{INDEX_NAME}' deleted.")
    
    # 创建带有映射的索引
    mapping = {
        "mappings": {
            "properties": {
                "Coordinates": {
                    "type": "geo_point"
                },
                "@timestamp": {
                    "type": "date"
                },
                "Date": {
                    "type": "date"
                },
                "AggregateRating": {
                    "type": "float"
                },
                "Votes": {
                    "type": "float"
                },
                "AverageCostForTwo": {
                    "type": "long"
                },
                "SerialNumber": {
                    "type": "long"
                }
            }
        }
    }
    r = requests.put(idx_url, auth=ES_AUTH, json=mapping, headers={"Content-Type": "application/json"}, verify=False)
    r.raise_for_status()
    logging.info(f"Index '{INDEX_NAME}' created with mappings.")

# 校验一行数据
def validate_row(row):
    try:
        if int(row[0]) < 0: return False
        if not (0 <= float(row[3]) <= 5): return False
        if float(row[5]) < 0: return False
        if float(row[2]) < 0: return False
        import re
        match = re.search(r'\[\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\]', str(row[7]))
        if match:
            lat = float(match.group(1)); lon = float(match.group(2))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180): return False
        return True
    except: return False

# 生成bulk数据
def prepare_bulk_data(csv_file):
    """Read the CSV and prepare bulk indexing data"""
    try:
        df = pd.read_csv(csv_file, sep=';')
        logging.info(f"Read {len(df)} rows from {csv_file}")
        
        # 打印第一行数据，用于调试
        first_row = df.iloc[0]
        logging.info(f"First row data: {first_row.to_dict()}")
        
        bulk_data = []
        for _, row in df.iterrows():
            # 处理坐标数据
            coords_str = str(row['Coordinates'])
            import re
            match = re.search(r'\[\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\]', coords_str)
            if match:
                lat = float(match.group(1))
                lon = float(match.group(2))
                coordinates = {"lat": lat, "lon": lon}
                
                # 验证坐标是否有效
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    logging.warning(f"Invalid coordinates values: lat={lat}, lon={lon}")
                    continue
            else:
                logging.warning(f"Invalid coordinates format for row: {coords_str}")
                continue  # 跳过无效坐标的记录
            
            # 直接构建文档
            doc = {
                "SerialNumber": int(row['SerialNumber']),
                "RestaurantName": str(row['RestaurantName']),
                "AverageCostForTwo": int(row['AverageCostForTwo']),
                "AggregateRating": float(row['AggregateRating']),
                "RatingText": str(row['RatingText']),
                "Votes": float(row['Votes']),
                "Date": str(row['Date']),
                "Coordinates": coordinates,  # 使用解析后的坐标对象
                "City": str(row['City']),
                "Country": str(row['Country']),
                "Continent": str(row['Continent']),
                "City/Country/Continent": f"{str(row['City'])}/{str(row['Country'])}/{str(row['Continent'])}"
            }
            
            # 打印第一条数据的格式，用于调试
            if len(bulk_data) == 0:
                logging.info(f"First document format: {json.dumps(doc, indent=2)}")
            
            # Add index action and document
            bulk_data.append(json.dumps({"index": {"_index": INDEX_NAME}}))
            bulk_data.append(json.dumps(doc))
        
        return '\n'.join(bulk_data) + '\n'  # Add final newline
    except Exception as e:
        logging.error(f"Error preparing bulk data: {str(e)}")
        sys.exit(1)

# bulk导入，带重试和进度条
def bulk_index(bulk_data):
    url = f"{ES_HOST}/_bulk?pipeline={PIPELINE_ID}"
    headers = {"Content-Type": "application/x-ndjson"}
    max_retries = 3
    lines = bulk_data.strip().split('\n')
    batch_size = 2000
    for attempt in range(1, max_retries+1):
        try:
            for i in tqdm(range(0, len(lines), batch_size), desc=f"Bulk import attempt {attempt}"):
                batch = '\n'.join(lines[i:i+batch_size]) + '\n'
                r = requests.post(url, auth=ES_AUTH, headers=headers, data=batch, verify=False)
                result = r.json()
                if result.get('errors', False):
                    logging.error(f"Errors in batch {i//batch_size+1}")
            return True
        except Exception as e:
            logging.error(f"Bulk import error (attempt {attempt}): {e}")
            if attempt < max_retries:
                import time; time.sleep(2)
            else:
                logging.error("Bulk import permanently failed.")
                return False

if __name__ == "__main__":
    logging.info("Start grok pipeline import...")
    create_grok_pipeline()
    recreate_index()
    bulk_data = prepare_bulk_data('/Users/zitian/Visual-Analytics-SP-2025/assigment2/Assignment2/restaurants_cleaned.csv')
    ok = bulk_index(bulk_data)
    if ok:
        logging.info("Grok pipeline import completed successfully.")
    else:
        logging.error("Grok pipeline import failed.")