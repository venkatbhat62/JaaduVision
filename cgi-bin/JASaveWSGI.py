
"""
This Web Service saves the data received from remote hosts in json format 
Data passed
    job - mandatory - like OSStats, usageStats, alarmStats, logStats
    sent to pushgateway as job
    hostName - mandatory - host that is posting the data
    environment - optional - like dev, test, uat, prod
        default - test
    siteName - optional - like west, east, central, or site name with city name
        default - none (not used to differentiate the data)
    platformName - optional - platform name to associate this data to
        default - none (not used to differentiate the data)
    componentName - optional -  component to associate this data to
        default - none (not used to differentiate the data)
    Json data - key, value pairs
        while sending data to pushgateway,
        "jobName + key" is prepended to parameter name so that each metric name becomes unique
        value is in the form
        <timestamp> metric1=value1, metric2=value2... 

Return Result
    Perf stats are saved to a file whose fileName is passed in posted data
    Perf stats are also posted to to pushgateway or influxdb using jobname, instance
        one metric posted per lineReturn Result
    Logs are sent to loki
    trace info is sent to zipkin

"""

import time, threading, socket, socketserver 
#from http.server import HTTPServer, BaseHTTPRequestHandler
from wsgiref.simple_server import make_server, WSGIServer
from socketserver import ThreadingMixIn
from time import sleep

import os,sys,json,re
from datetime import datetime
import yaml
import requests
import JAGlobalLib 
from collections import defaultdict
from urllib.parse import urlparse
from urllib.parse import parse_qs
import random
from influxdb_client import InfluxDBClient, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

def JAInfluxdbWriteData( bucket, data, debugLevel=0):
    statusCode = False
    returnStatus = ''

    """
    _write_client = _client.write_api(write_options=WriteOptions(batch_size=500,
    flush_interval=10_000,
    jitter_interval=2_000,
    retry_interval=5_000,
    max_retries=5,
    max_retry_delay=30_000,
    exponential_base=2))
    """
    
    if influxDBWriteClient != None:
        try:
            result = influxDBWriteClient.write(record=data,bucket=bucket, org=org,protocol='line')
            if result != None:
                returnStatus = "<Response [500]>" 
                returnResult += ("_Status_ERROR_ Could not insert record to influxdb, data:{0}, result:|{1}|".format(data, result ))
            else:
                statusCode = True
                if debugLevel > 0:
                    returnResult += ("_Status_PASS_ data written to influxdb:|{0}, status:{1}|".format( data, returnStatus ))

        except Exception as err:
           returnResult += ("_Status_ERROR_ JAInfluxdbWriteData() Could not insert record to influxdb, error:{0}".format(err ) )
           returnStatus = "<Response [500]>"
    else:
        returnStatus = "_Status_ERROR_ InfluxDB Write Client not present, check InfluxDB config"

    return statusCode, returnStatus

def JASaveStatsExit( reason, statusCode, JASaveStatsStartTime):
    if re.match('^ERROR ', reason):
        message='ERROR JASaveWS.py() ' + reason + '<Response [500]>'
    elif re.match('^PASS ', reason):
        message='PASS  JASaveWS.py() ' + reason + '<Response [200]>'
    else:
        message='      JASaveWS.py() ' + reason

    returnResult = message
    JASaveStatsEndTime = datetime.now()
    JASaveStatsDuration = JASaveStatsEndTime - JASaveStatsStartTime
    JASaveStatsDurationInSec = JASaveStatsDuration.total_seconds()
    message = r'{0}, response time:{1} sec\n'.format( reason, JASaveStatsDurationInSec)

    JAGlobalLib.LogMsg(message, JALogFileName, True)
    returnResult += message
    return [ returnResult.encode('utf-8') ]

def JASaveStatsError(reason, statusCode,JASaveStatsStartTime ):
    return JASaveStatsExit('ERROR Could not save the data: ' + reason, statusCode, JASaveStatsStartTime)

