#!/usr/bin/python3
"""
This script saves the data received from remote hosts in json format 

Parameters Passed
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
 Data is saved to a file whose fileName is passed in posted data
 Post the data to pushgateway using jobname, instance
   one metric posted per line

2021-07-11 havembha@gmail.com
    Initial version 

2021-09-11 havembha@gmaill.com
    Skipped storing data locally on server if JADirStats is not specified or empty or set to "None"
    Added capability to save log lines to the same stats file and post the log lines to loki URL

2021-10-31 havembha@gmail.com
    Searched the variable name for the pattern :<label>:, 
    if present, extracted label, removed it from variable name, and posted those values separately with label
    this is to allow aggregation / filtering using label values in dashboard menu 

2021-11-21 havembha@gmail.com
    Added option to insert data to influxdb with the time stamp sent from client.
    This enables historic data to be sent to influxdb with original timestamp at which the sample was taken.
    Whenever guranteed tracking is needed, use this influxdb option
    parameter sent from client - DBType - values - influxdb or prometheus (default - prometheus)
    InfluxdbURL parameter defined in JAGlobalVars.yml is used to send the data to.

2022-05-28 avembha@gmail.com
    Added capability to insert trace events to zipkin when DBType posted is zipkin
    
"""
import os,sys,json,re
from datetime import datetime
import yaml
import requests
import JAGlobalLib, JAInfluxdbLib
from collections import defaultdict

def JASaveStatsExit(reason):
    if re.match('^ERROR ', reason):
        print('ERROR JASaveStats.py() ' + reason + '<Response [500]>')
    elif re.match('^PASS ', reason):
        print('PASS  JASaveStats.py() ' + reason + '<Response [200]>')
    else:
        print('      JASaveStats.py() ' + reason)

    JASaveStatsEndTime = datetime.now()
    JASaveStatsDuration = JASaveStatsEndTime - JASaveStatsStartTime
    JASaveStatsDurationInSec = JASaveStatsDuration.total_seconds()
    JAGlobalLib.LogMsg(reason + ', response time:{JASaveStatsDurationInSec} sec\n', JALogFileName, True)
    sys.exit()

def JASaveStatsError(reason):
    print ('ERROR Could not save the data: ' + reason)
    JASaveStatsExit(reason)

JASaveStatsStartTime = datetime.now()

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

contentLength = int(os.environ["CONTENT_LENGTH"])
reqBody = sys.stdin.read(contentLength)
postedData = defaultdict(dict)
postedData = json.loads(reqBody)
print('Content-Type: text/html; charset=utf-8\n')

returnResult=''

### prepare server side fileName to store data
if JADirStats != None:
    if postedData['fileName'] == None:
        ### if valid JADirStats is present, expect fileName to be passed to save the data locally 
        JASaveStatsError('fileName not passed')
    else:
        fileName = JADirStats + '/' + postedData['fileName']
else:
    fileName = None

postToZipkin = postToLoki = False

if postedData['jobName'] == None:
    JASaveStatsError('jobName not passed')
else:
    jobName = postedData['jobName']
    if jobName == 'loki':
        postToLoki = True
    elif jobName == 'zipkin':
        postToZipkin = True

if postedData['hostName'] == None:
    JASaveStatsError('hostName not passed')
else:
    hostName = postedData['hostName']

if JAPushGatewayURL == None or JALokiGatewayURL == None:
    JASaveStatsError('config error - need valid JAPushGatewayURL and JALokiGatewayURL')

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
            print("INFO JASaveStats.py InfluxdbBucket not passed, using the default value:{0}".format(JAInfluxdbBucket))
   
    try:
       if postedData['InfluxdbOrg'] != None :
            JAInfluxdbOrg = postedData['InfluxdbOrg']
    except:
        if debugLevel > 0 :
            print("INFO JASaveStats.py InfluxdbOrg not passed, using the default value:{0}".format(JAInfluxdbOrg))

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
        print('DEBUG-2 JASaveStats.py Stats Dir:' + JADirStats + ', fileName: ' + fileName + ', pushGatewayURL: ' + pushGatewayURL + ', appendToURL: ' + appendToURL + ', prefixParamsForFile: |' + prefixParamsForFile + ', ZipkinURL:|'+ JAZipkinURL + '|\n')
    else:
        print("DEBUG-2 JASaveStats.py Stats Dir:|{0}, fileName:{1}, influxdbURL:|{2}|, influxdbBucket:|{3}|, influxdbOrg:|{4}|, prefixParamsForFile:|{5}|, ZipkinURL:|{6}|,labelParams:|{6}|".format(JADirStats, fileName, JAInfluxdbURL, JAInfluxdbBucket, JAInfluxdbOrg, prefixParamsForFile, JAZipkinURL, labelParams ))
