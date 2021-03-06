from __future__ import print_function

import csv
import json
from dateutil import parser
from StringIO import StringIO
from math import radians, sin, cos, sqrt, asin
import configparser

from pyspark import SparkContext


def valid_nonzero_float(string):
    '''
    True for a string that represents a nonzero float or integer

    Parameters
    ----------
    string : string, required
                String representing the property value

    Returns
    -------
    float
            If string can be represented as a valid nonzero float
    None
            Otherwise
    '''
    try:
        number = float(string)
        if number != 0.:
            return number
        else:
            return None
    except ValueError:
        return None


def parse_station_record(station_record):
    '''
    This function splits station record efficiently using csv package

    Input
    -----
    station_record : str
                One line containing air monitor reading

    Returns
    -------
    tuple
                Tuple characterizing station (station_id, latitude, longitude)
    '''
    f = StringIO(station_record.encode('ascii', 'ignore'))
    reader = csv.reader(f, delimiter=',')
    record = reader.next()

    state_id = record[0]
    # Filter out header, Canada, Mexico, US Virgin Islands, or Guam
    if state_id in ['State Code', 'CC', '80', '78', '66']:
        return None

    county_id = record[1]
    site_number = record[2]
    station_id = '|'.join([state_id, county_id, site_number])

    latitude = valid_nonzero_float(record[3])
    longitude = valid_nonzero_float(record[4])
    if not latitude or not longitude:
        return None

    datum = record[5]
    if datum not in ['WGS84', 'NAD83']:
        # Filter out old or malformed geospatial coorinates
        return None

    closed = record[10]
    if closed:
        closed_date = parser.parse(closed)
        history_span = parser.parse('1980-01-01')
        # Do not consider stations closed before January 1, 1980
        if closed_date < history_span:
            return None

    # Finally, if all checks are passed, return record for station
    return (station_id, latitude, longitude)


def calc_distance(lat1, lon1, lat2, lon2):
    '''
    Compute distance between two geographical points
    Source: https://rosettacode.org/wiki/Haversine_formula#Python

    Parameters
    ----------
    lat1 : float
    lon1 : float
            Latitude and longitude of the first geographical point

    lat2 : float
    lon2 : float
            Latitude and longitude of the second geographical point


    Returns
    -------
    float
            Distance between two points in kilometers
    '''
    R = 3959.  # Earth's radius in miles
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    lat1 = radians(lat1)
    lat2 = radians(lat2)
    a = sin(delta_lat / 2.0) ** 2 + \
        cos(lat1) * cos(lat2) * sin(delta_lon / 2.0) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def determine_grid_point_neighbors(rdd):
    '''
    Determine the list of stations within 50 miles of the current station

    Parameters
    ----------
    rdd : RDD
                RDD of air monitors readings

    Returns
    -------
    RDD
                RDDs of air monitors reading transformed to nearest grid points
    '''
    d_cutoff = 30.
    precision = 1  # Store one decimal place for distance in miles
    station_id = rdd[0]
    station_latitude = rdd[1]
    station_longitude = rdd[2]
    adjacent_grid_points = {}
    for grid in GRID:
        grid_id = grid["id"]
        grid_longitude = grid["lon"]
        grid_latitude = grid["lat"]
        d = calc_distance(grid_latitude, grid_longitude,
                          station_latitude, station_longitude)
        if d < d_cutoff:
            adjacent_grid_points[grid_id] = round(d, precision)
    return (station_id, adjacent_grid_points)


def main():

    # Read in data from the configuration file

    config = configparser.ConfigParser()
    config.read('../setup.cfg')

    s3 = 's3a://' + config["s3"]["bucket"] + '/'
    spark_url = 'spark://' + config["spark"]["dns"]

    # Create Spark context & session

    sc = SparkContext(spark_url, "Batch")

    # Read in json containing grid

    with open('grid.json', 'r') as f:
        raw_json = f.readline()

    global GRID
    GRID = json.loads(raw_json)

    # Start processing data files

    data_file = 'aqs_sites.csv'
    raw = s3 + data_file

    data_rdd = sc.textFile(raw, 3)

    stations = data_rdd.map(parse_station_record)\
                       .filter(lambda line: line is not None)\
                       .map(determine_grid_point_neighbors)\
                       .collectAsMap()

    with open('stations.json', 'w') as f:
        json.dump(stations, f)


if __name__ == '__main__':
    main()