def simple_app(environ, start_response):
    global JAInfluxdbURL, JAInfluxdbToken, JAInfluxdbOrg
    status = '200 OK'  # HTTP Status
    headers = [('Content-type', 'text/plain; charset=utf-8')]  # HTTP Headers
    start_response(status, headers)

    """
        ### create sessions for prometheus pushgateway, influxdb, loki and tempo
        self.sessionPushGateway = requests.session()
        self.sessionLoki = requests.session()
        self.sessionZipkin = requests.session()

        try:
            _client = InfluxDBClient(url=JAInfluxdbURL, token=JAInfluxdbToken, org=JAInfluxdbOrg)
            self.influxDBWriteClient = _client.write_api(write_options=SYNCHRONOUS)
        except Exception as err:
            self.influxbDBWriteClient = None
            print("ERROR Not able to create InfluxDBWriteClient with url:{0}, token:{1}, org:{2}".format(JAInfluxdbURL,JAInfluxdbToken, JAInfluxdbOrg))
    """
    returnResult=''
    JASaveStatsStartTime = datetime.now()
    try:
        contentLength = int(environ['CONTENT_LENGTH'])
        contentType = environ['CONTENT_TYPE']
        requestBody = environ['wsgi.input'].read(contentLength)
        print("DEBUG content length:{0}, content type:{1}, content:|{2}|\n".format(contentLength, contentType, requestBody ))

    except (TypeError, ValueError):
        returnResult="ERROR converting requestBody to string"
        requestBody = None

    if requestBody != None :
        try:
            postedData = json.loads(requestBody)
            print("DEBUG-2 read content length:{0}\n".format(contentLength))
        except:
            print("ERROR content length:{0}, content type:{1}, content:|{2}|\n".format(contentLength, contentType, requestBody ))
            return [returnResult.encode("ascii")]
    else:
        JASaveStatsError('ERROR zero content posted')
        return [returnResult.encode("utf-8")]
    
    # return JASaveStatsExit("PASS ", 200, JASaveStatsStartTime )

    if requestBody != None:
        ### prepare server side fileName to store data
        if JADirStats != None:
            if postedData['fileName'] == None:
                ### if valid JADirStats is present, expect fileName to be passed to save the data locally 
                return JASaveStatsError('fileName not passed')
            else:
                fileName = JADirStats + '/' + postedData['fileName']
        else:
            fileName = None

        postToZipkin = postToLoki = False

        ### get the parameters passed
        if postedData['jobName'] == None:
            return JASaveStatsError('jobName not passed')
        else:
            jobName = postedData['jobName']
            if jobName == 'loki':
                postToLoki = True
            elif jobName == 'zipkin':
                postToZipkin = True

        if postedData['hostName'] == None:
            return JASaveStatsError('hostName not passed')
        else:
            hostName = postedData['hostName']

        if 'saveLogOnWebServer' in postedData:
            saveLogsOnWebServer = postedData['saveLogsOnWebServer']
        else:
            saveLogsOnWebServer = 'no'

        ### for stats, use web server level setting to save the stats on web server
        ### for logs, use the value posted from client to save the logs on web server
        saveOnWebServer = 0
        if postToLoki == True:
            if  saveLogsOnWebServer == 'yes':
                saveOnWebServer = 1
        else:
            if JASaveStatsOnWebServer == 'yes':
                saveOnWebServer = 1

        ## make initial part of pushgateway URL 
        pushGatewayURL = JAPushGatewayURL + "/metrics/job/" + jobName + "/instance/" + hostName
        prefixParamsForFile = ''
        appendToURL = ''

        #instance=\"' + hostName + '\", site=\"' + siteName + '\", component=\"' + componentName + '\", platform=\"' + platformName + '\",
        labelParams = ''
        comma = ''
        ## make initial part of Lokigateway URL
        lokiGatewayURL = JALokiGatewayURL + "/api/prom/push"

        if postedData['debugLevel'] == None:
            debugLevel = 0
        else:
            debugLevel = int(postedData['debugLevel'])

        try:
            if postedData['DBType'] == 'Influxdb':
                JADBTypeInfludb = True
            else:
                JADBTypeInfludb = False
        except:
            ## default DBType is Prometheus
            JADBTypeInfludb = False
        
        if JADBTypeInfludb == True:
            ### ensure influxdb related values are passed from client or available in server side config file
            try:
                if postedData['InfluxdbBucket'] != None :
                    JAInfluxdbBucket = postedData['InfluxdbBucket']
            except:
                if debugLevel > 0 :
                    returnResult += ("INFO JASaveWS.py InfluxdbBucket not passed, using the default value:{0}".format(JAInfluxdbBucket))
            try:
                if postedData['InfluxdbOrg'] != None :
                    JAInfluxdbOrg = postedData['InfluxdbOrg']
            except:
                if debugLevel > 0 :
                    returnResult += ("INFO JASaveWS.py InfluxdbOrg not passed, using the default value:{0}".format(JAInfluxdbOrg))

        prefixParamsForFile = ''
        comma = ''

        if postedData['environment'] != None:
            appendToURL = "/environment/" + postedData['environment'] 
            prefixParamsForFile = "environment=" + postedData['environment']
            if JADBTypeInfludb == True :
                ### influxdb does not need double quote around text tags
                labelParams = 'environment=' + postedData['environment']    
            else:
                labelParams = 'environment=\"' + postedData['environment'] + '\"'
            comma = ','

        else:
            ### DO NOT pass empty tag to Influxdb, pass it for Prometheus
            if JADBTypeInfludb == False:
                prefixParamsForFile = "environment="
                comma = ','

        if postedData['platformName'] != None:
            appendToURL = appendToURL + "/platform/" + postedData['platformName']
            prefixParamsForFile = prefixParamsForFile + comma + "platform=" + postedData['platformName']
            if JADBTypeInfludb == True :
                labelParams += comma + 'platform=' + postedData['platformName']    
            else:
                labelParams += comma + 'platform=\"' + postedData['platformName'] + '\"'
            comma = ','
        else:
            ### DO NOT pass empty tag to Influxdb, pass it for Prometheus
            if JADBTypeInfludb == False:
                prefixParamsForFile = prefixParamsForFile + comma + "platform="

        if postedData['siteName'] != None:
            appendToURL = appendToURL + "/site/" + postedData['siteName'] 
            prefixParamsForFile = prefixParamsForFile + comma + "site=" + postedData['siteName']
            siteName = postedData['siteName']
            if JADBTypeInfludb == True :
                labelParams += comma + 'site=' + postedData['siteName']    
            else:
                labelParams += comma + 'site=\"' + postedData['siteName'] + '\"'
            comma = ','
        else:
            ### DO NOT pass empty tag to Influxdb, pass it for Prometheus
            if JADBTypeInfludb == False:
                prefixParamsForFile = prefixParamsForFile + comma + "site="

        if postedData['componentName'] != None:
            appendToURL = appendToURL + "/component/" + postedData['componentName']
            prefixParamsForFile = prefixParamsForFile + comma + "component=" + postedData['componentName']
            if JADBTypeInfludb == True :
                labelParams += comma + 'component=' + postedData['componentName']    
            else:
                labelParams += comma + 'component=\"' + postedData['componentName'] + '\"'
            comma = ','
        else:
            ### DO NOT pass empty tag to Influxdb, pass it for Prometheus
            if JADBTypeInfludb == False:
                prefixParamsForFile = prefixParamsForFile + comma + "component=" 

        if hostName != None:
            prefixParamsForFile = prefixParamsForFile + comma + "host=" + hostName
            if JADBTypeInfludb == True :
                labelParams += comma + 'instance=' + hostName    
            else:
                labelParams += comma + 'instance=\"' + hostName + '\"'

        if debugLevel > 1:
            if JADBTypeInfludb == False:
                returnResult += ('DEBUG-2 JASaveWS.py Stats Dir:' + JADirStats + ', fileName: ' + fileName + ', pushGatewayURL: ' + pushGatewayURL + ', appendToURL: ' + appendToURL + ', prefixParamsForFile: |' + prefixParamsForFile + ', ZipkinURL:|'+ JAZipkinURL + '|\n')
            else:
                returnResult += ("DEBUG-2 JASaveWS.py Stats Dir:|{0}, fileName:{1}, influxdbURL:|{2}|, influxdbBucket:|{3}|, influxdbOrg:|{4}|, prefixParamsForFile:|{5}|, ZipkinURL:|{6}|,labelParams:|{6}|".format(JADirStats, fileName, JAInfluxdbURL, JAInfluxdbBucket, JAInfluxdbOrg, prefixParamsForFile, JAZipkinURL, labelParams ))
        
        ### Now post the data to web server
        headersForPushGateway= {'Content-type': 'application/x-www-form-urlencoded', 'Accept': '*/*', 'Connection': 'keep-alive'}
        headersForLokiGateway = {'Content-Type': 'application/json','Connection': 'keep-alive'}
        headersForZipkin = {'Content-Type': 'application/json', 'Connection': 'keep-alive'}

        if JADisableWarnings == True:
            requests.packages.urllib3.disable_warnings()

        influxdbDataArrayToPost = []
    
        ### open the file in append mode and save data
        ###   only one posting expected at a time from a given host.
        ###   since fileName is hostName specific, this will not be an issue while multiple threads are running
        try:
            if fileName != None:
                if saveOnWebServer == 1:
                    try:
                        ### save data locally if fileName is specified
                        fpo = open( fileName, 'a')
                        if debugLevel > 0:
                            returnResult += ('DEBUG-1 JASaveWS.py fileName: {0}, postToLoki {1}\n'.format(fileName, postToLoki))
                    except OSError as err:
                        fpo = None
                        returnResult += ("507 {0}, ERROR opening file to save data on web server".format(err))

            ### while writing values to file and posting to pushgateway, skip below keys
            skipKeyList = ['DBType','InfluxdbBucket','InfluxdbOrg','jobName','debugLevel','fileName','environment','siteName','platformName','componentName','hostName','saveLogsOnWebServer']

            statsType = None
            statsToPost = ''
            postData = False

            metricsVariablesToBePosted = {}

            errorPostingPrometheusGateway = errorPostingInfluxDB = errorPostingLoki = False

            for key, value in postedData.items():
                if key in skipKeyList:
                    if debugLevel > 3:
                        returnResult += ('DEBUG-4 JASaveStats.py skipping key:{0} this data not added to stats key'.format(key))
                    continue

                if debugLevel > 1:
                    returnResult += ('DEBUG-2 JASaveWS.py processing key: {0}, value: {1}'.format(key, value))
                    ### SKIP LogStats, OSStats, loki , zipkin
                    if value == 'LogStats' or value == 'OSStats' or value == 'loki' or value == 'zipkin':
                        statsType = value
                        continue

                ### if fileName is passed and saveOnWebServer is set to 1, write data to file
                if fileName != None:
                    if saveOnWebServer == 1 and fpo != None:
                        try:   
                            ### save this data with prefixParamsForFile that identifies statsType, environment, site, platform, component, host 
                            fpo.write( '{0},{1},{2}\n'.format(prefixParamsForFile, key, value ) )

                            if debugLevel > 1:
                                returnResult += ('DEBUG-2 JASaveWS.py wrote data: {0},{1},{2} to file'.format(prefixParamsForFile,key, value))
                        except OSError as err:
                            returnResult += ("500 ERROR {0}, not able to save the stats in file on web server".format(err))
                            fpo = None
               
                ### log lines to loki
                if postToLoki == True and errorPostingLoki == False:
                    ### need to post log lines to loki
                    ### data posted has lines with , separation
                    """
                    Post log lines to Loki with labels instance, site, component, and platform. Values of these labels are from posted values
                    instance - hostName
                    site - siteName
                    component - componentName
                    platform - platformName

                    Data posted is of the form:
                    2022-05-30T22:01:44.767078 Trace 0000000000000a3b Service1 test trace line 1\n
                    2022-05-30T22:01:44.767273 Trace 0000000000000a3c Service1 test trace line 3\n'
                    """
                    ### regular expression definition for timestamp string at the start of line
                    # with T separator
                    myTimeStampRegexT = re.compile(r'(\d\d\d\d-\d\d-\d\d[T| ]\d\d:\d\d:\d\d[\.|,]\d+)') 
                    # with space separator 
                    #myTimeStampRegexSpace = re.compile(r'(\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)') 
                   
                    ### tempLines = value.split('\n')
                    tempLines = value.split("__NEWLINE__")
                    lineCount = 1
                    for line in tempLines:
                        line = line.replace("__NEWLINE__", "")
                        if len(line) > 0:
                            ### if current line has timestamp in standard ISO format, use it
                            try:
                                tempDateTime = myTimeStampRegexT.search(line)
                                if tempDateTime != None:
                                    myDateTime = str(tempDateTime.group()) + "-00:00"
                                #else:
                                #    tempDateTime = myTimeStampRegexSpace.search(line)
                                #    if tempDateTime != None:
                                #        myDateTime = str(tempDateTime.group()) + "-00:00"
                                #        ### replace space with T to bring it to isoformat required by Loki
                                #        myDateTime = myDateTime.replace(" ", "T")
                                else:
                                    curr_datetime = datetime.utcnow()
                                    curr_datetime = curr_datetime.isoformat('T')
                                    myDateTime = str(curr_datetime) + "-00:00"

                            except Exception as err:
                                returnResult += ("myTimeStampRegex.search() generated exception:" + str(err))
                                curr_datetime = datetime.utcnow()
                                curr_datetime = curr_datetime.isoformat('T')
                                myDateTime = str(curr_datetime) + "-00:00"

                            # 'labels': '{instance=\"' + hostName + '\", site=\"' + siteName + '\", component=\"' + componentName + '\", platform=\"' + platformName + '\"}',
                            payload = {
                                'streams': [
                                    {
                                        'labels': '{' + labelParams + '}',
                                        'entries': [
                                            {
                                                'ts': myDateTime,
                                                'line': " " + line
                                            }
                                        ]
                                    }
                                ]
                            }
                            payload = json.dumps(payload)
                            if debugLevel > 2:
                                returnResult += ("DEBUG-3 JASaveWS.py payload:|{0}|, lokiGatewayURL:|{1}|\n".format(payload, lokiGatewayURL))
                            try:
                                tempReturnResult = requests.post( lokiGatewayURL, data=payload, headers=headersForLokiGateway)
                                tempReturnResult.raise_for_status()
                            
                                if debugLevel > 1:
                                    returnResult += ('DEBUG-2 JASaveWS.py log line: {0} posted to loki with result:{1}\n'.format(line,tempReturnResult.text))
                            except requests.exceptions.RequestException as err:
                                ### DO NOT abort here on error, continue to post data to other destinations 
                                returnResult = returnResult + "ERROR posting logs to Loki, returnResult:{0}".format(err)
                                errorPostingLoki = True
                                break

                            lineCount += 1
                
                elif postToZipkin == True:
                    """ content posted is the form:
                    id=1,name=./JATest.log.20220528,serviceName=TestTrace,traceId=0000000000000116,timestamp=1653771104716898,duration=1000\n
                    id=2,name=./JATest.log.20220528,serviceName=TestTrace,traceId=0000000000000116,timestamp=1653771104718201,duration=1000\n
                    id=3,name=./JATest.log.20220528,serviceName=TestTrace,traceId=0000000000000117,timestamp=1653771104718524,duration=1000\n
                    """

                    traceLines = value.split("\\n")
                    if debugLevel > 0:
                        returnResult += ('DEBUG-1 JASaveWS.py number of traces to post:{0}\n{1}\n'.format( len(traceLines), traceLines))
                    id ="1234"

                    for traceLine in traceLines:
                        ### process each line having var=value,
                        ### separate variable and value pairs using comma as separator
                        items = traceLine.split(',')
                        
                        ### SKIP empty line
                        if len(items) <= 0 :
                            if debugLevel > 2:
                                returnResult += ("DEBUG-3 JASaveWS.py no data in traceLine:{0}, items:{1}\n".format(traceLine, items))
                            continue

                        traceParameters = {}

                        ### assign default values so that these can be checked later
                        traceParameters['status'] = '200'
                        traceParameters['parentId'] = traceParameters['id'] = '9999'
                        traceParameters['duration'] = '1000'
                        traceParameters['serviceName'] = traceParameters['name'] = 'NA'

                        for item in items:
                            ### expect the item in the form paramName=value
                            ### separate paramName and store it in metricsVariablesToBePosted hash
                            variableNameAndValues = re.split('=', item)
                            variableName = variableNameAndValues[0]
                            if len(variableNameAndValues) > 1:
                                traceParameters[variableName] = variableNameAndValues[1] 

                        try:
                            payload = [{
                                "id": traceParameters['id'],
                                "traceId":  traceParameters['traceId'] ,
                                "timestamp": int(traceParameters['timestamp']),
                                "duration": int(traceParameters['duration']),
                                "name":  traceParameters['name'],
                                "parentId": traceParameters['parentId'],
                                "tags": {
                                     "instance": hostName,
                                     "status.code": traceParameters['status']
                                     #"http.method": "GET",
                                     #"http.path": "/api"
                                },
                                "localEndpoint": {
                                    "serviceName":  traceParameters['serviceName'] 
                                }
                            }]
                            payload = json.dumps(payload)
                            if debugLevel > 2:
                                returnResult += ("DEBUG-3 JASaveWS.py payload:|{0}|, ZipkinURL:|{1}|\n".format(payload, JAZipkinURL))
                            try:
                                tempReturnResult = requests.post( JAZipkinURL, data=payload, headers=headersForZipkin)
                                if debugLevel > 0:
                                    returnResult += ('DEBUG-1 JASaveWS.py data: {0} posted to zipkin with result:{1}\n\n'.format(payload,tempReturnResult))
                            except requests.exceptions.RequestException as err:
                                 returnResult = returnResult + "ERROR posting trace to zipkin, traceToPost:{0}, returnResult:{1}".format(payload, err)
                                 errorPostingZipkin = True
                        except:
                           returnResult += 'ERROR timestamp data not posted to zipkin, items passed:{0}'.format(items)
                           errorPostingZipkin = True

                ### post stats
                else:
                    ### timeStamp=2021-09-28T21:06:42.526907,TestStats_pass=0.05,TestStats_fail=0.02,TestStats_count=0.02,TestStats_key1_sum=0.40,TestStats_key2_sum=0.20,TestStats_key1_delta=-0.05,TestStats_key2_delta=-0.03
                    ### convert data 
                    ### from p1=v1,p2=v2,... 
                    ### to 
                    ###    p1 v1
                    ###    p2 v2
                    ### replace =, remove space, and make one metric per line to post to PushGatewayURL
                    valuePairs = str(value)
                    items = valuePairs.split(',')
                
                    ### remove timeStamp=value from the list. Prometheous scraper uses scraping time for reference.
                    ###    this sample from source can't be used for time series graphs
                    tempSampleDateTime = items.pop(0)
                    ### only timestamp present, no data, skip it
                    if len(items) == 0 :
                        continue
                
                    ### if stats are to be posted for label, use separate variable to track it
                    statsToPostForLabel = defaultdict(dict)

                    if JADBTypeInfludb == True :
                        ### sampleDateTimeString is of the format timestamp=YYYY-MM-DDTHH:MM:SS.uuuuuu
                        ###   extract only time string
                        tempSampleDateTimeArray = re.split('=',tempSampleDateTime) 
                        ### while inserting to influxdb, use the timestamp posted by client in pico second 
                        sampleTimeFloat = datetime.strptime(tempSampleDateTimeArray[1], "%Y-%m-%dT%H:%M:%S.%f")
                        sampleTime = "{0:.0f}".format(sampleTimeFloat.timestamp()*1000000000)

                        ### holds data for entire row, including one or more variable name=value pairs
                        ### measurement,tag1=value1,tag2=value2[,...] field1=value1,field2=value2[,...]
                        ### add space separator between tag and field values 
                        influxdbRowData = "{0},{1} ".format(jobName,labelParams)
                        ### set this to ,(comma) after appending first field1=value1 to 
                        comma = ''
                
                    for item in items:
                        labelPrefix = ''
                        ### expect the item in the form paramName=value
                        ### separate paramName and store it in metricsVariablesToBePosted hash
                        variableNameAndValues = re.split('=', item)
                        variableName = variableNameAndValues[0]
                        if len(variableNameAndValues) > 1:
                            # if current name is already present, SKIP current name=value pair
                            if variableName in metricsVariablesToBePosted.keys() :
                                ## param name already present, SKIP this pair
                                returnResult += ("WARN JASaveStats.py metrics variable name:{0} already present, SKIPing this item:{1}".format(variableName, item))
                                continue
                            else:
                                ### new name and value
                                metricsVariablesToBePosted[variableName] = True
                            
                                ### this format needs to match the format used in JAGatherLogStats.py function JAProcessLogFile()
                                myResults = re.search(r'_:(\w+):', variableName)
                                if myResults != None:
                                    ### if data posted has embeded label in the form <name>_:<label>:<name>_*,
                                    ###    extract <label> from that variable name, 
                                    ###    replace :<label>: for all the variable associated with current key
                                    ###    post the data with this label to prometheus gateway or influxb separately with client=<labelName>.
                                    ### timeStamp=2021-10-31T15:24:22.480140,TestStatsWithLabel_:client1:key1_average=32.50,TestStatsWithLabel_:client1:key2_average=16.25,TestStatsWithLabel_:client2:key1_average=32.50,TestStatsWithLabel_:client2:key2_average=16.25
                                    ###   
                                    labelPrefix = myResults.group(1)
                                    if debugLevel > 2 :
                                        print ("DEBUG-3 JASaveStats.py label:|{0}|, variableName BEFORE removing the label:|{1}|".format(labelPrefix, variableName))
                                    if labelPrefix != None:
                                        ### this format needs to match the format used in JAGatherLogStats.py function JAProcessLogFile()
                                        replaceString = '_:{0}:'.format(labelPrefix)
                                        variableName = re.sub(replaceString,'_',variableName)
                                    if debugLevel > 2 :
                                        print ("DEBUG-3 JASaveStats.py, label:|{0}|, variableName AFTER removing the label:|{1}|".format(labelPrefix, variableName))

                                    if JADBTypeInfludb == True :
                                        ### for influxdb, need to post these later along with label
                                        if labelPrefix in statsToPostForLabel:
                                            ### separate fields with comma
                                            statsToPostForLabel[labelPrefix] += ',{0}={1}'.format(variableName, variableNameAndValues[1])                                
                                        else:
                                            ### first time, no comma
                                            statsToPostForLabel[labelPrefix] = '{0}={1}'.format(variableName, variableNameAndValues[1])
                                    else:
                                        ### for prometheus, need to post these later along with label
                                        if labelPrefix in statsToPostForLabel:
                                            statsToPostForLabel[labelPrefix] += '{0} {1}\n'.format( variableName, variableNameAndValues[1])                                
                                        else:
                                            statsToPostForLabel[labelPrefix] = '{0} {1}\n'.format( variableName, variableNameAndValues[1])
    
                                    if debugLevel > 2 :
                                        print ("DEBUG-3 JASaveStats.py, statsToPostForLabel[{0}]:|{1}|".format(labelPrefix,statsToPostForLabel[labelPrefix]))
                                    postData = True
                                else:
                                    if JADBTypeInfludb == True :
                                        ### append fieldN=valueN to row data
                                        influxdbRowData += '{0}{1}={2}'.format(comma, variableName, variableNameAndValues[1])
                                        ### need to separate next field with comma
                                        comma = ','
                                        if debugLevel > 2:
                                            returnResult += ("DEBUG-3 JASaveStats.py after appending item:{0}, influxRowData:|{1}|".format(item, influxdbRowData) )
                                    else:
                                        statsToPost += '{0} {1}\n'.format( variableName, variableNameAndValues[1])
                                        if debugLevel > 2: 
                                            returnResult += ('DEBUG-3 JASaveStats.py item :{0}, itemToPost:{1} {2}\n'.format(item,variableName, variableNameAndValues[1] ) )
                                    postData = True

                        else:
                            returnResult += ('WARN JASaveStats.py item:{0} is NOT in paramName=value format, DID NOT post this to prometheus\n'.format(item))

                    if JADBTypeInfludb == True:

                        if len(statsToPostForLabel) > 0:
                            ### if label values are present, add separate row per label to influxdbDataArrayToPost
                            for label, labelValue in statsToPostForLabel.items():
                                ### prepare one row data per label
                                influxdbRowData = "{0},{1},client={2} {3} {4}".format(jobName,labelParams, label,labelValue,sampleTime)
                                influxdbDataArrayToPost.append(influxdbRowData)
                                if debugLevel > 2:
                                    returnResult += ("DEBUG-3 JASaveStats.py influxdbRowData for label:|{0}|, influxdbRowData:|{1}|".format(label,influxdbRowData))
                        else :
                             ### measurement,tag1=value1,tag2=value2[,...] field1=value1,field2=value2[,....] timestamp
                             #   add space between fieldN=valueN and timestamp, and append to array
                             influxdbDataArrayToPost.append(influxdbRowData + " " + sampleTime)

                    else:
                        if errorPostingPrometheusGateway == False:
                            try:
                                for label, labelValue in statsToPostForLabel.items():
                                    tempReturnResult = requests.post( pushGatewayURL + appendToURL + "/client/" + label, data=labelValue, headers=headersForPushGateway)
                                    if debugLevel > 0:
                                        returnResult += ('DEBUG-1 JASaveStats.py label:|{0}| and data:|{1}| posted to prometheus push gateway with result:{2}\n\n'.format(label, labelValue,tempReturnResult))
                            except requests.exceptions.RequestException as err:
                                returnResult = returnResult + "ERROR posting data to prometheus gateway, returnResult:{0}".format(err)
                                errorPostingPrometheusGateway = True    

            #### now post the data
            if postData == True :
                if JADBTypeInfludb == True :
                    try:
                        tempStatus, tempReturnResult = JAInfluxdbWriteData(JAInfluxdbBucket, influxdbDataArrayToPost, debugLevel)
                        if tempStatus == False:
                            returnResult = returnResult + "ERROR posting data to influxDB, returnResult:{0}".format(tempReturnResult)
                        else:
                            if debugLevel > 0:
                                returnResult += ("DEBUG-1 JASaveStats.py data: {0} posted to influxdb with returnStatus:|{1}|".format(influxdbDataArrayToPost, tempReturnResult ))
                            if fpo != None:
                                fpo.write("influxDataArrayToPost:|{0}|, returnResult:|{1}|".format(influxdbDataArrayToPost, tempReturnResult))
                    except Exception as err:
                        returnResult = returnResult + "ERROR posting data to influxDB, returnResult:{0}".format(err)
                        errorPostingInfluxDB = True
                else:
                     if errorPostingPrometheusGateway == False:
                         try:
                             tempReturnResult = requests.post( pushGatewayURL + appendToURL, data=statsToPost, headers=headersForPushGateway)
                             if debugLevel > 0:
                                 returnResult += ('DEBUG-1 JASaveStats.py data: {0} posted to prometheus push gateway with result:{1}\n\n'.format(statsToPost,tempReturnResult))
                         except requests.exceptions.RequestException as err:
                             returnResult = returnResult + "ERROR posting data to prometheus push gateway, returnResult:{0}".format(err)
                             errorPostingPrometheusGateway = True

            if fileName != None:
                if saveOnWebServer == 1: 
                    if fpo != None:
                        fpo.close()

        except OSError as err:
            JASaveStatsError("{0}".format(err) )

        if len(returnResult) == 0:
            returnResult='PASS - Saved data, postToLoki:{0}, postToZipkin:{1}, JADBTypeInfludb:{2}'.format( postToLoki, postToZipkin, JADBTypeInfludb)

        ### print status and get out
        return JASaveStatsExit(str(returnResult), 200, JASaveStatsStartTime )

