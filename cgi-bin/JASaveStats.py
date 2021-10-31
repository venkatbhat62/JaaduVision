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

"""
import os,sys,json,re
import datetime
import yaml
import requests
import JAGlobalLib
from collections import defaultdict

def JASaveStatsExit(reason):
    if re.match('^ERROR ', reason):
        print('ERROR JASaveStats.py() ' + reason )
    elif re.match('^PASS ', reason):
        print('PASS  JASaveStats.py() ' + reason)
    else:
        print('      JASaveStats.py() ' + reason)

    JASaveStatsEndTime = datetime.datetime.now()
    JASaveStatsDuration = JASaveStatsEndTime - JASaveStatsStartTime
    JASaveStatsDurationInSec = JASaveStatsDuration.total_seconds()
    JAGlobalLib.LogMsg(reason + ', response time:{JASaveStatsDurationInSec} sec\n', JALogFileName, True)
    sys.exit()

def JASaveStatsError(reason):
    print ('ERROR Could not save the data: ' + reason)
    JASaveStatsExit(reason)

JASaveStatsStartTime = datetime.datetime.now()

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

contentLength = int(os.environ["CONTENT_LENGTH"])
reqBody = sys.stdin.read(contentLength)
postedData = defaultdict(dict)
postedData = json.loads(reqBody)
print('Content-Type: text/html; charset=utf-8\n')

returnResult='PASS - Saved data'

### prepare server side fileName to store data
if JADirStats != None:
    if postedData['fileName'] == None:
        ### if valid JADirStats is present, expect fileName to be passed to save the data locally 
        JASaveStatsError('fileName not passed')
    else:
        fileName = JADirStats + '/' + postedData['fileName']
else:
    fileName = None

if postedData['jobName'] == None:
    JASaveStatsError('jobName not passed')
else:
    jobName = postedData['jobName']
    if jobName == 'loki':
        postToLoki = True
    else:
        postToLoki = False

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
prefixParams = ''
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

if postedData['environment'] != None:
    appendToURL = "/environment/" + postedData['environment'] 
    prefixParams = "environment=" + postedData['environment']
else:
    prefixParams = "environment="

if postedData['platformName'] != None:
    appendToURL = appendToURL + "/platform/" + postedData['platformName']
    prefixParams = prefixParams + ",platform=" + postedData['platformName']
    labelParams += 'platform=\"' + postedData['platformName'] + '\"'
    comma = ','
else:
    prefixParams = prefixParams + ",platform="

if postedData['siteName'] != None:
    appendToURL = appendToURL + "/site/" + postedData['siteName'] 
    prefixParams = prefixParams + ",site=" + postedData['siteName']
    siteName = postedData['siteName']
    labelParams += comma + ' site=\"' + postedData['siteName'] + '\"'
    comma = ','
else:
    prefixParams = prefixParams + ",site="

if postedData['componentName'] != None:
    appendToURL = appendToURL + "/component/" + postedData['componentName']
    prefixParams = prefixParams + ",component=" + postedData['componentName']
    labelParams += comma + ' component=\"' + postedData['componentName'] + '\"'
    comma = ','
else:
    prefixParams = prefixParams + ",component=" 

if hostName != None:
    prefixParams = prefixParams + ",host=" + hostName
    labelParams += comma + ' instance=\"' + hostName + '\"'

if debugLevel > 1:
    JAGlobalLib.LogMsg('DEBUG-2 Stats Dir:' + JADirStats + ', fileName: ' + fileName + ', pushGatewayURL: ' + pushGatewayURL + ', appendToURL: ' + appendToURL + ', prefixParams: ' + prefixParams + '\n', JALogFileName, True)

### Now post the data to web server
headersForPushGateway= {'Content-type': 'application/x-www-form-urlencoded', 'Accept': '*/*'}
headersForLokiGateway = {'Content-Type': 'application/json'}

if JADisableWarnings == True:
    requests.packages.urllib3.disable_warnings()

### open the file in append mode and save data
try:
    if fileName != None:
        if saveOnWebServer == 1:
            ### save data locally if fileName is specified
            fpo = open( fileName, 'a')
            if debugLevel > 0:
                print('DEBUG-1 JASaveStats.py fileName: {0}, postToLoki {1}'.format(fileName, postToLoki))

    ### while writing values to file and posting to pushgateway, skip below keys
    skipKeyList = ['debugLevel','fileName','environment','siteName','platformName','componentName','hostName','saveLogsOnWebServer']

    statsType = None
    statsToPost = ''
    postData = False

    metricsVariablesToBePosted = {}

    for key, value in postedData.items():

        if key not in skipKeyList:
            if debugLevel > 1:
                print('DEBUG-2 JASaveStats.py processing key: {0}, value: {1}\n'.format(key, value))
                
            ### SKIP LogStats, OSStats, loki  
            if value == 'LogStats' or value == 'OSStats' or value == 'loki':
                statsType = value
                continue

            if fileName != None:
                if saveOnWebServer == 1:   
                    ### save this data with prefixParams that identifies statsType, environment, site, platform, component, host 
                    fpo.write( '{0},{1},{2}\n'.format(prefixParams, key, value ) )

                    if debugLevel > 1:
                        print('DEBUG-2 JASaveStats.py wrote data: {0},{1},{2} to file\n'.format(prefixParams,key, value))

            if postToLoki == True:
                ### need to post log lines to loki
                ### data posted has lines with , separation
                """
                Post log lines to Loki with labels instance, site, component, and platform. Values of these labels are from posted values
                  instance - hostName
                  site - siteName
                  component - componentName
                  platform - platformName 
                """
                
                tempLines = value.split('\n')
                lineCount = 1
                for line in tempLines:
                    curr_datetime = datetime.datetime.utcnow()
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
                        returnResult = requests.post( lokiGatewayURL, data=payload, headers=headersForLokiGateway)
                        returnResult.raise_for_status()
                        
                        if debugLevel > 1:
                            print('DEBUG-2 JASaveStats.py log line: {0} posted to loki with result:{1}\n'.format(line,returnResult.text))
                    except requests.exceptions.HTTPError as err:
                        print("ERROR JASaveStats.py " + err.response.text)
                        raise SystemExit(err)

                    lineCount += 1

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
                items.pop(0)

                ### if stats are to be posted for label, use separate variable to track it
                statsToPostForLabel = defaultdict(dict)

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
                                ###    post the data with this label to prometheus gateway separately.
                                ### timeStamp=2021-10-31T15:24:22.480140,TestStatsWithLabel_:client1:key1_average=32.50,TestStatsWithLabel_:client1:key2_average=16.25,TestStatsWithLabel_:client2:key1_average=32.50,TestStatsWithLabel_:client2:key2_average=16.25
                                ###                                                         ^^^^^^^^^
                                labelPrefix = myResults.group(1)
                                if debugLevel > 2 :
                                    print ("DEBUG-3 JASaveStats.py label:|{0}|, variableName BEFORE removing the label:{1}\n".format(labelPrefix, variableName))
                                if labelPrefix != None:
                                    ### this format needs to match the format used in JAGatherLogStats.py function JAProcessLogFile()
                                    replaceString = '_:{0}:'.format(labelPrefix)
                                    variableName = re.sub(replaceString,'_',variableName)
                                if debugLevel > 2 :
                                    print ("DEBUG-3 JASaveStats.py, label:|{0}|, variableName AFTER removing the label:|{1}|\n".format(labelPrefix, variableName))
                                
                                if labelPrefix in statsToPostForLabel[labelPrefix]:
                                    statsToPostForLabel[labelPrefix] += '{0} {1}\n'.format( variableName, variableNameAndValues[1])                                
                                else:
                                    statsToPostForLabel[labelPrefix] = '{0} {1}\n'.format( variableName, variableNameAndValues[1])

                            else:
                                statsToPost += '{0} {1}\n'.format( variableName, variableNameAndValues[1])
                                if debugLevel > 2: 
                                    print('DEBUG-3 JASaveStats.py item :{0}, itemToPost:{1} {2}\n'.format(item,variableName, variableNameAndValues[1] ) )
                                postData = True
                    else:
                        print('WARN JASaveStats.py item:{0} is NOT in paramName=value format, DID NOT post this to prometheus\n'.format(item))
                
                for label, labelValue in statsToPostForLabel.items():
                    returnResult = requests.post( pushGatewayURL + appendToURL + "/client/" + label, data=labelValue, headers=headersForPushGateway)

                    if debugLevel > 0:
                        print('DEBUG-1 JASaveStats.py label:|{0}| and data:|{1}| posted to prometheus push gateway with result:{2}\n\n'.format(label, labelValue,returnResult))


        else:
            if debugLevel > 2:
                print('DEBUG-3 JASaveStats.py skipping key:{0} this data not added to stats key\n'.format(key) )

    if postData == True :
        returnResult = requests.post( pushGatewayURL + appendToURL, data=statsToPost, headers=headersForPushGateway)

        if debugLevel > 0:
            print('DEBUG-1 JASaveStats.py data: {0} posted to prometheus push gateway with result:{1}\n\n'.format(statsToPost,returnResult))

    if fileName != None:
        if saveOnWebServer == 1: 
            fpo.close()

except OSError as err:
    JASaveStatsError('ASaveStats.py Can not open file:|' + fileName + '|' + "OS error: {0}".format(err) )

### print status and get out
JASaveStatsExit(str(returnResult))

