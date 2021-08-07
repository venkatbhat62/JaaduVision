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

Author: havembha@gmail.com 2021-07-11

"""
import os,sys,json,re
import datetime
import yaml
import requests
import JAGlobalLib

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

### read global parameters
with open('JAGlobalVars.yml','r') as file:
    JAGlobalVars = yaml.load(file, Loader=yaml.FullLoader)
    JALogDir = JAGlobalVars['JALogDir']
    JADisableWarnings = JAGlobalVars['JADisableWarnings']
    JALogFileName = JALogDir + "/" + JAGlobalVars['JASaveStats']['LogFileName']
    JADirStats = JAGlobalVars['JASaveStats']['Dir']
    JAPushGatewayURL = JAGlobalVars['JASaveStats']['PushGatewayURL']

contentLength = int(os.environ["CONTENT_LENGTH"])
reqBody = sys.stdin.read(contentLength)
postedData = json.loads(reqBody)
print('Content-Type: text/html; charset=utf-8\n')

returnResult='PASS - Saved data'

### prepare server side fileName to store data
if postedData['fileName'] == None:
    JASaveStatsError('fileName not passed')
else:
    fileName = JADirStats + '/' + postedData['fileName']

if postedData['jobName'] == None:
    JASaveStatsError('jobName not passed')
else:
    jobName = postedData['jobName']

if postedData['hostName'] == None:
    JASaveStatsError('hostName not passed')
else:
    hostName = postedData['hostName']

## make initial part of URL 
pushGatewayURL = JAPushGatewayURL + "/metrics/job/" + jobName + "/instance/" + hostName
prefixParams = ''
appendToURL = ''

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
else:
    prefixParams = prefixParams + ",platform="

if postedData['siteName'] != None:
    appendToURL = appendToURL + "/site/" + postedData['siteName'] 
    prefixParams = prefixParams + ",site=" + postedData['siteName']
else:
    prefixParams = prefixParams + ",site="

if postedData['componentName'] != None:
    appendToURL = appendToURL + "/component/" + postedData['componentName']
    prefixParams = prefixParams + ",component=" + postedData['componentName']
else:
    prefixParams = prefixParams + ",component=" 

if hostName != None:
    prefixParams = prefixParams + ",host=" + hostName

if debugLevel > 1:
    JAGlobalLib.LogMsg('DEBUG-2 pushGatewayURL: ' + pushGatewayURL + ', appendToURL: ' + appendToURL + ', prefixParams: ' + prefixParams + '\n', JALogFileName, True)

### Now post the data to web server
headers= {'Content-type': 'application/x-www-form-urlencoded', 'Accept': '*/*'}

if JADisableWarnings == True:
    requests.packages.urllib3.disable_warnings()

### open the file in append mode and save data
try:
    fpo = open( fileName, 'a')
    ### while writing values to file and posting to pushgateway, skip below keys
    skipKeyList = ['fileName','environment','siteName','platformName','componentName','hostName']

    for key, value in postedData.items():
        if key not in skipKeyList:
            if debugLevel > 2:
                print('DEBUG-3 JASaveStats.py processing key:' + key)
            ### save this data with prefixParams that identifies environment, site, platform, component, host 
            fpo.write(prefixParams + ',' + value + '\n')

            ### convert data 
            ### from p1=v1,p2=v2,... 
            ### to 
            ###    p1 v1
            ###    p2 v2
            ### replace =, remove space, and make one metric per line to post to PushGatewayURL
            valuePairs = str(value)
            items = valuePairs.split(',')
            statsToPost = ''

            ### remove timeStamp=value from the list. Prometheous scraper uses scaping time for reference.
            ###    this sample from source can't be used for time series graphs
            items.pop(0)

            for item in items:
                statsToPost += (item + '\n')
                if debugLevel > 2: 
                    JAGlobalLib.LogMsg('DEBUG-3 item : ' + item + '\n', JALogFileName, True) 

            statsToPost = statsToPost.replace('=', ' ')
            returnResult = requests.post( pushGatewayURL, data=statsToPost, headers=headers)

            if debugLevel > 0:
                JAGlobalLib.LogMsg('DEBUG-1 data posted:\n' + statsToPost + '      With result:' + returnResult + '\n\n', JALogFileName, True)

        else:
            if debugLevel > 2:
                print('DEBUG-3 JASaveStats.py skipping key:' + key + ', this data will not be added to stats key')

    fpo.close()

except OSError as err:
    JASaveStatsError('Can not open file:|' + fileName + '|' + "OS error: {0}".format(err) )

### print status and get out
JASaveStatsExit(str(returnResult))