class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    pass


SaveStatsStartTime = datetime.now()
JAPushGatewayURL = JALokiGatewayURL = None

### read global parameters
with open('JAGlobalVars.yml','r') as file:
    JAGlobalVars = yaml.load(file, Loader=yaml.FullLoader)
    JALogDir = JAGlobalVars['JALogDir']
    JADisableWarnings = JAGlobalVars['JADisableWarnings']
    JALogFileName = JALogDir + "/" + JAGlobalVars['JASaveStats']['LogFileName']
    if JAGlobalVars['JASaveStats']['Dir'] != None:
        JADirStats = JAGlobalVars['JASaveStats']['Dir']
        if JADirStats == 'None' or JADirStats == '':
            JADirStats =  None
    else:
      # Dir to store stats not specified, DO NOT save stats locally
      JADirStats = None

    ### global setting for all hosts, whether to save stats on web server
    JASaveStatsOnWebServer = JAGlobalVars['JASaveStats']['SaveStatsOnWebServer']
    if JASaveStatsOnWebServer == 'True' or JASaveStatsOnWebServer == True:
       JASaveStatsOnWebServer = 'yes'
    else:
       JASaveStatsOnWebServer = 'no'
    ### URL to send the data to prometheus push gateway
    JAPushGatewayURL = JAGlobalVars['JASaveStats']['PushGatewayURL']

    ### URL to send the log lines to Loki gateway
    JALokiGatewayURL = JAGlobalVars['JASaveStats']['LokiGatewayURL']

    ### read configured number of threads value
    try:
        JANumberOfThreads = int(JAGlobalVars['JASaveStats']['NumberOfThreads'])
    except:
        ### default number of threads
        JANumberOfThreads = 100

    try:
        ### URL to send the data to influxdb
        JAInfluxdbURL = JAGlobalVars['JASaveStats']['InfluxdbURL']
        if JAGlobalVars['JASaveStats']['InfluxdbURL'] != None:
            ## influlxdb - org, bucket, token
            JAInfluxdbOrg = JAGlobalVars['JASaveStats']['InfluxdbOrg']
            JAInfluxdbToken = JAGlobalVars['JASaveStats']['InfluxdbToken']
            ## default bucket if client does not pass one
            JAInfluxdbBucket = JAGlobalVars['JASaveStats']['InfluxdbBucket']
    except:
        JAInfluxdbURL = JAInfluxdbOrg = JAInfluxdbToken = JAInfluxdbBucket = ''

    try:
        JAZipkinURL = JAGlobalVars['JASaveStats']['ZipkinURL']
    except:
        JAZipkinURL = ''
    file.close() 

    if JAPushGatewayURL == None or JALokiGatewayURL == None:
        JASaveStatsError('config error - need valid JAPushGatewayURL and JALokiGatewayURL')

class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
            pass

httpd = make_server('', 9060, simple_app, ThreadingWSGIServer)
print('Listening on port 9060....')
httpd.serve_forever()
