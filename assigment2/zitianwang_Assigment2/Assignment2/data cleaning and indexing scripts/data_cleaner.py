# data_cleaner.py
import pandas as pd
import numpy as np
import re
import logging
from tqdm import tqdm
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def clean_restaurant_data(input_file='restaurants.csv', output_file='restaurants_cleaned.csv'):
    """
    Clean and prepare the restaurant dataset for Elasticsearch import
    """
    logging.info(f"Starting data cleaning process for {input_file}")
    
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
    
    # Clean numeric fields with progress bar
    for _ in tqdm(range(1), desc="Cleaning numeric fields"):
        # Clean AggregateRating - ensure it's numeric
        df['AggregateRating'] = pd.to_numeric(df['AggregateRating'], errors='coerce')
        
        # Clean Votes - ensure it's numeric
        df['Votes'] = pd.to_numeric(df['Votes'], errors='coerce')
        
        # Clean AverageCostForTwo - ensure it's numeric
        df['AverageCostForTwo'] = pd.to_numeric(df['AverageCostForTwo'], errors='coerce')
    
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
    
    # Handle City/Country/Continent
    def split_location(location_str):
        if pd.isna(location_str):
            return 'Unknown/Unknown/Unknown'
        
        parts = location_str.split('/')
        if len(parts) != 3:
            # If parts are not exactly 3, return None to filter out this row
            return None
        return '/'.join(parts)
    
    df['City/Country/Continent'] = df['City/Country/Continent'].apply(split_location)
    # Remove rows where City/Country/Continent is None
    df = df.dropna(subset=['City/Country/Continent'])
    
    # Validate coordinates
    def validate_coordinates(coord_str):
        if pd.isna(coord_str):
            return '[0, 0]'  # Default coordinates if missing
            
        # Check if it's already in [lat, lon] format
        if re.match(r'\[\s*[-+]?\d*\.?\d+\s*,\s*[-+]?\d*\.?\d+\s*\]', str(coord_str)):
            return coord_str
            
        try:
            # Try to extract lat and lon values
            match = re.search(r'\[\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\]', str(coord_str))
            if match:
                lat = float(match.group(1))
                lon = float(match.group(2))
                # Validate latitude range
                if lat < -90 or lat > 90:
                    lat = 0
                # Validate longitude range
                if lon < -180 or lon > 180:
                    lon = 0
                return f"[{lat}, {lon}]"
            else:
                return '[0, 0]'
        except:
            return '[0, 0]'
    
    df['Coordinates'] = df['Coordinates'].apply(validate_coordinates)
    
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
    # Use correct relative paths
    input_file = '../restaurants.csv'
    output_file = 'restaurants_cleaned.csv'
    clean_restaurant_data(input_file, output_file) 