"""
This module provides client and write functions to operate on influxdb
Author: 2021-11-23 havembha@gmail.com
"""
from influxdb_client import InfluxDBClient, WriteOptions

def JAInfluxdbWriteData( url, token, org, bucket, data):

    returnStatus = True
    _client = InfluxDBClient(url=url, token=token, org=org)

    _write_client = _client.write_api(write_options=WriteOptions(batch_size=500,
                                      flush_interval=10_000,
                                      jitter_interval=2_000,
                                      retry_interval=5_000,
                                      max_retries=5,
                                      max_retry_delay=30_000,
                                      exponential_base=2))
    try:
        returnStatus = _write_client.write(record=data,bucket=bucket, org=org,protocol='line')
        print("INFO data written to influxdb:|{0}, status:{1}|".format( data, returnStatus ))
    except Exception as err:
        print("ERROR JAInfluxdbWriteData() Could not insert record to influxdb, error:{0}".format(err ) )
        returnStatus = False
    _write_client.close()
    return returnStatus