"""
This module provides client and write functions to operate on influxdb
Author: 2021-11-23 havembha@gmail.com
"""
from influxdb_client import InfluxDBClient, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

def JAInfluxdbWriteData( url, token, org, bucket, data):

    returnStatus = "<Response [200]>"
    _client = InfluxDBClient(url=url, token=token, org=org)
    """
    _write_client = _client.write_api(write_options=WriteOptions(batch_size=500,
                                      flush_interval=10_000,
                                      jitter_interval=2_000,
                                      retry_interval=5_000,
                                      max_retries=5,
                                      max_retry_delay=30_000,
                                      exponential_base=2))
    """
    _write_client = _client.write_api(write_options=SYNCHRONOUS)

    try:
        result = _write_client.write(record=data,bucket=bucket, org=org,protocol='line')
        print("_Status_PASS_ data written to influxdb:|{0}, status:{1}|".format( data, returnStatus ))
        if result != None:
            returnStatus = "<Response [500]>"    
    except Exception as err:
        print("_Status_ERROR_ JAInfluxdbWriteData() Could not insert record to influxdb, error:{0}".format(err ) )
        returnStatus = "<Response [500]>"
    _write_client.close()
    return returnStatus