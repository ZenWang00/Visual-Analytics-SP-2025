# data_cleaner.py
import pandas as pd
import numpy as np
import re
import logging
from tqdm import tqdm
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def clean_restaurant_data():
    """
    Clean and prepare the restaurant dataset for Elasticsearch import
    """
    input_file = os.path.abspath('Assignment2/restaurants.csv')
    output_file = os.path.abspath('Assignment2/restaurants_cleaned.csv')
    logging.info(f"Starting data cleaning process for {input_file}")
    
    # 1. 读取绝对路径的csv
    df = pd.read_csv(input_file, sep=';')
    
    # Display initial info
    logging.info(f"Original dataset: {df.shape[0]} rows, {df.shape[1]} columns")
    logging.info(f"Column names: {list(df.columns)}")
    
    # Check for missing values
    missing_values = df.isnull().sum()
    logging.info(f"Missing values by column:\n{missing_values}")
    
    # Rename the first column to SerialNumber
    first_col = df.columns[0]
    df = df.rename(columns={first_col: 'SerialNumber'})
    
    # 使用tqdm进度条包裹主要清洗步骤
    for _ in tqdm(range(1), desc="Cleaning numeric fields"):
        # Clean AggregateRating - ensure it's numeric
        df['AggregateRating'] = pd.to_numeric(df['AggregateRating'], errors='coerce')
        # Clean Votes - ensure it's numeric
        df['Votes'] = pd.to_numeric(df['Votes'], errors='coerce')
        # Clean AverageCostForTwo - ensure it's numeric
        df['AverageCostForTwo'] = pd.to_numeric(df['AverageCostForTwo'], errors='coerce')
    
    for _ in tqdm(range(1), desc="Filling missing values"):
        # Fill missing values appropriately
        df['RestaurantName'] = df['RestaurantName'].fillna('Unknown Restaurant')
        df['RatingText'] = df['RatingText'].fillna('Not Rated')
        df['AggregateRating'] = df['AggregateRating'].fillna(0)
        df['Votes'] = df['Votes'].fillna(0)
        df['AverageCostForTwo'] = df['AverageCostForTwo'].fillna(0)
    
    # Validate date format
    def validate_date(date_str):
        if pd.isna(date_str):
            return None
        # Check if date is already in ISO format
        if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', str(date_str)):
            return date_str
        try:
            # Try to parse as datetime and convert to ISO
            date = pd.to_datetime(date_str)
            return date.strftime('%Y-%m-%dT%H:%M:%SZ')
        except:
            return None
    df['Date'] = df['Date'].apply(validate_date)
    # 只保留Date字段非空且格式正确的行
    df = df[df['Date'].notnull() & (df['Date'] != '')]
    
    # Handle City/Country/Continent
    def split_location(location_str):
        if pd.isna(location_str):
            return 'Unknown/Unknown/Unknown'
        parts = location_str.split('/')
        if len(parts) < 3:
            while len(parts) < 3:
                parts.append('Unknown')
        # 统一城市名格式：strip并首字母大写
        parts[0] = parts[0].strip().title()
        return '/'.join(parts)
    tqdm.pandas(desc="Standardizing city names")
    df['City/Country/Continent'] = df['City/Country/Continent'].progress_apply(split_location)
    
    # 先只保留前3段，去除多余的斜杠
    df['City/Country/Continent'] = df['City/Country/Continent'].apply(lambda x: '/'.join(str(x).split('/')[:3]))
    # 拆分为三列
    split_cols = df['City/Country/Continent'].str.split('/', expand=True)
    split_cols.columns = ['City', 'Country', 'Continent']
    # 删除地理信息不全的行（任一为空或为Unknown都删）
    mask = (
        split_cols['City'].notna() & (split_cols['City'] != '') & (split_cols['City'].str.lower() != 'unknown') &
        split_cols['Country'].notna() & (split_cols['Country'] != '') & (split_cols['Country'].str.lower() != 'unknown') &
        split_cols['Continent'].notna() & (split_cols['Continent'] != '') & (split_cols['Continent'].str.lower() != 'unknown')
    )
    df = df[mask].copy()
    df[['City', 'Country', 'Continent']] = split_cols[mask]
    
    # Validate coordinates
    def validate_coordinates(coord_str):
        if pd.isna(coord_str):
            return '[0, 0]'  # Default coordinates if missing
        if re.match(r'\[\s*[-+]?\d*\.?\d+\s*,\s*[-+]?\d*\.?\d+\s*\]', str(coord_str)):
            return coord_str
        try:
            match = re.search(r'\[\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\]', str(coord_str))
            if match:
                lat = float(match.group(1))
                lon = float(match.group(2))
                if lat < -90 or lat > 90:
                    lat = 0
                if lon < -180 or lon > 180:
                    lon = 0
                return f"[{lat}, {lon}]"
            else:
                return '[0, 0]'
        except:
            return '[0, 0]'
    tqdm.pandas(desc="Validating coordinates")
    df['Coordinates'] = df['Coordinates'].progress_apply(validate_coordinates)
    
    # Check for duplicates
    duplicate_count = df.duplicated().sum()
    logging.info(f"Found {duplicate_count} duplicate entries")
    if duplicate_count > 0:
        df = df.drop_duplicates()
        logging.info(f"Removed duplicates. New size: {df.shape[0]} rows")
    
    # Save the cleaned data
    df.to_csv(output_file, sep=';', index=False)
    logging.info(f"Cleaning complete. Data saved to '{output_file}'")
    logging.info(f"Final dataset: {df.shape[0]} rows, {df.shape[1]} columns")
    
    return df

if __name__ == "__main__":
    clean_restaurant_data() 