### Now post the data to web server
headersForPushGateway= {'Content-type': 'application/x-www-form-urlencoded', 'Accept': '*/*'}
headersForLokiGateway = {'Content-Type': 'application/json'}
headersForZipkin = {'Content-Type': 'application/json'}

if JADisableWarnings == True:
    requests.packages.urllib3.disable_warnings()

influxdbDataArrayToPost = []

### open the file in append mode and save data
try:
    if fileName != None:
        if saveOnWebServer == 1:
            try:
                ### save data locally if fileName is specified
                fpo = open( fileName, 'a')
                if debugLevel > 0:
                    print('DEBUG-1 JASaveStats.py fileName: {0}, postToLoki {1}'.format(fileName, postToLoki))
            except OSError as err:
                fpo = None
                print("507 {0}, ERROR opening file to save data on web server".format(err))

    ### while writing values to file and posting to pushgateway, skip below keys
    skipKeyList = ['DBType','InfluxdbBucket','InfluxdbOrg','jobName','debugLevel','fileName','environment','siteName','platformName','componentName','hostName','saveLogsOnWebServer']

    statsType = None
    statsToPost = ''
    postData = False

    metricsVariablesToBePosted = {}

    errorPostingPrometheusGateway = errorPostingInfluxDB = errorPostingLoki = False
    
    for key, value in postedData.items():

        if key not in skipKeyList:
            if debugLevel > 1:
                print('DEBUG-2 JASaveStats.py processing key: {0}, value: {1}'.format(key, value))
                
            ### SKIP LogStats, OSStats, loki , zipkin
            if value == 'LogStats' or value == 'OSStats' or value == 'loki' or value == 'zipkin':
                statsType = value
                continue

            if fileName != None:
                if saveOnWebServer == 1 and fpo != None:
                    try:   
                        ### save this data with prefixParamsForFile that identifies statsType, environment, site, platform, component, host 
                        fpo.write( '{0},{1},{2}\n'.format(prefixParamsForFile, key, value ) )

                        if debugLevel > 1:
                            print('DEBUG-2 JASaveStats.py wrote data: {0},{1},{2} to file'.format(prefixParamsForFile,key, value))
                    except OSError as err:
                        print("500 ERROR {0}, not able to save the stats in file on web server".format(err))
                        fpo = None

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
                myTimeStampRegexT = re.compile(r'(\d\d\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)') 
                # with space separator 
                myTimeStampRegexSpace = re.compile(r'(\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)') 

                tempLines = value.split('\n')
                lineCount = 1
                for line in tempLines:
                    ### if current line has timestamp in standard ISO format, use it
                    try:
                        tempDateTime = myTimeStampRegexT.search(line)
                        if tempDateTime != None:
                            myDateTime = str(tempDateTime.group()) + "-00:00"
                        else:
                            tempDateTime = myTimeStampRegexSpace.search(line)
                            if tempDateTime != None:
                                myDateTime = str(tempDateTime.group()) + "-00:00"
                                ### replace space with T to bring it to isoformat required by Loki
                                myDateTime.replace(" ", "T")
                            else:
                                curr_datetime = datetime.utcnow()
                                curr_datetime = curr_datetime.isoformat('T')
                                myDateTime = str(curr_datetime) + "-00:00"
                    except Exception as err:
                        print("myTimeStampRegex.search() generated exception:" + str(err))
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
                        print("DEBUG-3 JASaveStats.py payload:|{0}|, lokiGatewayURL:|{1}|\n".format(payload, lokiGatewayURL))

                    try:
                        tempReturnResult = requests.post( lokiGatewayURL, data=payload, headers=headersForLokiGateway)
                        tempReturnResult.raise_for_status()
                        
                        if debugLevel > 1:
                            print('DEBUG-2 JASaveStats.py log line: {0} posted to loki with result:{1}\n'.format(line,tempReturnResult.text))
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
                    print('DEBUG-1 JASaveStats.py number of traces to post:{0}\n{1}\n'.format( len(traceLines), traceLines) ) 
                id ="1234"

                for traceLine in traceLines:
                    ### process each line having var=value,
                    ### separate variable and value pairs using comma as separator
                    items = traceLine.split(',')

                    traceParameters = {}
                
                    for item in items:
                        ### expect the item in the form paramName=value
                        ### separate paramName and store it in metricsVariablesToBePosted hash
                        variableNameAndValues = re.split('=', item)
                        variableName = variableNameAndValues[0]
                        if len(variableNameAndValues) > 1:
                            traceParameters[variableName] = variableNameAndValues[1] 


                    payload = [{
                        "id": "1234",
                        "traceId":  traceParameters['traceId'] ,
                        "timestamp": int(traceParameters['timestamp']),
                        "duration": int(traceParameters['duration']),
                        "name":  traceParameters['name'] ,
                        "tags": {
                            "instance": hostName,
                            "http.method": "GET",
                            "http.path": "/api"
                        },
                        "localEndpoint": {
                            "serviceName":  traceParameters['serviceName'] 
                        }
                    }]
                    payload = json.dumps(payload)
                    if debugLevel > 2:
                        print("DEBUG-3 JASaveStats.py payload:|{0}|, ZipkinURL:|{1}|\n".format(payload, JAZipkinURL))

                    try:
                        tempReturnResult = requests.post( JAZipkinURL, data=payload, headers=headersForZipkin)
                        if debugLevel > 0:
                            print('DEBUG-1 JASaveStats.py data: {0} posted to zipkin with result:{1}\n\n'.format(payload,tempReturnResult))
                    except requests.exceptions.RequestException as err:
                        returnResult = returnResult + "ERROR posting trace to zipkin, traceToPost:{0}, returnResult:{1}".format(payload, err)
                        errorPostingZipkin = True

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

                if JADBTypeInfludb == True :
                    ### sampleDateTimeString is of the format timestamp=YYYY-MM-DDTHH:MM:SS.uuuuuu
                    ###   extract only time string
                    tempSampleDateTimeArray = re.split('=',tempSampleDateTime) 
                    ### while inserting to influxdb, use the timestamp posted by client in pico second 
                    sampleTimeFloat = datetime.strptime(tempSampleDateTimeArray[1], "%Y-%m-%dT%H:%M:%S.%f")
                    sampleTime = "{0:.0f}".format(sampleTimeFloat.timestamp()*1000000000)

                ### if stats are to be posted for label, use separate variable to track it
                statsToPostForLabel = defaultdict(dict)

                if JADBTypeInfludb == True :
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
                            print("WARN JASaveStats.py metrics variable name:{0} already present, SKIPing this item:{1}".format(variableName, item))
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
                                ###                                                         ^^^^^^^^^
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
                                        print("DEBUG-3 JASaveStats.py after appending item:{0}, influxRowData:|{1}|".format(item, influxdbRowData) )
                                else:    
                                    statsToPost += '{0} {1}\n'.format( variableName, variableNameAndValues[1])
                                    if debugLevel > 2: 
                                        print('DEBUG-3 JASaveStats.py item :{0}, itemToPost:{1} {2}\n'.format(item,variableName, variableNameAndValues[1] ) )
                                postData = True
                    else:
                        print('WARN JASaveStats.py item:{0} is NOT in paramName=value format, DID NOT post this to prometheus\n'.format(item))
                
                if JADBTypeInfludb == True:

                    if len(statsToPostForLabel) > 0:
                        ### if label values are present, add separate row per label to influxdbDataArrayToPost
                        for label, labelValue in statsToPostForLabel.items():
                            ### prepare one row data per label
                            influxdbRowData = "{0},{1},client={2} {3} {4}".format(jobName,labelParams, label,labelValue,sampleTime)
                            influxdbDataArrayToPost.append(influxdbRowData)
                            if debugLevel > 2:
                                print("DEBUG-3 JASaveStats.py influxdbRowData for label:|{0}|, influxdbRowData:|{1}|".format(label,influxdbRowData))
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
                                    print('DEBUG-1 JASaveStats.py label:|{0}| and data:|{1}| posted to prometheus push gateway with result:{2}\n\n'.format(label, labelValue,tempReturnResult))

                        except requests.exceptions.RequestException as err:
                            returnResult = returnResult + "ERROR posting data to prometheus gateway, returnResult:{0}".format(err)
                            errorPostingPrometheusGateway = True                        

        else:
            if debugLevel > 3:
                print('DEBUG-4 JASaveStats.py skipping key:{0} this data not added to stats key'.format(key) )

    if postData == True :
        if JADBTypeInfludb == True :
            try:
                tempStatus, tempReturnResult = JAInfluxdbLib.JAInfluxdbWriteData(JAInfluxdbURL,JAInfluxdbToken,JAInfluxdbOrg,JAInfluxdbBucket, influxdbDataArrayToPost, debugLevel)
                if tempStatus == False:
                    returnResult = returnResult + "ERROR posting data to influxDB, returnResult:{0}".format(tempReturnResult)
                else:
                    if debugLevel > 0:
                        print("DEBUG-1 JASaveStats.py data: {0} posted to influxdb with returnStatus:|{1}|".format(influxdbDataArrayToPost, tempReturnResult ))
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
                        print('DEBUG-1 JASaveStats.py data: {0} posted to prometheus push gateway with result:{1}\n\n'.format(statsToPost,tempReturnResult))
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
    returnResult='PASS - Saved data'

### print status and get out
JASaveStatsExit(str(returnResult))