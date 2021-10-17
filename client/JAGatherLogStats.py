
""" 
This script gathers and POSTs log stats to remote web server
Posts jobName=LogStats, hostName=<thisHostName>, fileName as parameter in URL
Posts <key> {metric1=value1, metric2=value2...} one line per key type as data

Parameters passed are:
-c    configFile - yaml file containing stats to be collected
        default - JAGatherLogStats.yml 
-U    webServerURL - post the data collected to web server 
        default - get it from JAGatherLogStats.yml 
-i    dataPostIntervalInSec - post data at this periodicity, in seconds
        default - get it from JAGatherLogStats.yml
-d    dataCollectDurationInSec - collect data for this duration once started
            when started from crontab, run for this duration and exit
            default - get it from JAGatherLogStats.yml
-L    processSingleLogFileName - process only this log file, skip the rest
            useful to debug single log file at a time to refine regular expression spec for services
-D    debugLevel - 0, 1, 2, 3, 4
        default = 0

returnResult
    Print result of operation to log file 

Note - did not add python interpreter location at the top intentionally so that
    one can execute this using python or python3 depending on python version on target host

Author: havembha@gmail.com, 2021-07-18
"""
import json
import platform
import argparse
from collections import defaultdict
import os
import sys
import re
import JAGlobalLib
import time
import subprocess
import signal


# Major 01, minor 00, buildId 01
JAVersion = "01.00.02"

### number of patterns that can be searched in log line per Service
patternIndexForPriority = 0
patternIndexForPatternPass = 1
patternIndexForPatternFail = 2
patternIndexForPatternCount = 3
patternIndexForPatternSum = 4
patternIndexForPatternAverage = 5
patternIndexForPatternDelta = 6
## below patterns comes into play when pattern searched is Pattern Sum/Average/Delta
patternIndexForVariablePrefix = 7
patternIndexForVariablePrefixGroup = 8
patternIndexForPatternLog = 9
### keep this one higher than patternIndex values above
## it is used to initialize list later.
maxPatternIndex = 10

try:
    from subprocess import CompletedProcess
except ImportError:
    # Python 2
    class CompletedProcess:

        def __init__(self, args, returncode, stdout=None, stderr=None):
            self.args = args
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

        def check_returncode(self):
            if self.returncode != 0:
                err = subprocess.CalledProcessError(
                    self.returncode, self.args, output=self.stdout)
                raise err
                return self.returncode

        def sp_run(*popenargs, **kwargs):
            input = kwargs.pop("input", None)
            check = kwargs.pop("handle", False)
            if input is not None:
                if 'stdin' in kwargs:
                    raise ValueError(
                        'stdin and input arguments may not both be used.')
                kwargs['stdin'] = subprocess.PIPE
            process = subprocess.Popen(*popenargs, **kwargs)
            try:
                outs, errs = process.communicate(input)
            except:
                process.kill()
                process.wait()
                raise
            returncode = process.poll()
            if check and returncode:
                raise subprocess.CalledProcessError(
                    returncode, popenargs, output=outs)
            return CompletedProcess(popenargs, returncode, stdout=outs, stderr=errs)

        subprocess.run = sp_run
        # ^ This monkey patch allows it work on Python 2 or 3 the same way


# global default parameters, need to keep these as None so that they will have value other than None 
#  when environment speicfic value is seen
configFile = None
webServerURL = None
maxProcessingTimeForAllEvents = 0
dataPostIntervalInSec = 0
dataCollectDurationInSec = 0
debugLevel = 0
statsLogFileName = None
componentName = None
platformName = None
siteName = None
disableWarnings = None
verifyCertificate = None
cacheLogFileName = None
processSingleLogFileName = None
saveLogsOnWebServer = None

### max log lines per service, per sampling interval
###  when log lines exceed this count, from 11th line till last line withing the sampling interval,
###    lines will be counted and reported as "..... XXX more lines...."
maxLogLines = None
# list contains the max cpu usage levels for all events, priority 1,2,3 events
# index 0 - for all events, index 1 for priority 1, index 3 for priority 3
maxCPUUsageForEvents = [0, 0, 0, 0]
# logEventPriorityLevel will be set to this value by default (no skipping)
maxCPUUsageLevels = logEventPriorityLevel = 4


# current average CPU usage - average over last 10 samples at dataPostIntervalInSec interval
averageCPUUsage = 0

# contains current stats
# key1 - serviceName
logStats = defaultdict(dict)

# contains log lines to be sent to web server
# key1 = serviceName (similar to key1 of logStats)
# key2 = logFileName
logLines = defaultdict(dict)

# take current timestamp
statsStartTimeInSec = statsEndTimeInSec = time.time()

# parse arguments passed from command line
parser = argparse.ArgumentParser()
parser.add_argument(
    "-D", type=int, help="debug level 0 - None, 1,2,3-highest level")
parser.add_argument(
    "-c", help="yaml file containing stats to be collected, default - JAGatherLogStats.yml")
parser.add_argument(
    "-U", help="web server URL to post the data, default - get it from configFile")
parser.add_argument(
    "-i", type=int, help="data post interval in sec, default - get it from configFile")
parser.add_argument(
    "-d", type=int, help="data collect duration in sec, default - get it from configFile")
parser.add_argument("-C", help="component name, default - none")
parser.add_argument("-P", help="platform name, default - none")
parser.add_argument("-S", help="site name, default - none")
parser.add_argument(
    "-E", help="environment like dev, test, uat, prod, default - test")
parser.add_argument("-l", help="log file name, including path name")
parser.add_argument(
    "-L", help="process single log file name, including path name, skip rest")

args = parser.parse_args()
if args.D:
    debugLevel = args.D

if args.c:
    configFile = args.c

if args.U:
    webServerURL = args.U

if args.i:
    dataPostIntervalInSec = args.i

if args.d:
    dataCollectDurationInSec = args.d

if args.C:
    componentName = args.C

if args.P:
    platformName = args.P

if args.S:
    siteName = args.S

if args.E:
    environment = args.E
else:
    environment = 'test'

if args.l:
    statsLogFileName = args.l

if args.L:
    processSingleLogFileName = args.L

if debugLevel > 0:
    print('DEBUG-1 Parameters passed configFile: {0}, WebServerURL: {1}, dataPostIntervalInSec: {2}, dataCollectDurationInSec: {3}, debugLevel: {4}, componentName: {5}, platformName: {6}, siteName: {7}, environment: {8}, processSingleLogFileName: {9}\n'.format(
        configFile, webServerURL, dataPostIntervalInSec, dataCollectDurationInSec, debugLevel, componentName, platformName, siteName, environment, processSingleLogFileName))


def JASignalHandler(sig, frame):
    JAStatsExit("Control-C pressed")

signal.signal(signal.SIGINT, JASignalHandler)


def JAStatsExit(reason):
    print(reason)
    JAStatsDurationInSec = statsEndTimeInSec - statsStartTimeInSec
    JAGlobalLib.LogMsg('{0} processing duration: {1} sec\n'.format(
        reason, JAStatsDurationInSec), statsLogFileName, True)
    ### write prev start time of 0 so that next time process will run
    JAGlobalLib.JAWriteTimeStamp("JAGatherLogStats.PrevStartTime", 0)
    sys.exit()


# use default config file
if configFile == None:
    configFile = "JAGatherLogStats.yml"

# stats spec with service name as key
JAStatsSpec = defaultdict(dict)

# get current hostname
thisHostName = platform.node()
# if hostname has domain name, strip it
hostNameParts = thisHostName.split('.')
thisHostName = hostNameParts[0]

# get OSType, OSName, and OSVersion. These are used to execute different python
# functions based on compatibility to the environment
OSType, OSName, OSVersion = JAGlobalLib.JAGetOSInfo(
    sys.version_info, debugLevel)

# based on current hostName, this variable will be set to Dev, Test, Uat, Prod etc
myEnvironment = None

"""
JAGatherEnvironmentSpecs( key, values )
This function parses the environment variables defined for a given environment like Dev, Test, UAT
If current environment is 'All' and value not defined for a parameter,
  appropriate default value is assigned

Parameters passed
  key like Dev, Test, UAT, Prod, All
  values - values in list form 

Return value
  Below global variables are updated with values parsed from values parameter
    global dataPostIntervalInSec, dataCollectDurationInSec 
    global webServerURL, disableWarnings, verifyCertificate, numSamplesToPost

"""


def JAGatherEnvironmentSpecs(key, values):

    # declare global variables
    global dataPostIntervalInSec, dataCollectDurationInSec, maxCPUUsageForEvents, maxProcessingTimeForAllEvents
    global webServerURL, disableWarnings, verifyCertificate, debugLevel, maxLogLines, saveLogsOnWebServer

    for myKey, myValue in values.items():
        if debugLevel > 1:
            print(
                'DEBUG-2 JAGatherEnvironmentSpecs() key: {0}, value: {1}'.format(myKey, myValue))
        if myKey == 'DataPostIntervalInSec':
            if dataPostIntervalInSec == 0:
                if myValue != None:
                    dataPostIntervalInSec = int(myValue)

        elif myKey == 'DataCollectDurationInSec':
            if dataCollectDurationInSec == 0:
                if myValue != None:
                    dataCollectDurationInSec = int(myValue)

        elif myKey == 'MaxProcessingTimeForAllEvents':
            if maxProcessingTimeForAllEvents == 0:
                if myValue != None:
                    maxProcessingTimeForAllEvents = int(myValue)

        elif myKey == 'MaxCPUUsageForAllEvents':
            if maxCPUUsageForEvents[0] == 0:
                if myValue != None:
                    maxCPUUsageForEvents[0] = int(myValue)

        elif myKey == 'MaxCPUUsageForPriority1Events':
            if maxCPUUsageForEvents[1] == 0:
                if myValue != None:
                    maxCPUUsageForEvents[1] = int(myValue)

        elif myKey == 'MaxCPUUsageForPriority2Events':
            if maxCPUUsageForEvents[2] == 0:
                if myValue != None:
                    maxCPUUsageForEvents[2] = int(myValue)

        elif myKey == 'MaxCPUUsageForPriority3Events':
            if maxCPUUsageForEvents[3] == 0:
                if myValue != None:
                    maxCPUUsageForEvents[3] = int(myValue)

        elif myKey == 'DebugLevel':
            if debugLevel == 0:
                if myValue != None:
                    debugLevel = int(myValue)

        elif myKey == 'MaxLogLines':
            if maxLogLines == 0:
                if myValue != None:
                    maxLogLines = int(myValue)

        elif myKey == 'SaveLogsOnWebServer':
            if saveLogsOnWebServer == None:           
                ## if this is not assigned yet, assign
                ## if host specific assignment is already done, while processing "All" environment related spec,
                ##   retain the values specified in environment specific section
                if myValue != None:
                    if myValue == 'False' or myValue == False:
                        saveLogsOnWebServer = False
                    if myValue == 'True' or myValue == True:
                        saveLogsOnWebServer = True

        elif myKey == 'WebServerURL':
            if webServerURL == None:
                if myValue != None:
                    webServerURL = myValue
                elif key == 'All':
                    JAStatsExit(
                        'ERROR mandatory param WebServerURL not available')

        elif myKey == 'DisableWarnings':
            if disableWarnings == None:
                if myValue != None:
                    if myValue == 'False' or myValue == False:
                        disableWarnings = False
                    elif myValue == 'True' or myValue == True:
                        disableWarnings = True
                    else:
                        disableWarnings = myValue

        elif myKey == 'VerifyCertificate':
            if verifyCertificate == None:
                if myValue != None:
                    if myValue == 'False' or myValue == False:
                        verifyCertificate = False
                    elif myValue == 'True' or myValue == True:
                        verifyCertificate = True
                    else:
                        verifyCertificate = myValue

    if debugLevel > 0:
        print('DEBUG-1 Parameters after reading configFile: {0}, WebServerURL: {1},  DataPostIntervalInSec: {2}, DataCollectDurationInSec: {3}, maxCPUUsageForEvents: {4}, maxProcessingTimeForAllEvents: {5}, DebugLevel: {6}'.format(
            configFile, webServerURL, dataPostIntervalInSec, dataCollectDurationInSec, maxCPUUsageForEvents, maxProcessingTimeForAllEvents, debugLevel))


# check whether yaml module is present
yamlModulePresent = False

if sys.version_info >= (3, 3):
    import importlib
    import importlib.util
    try:
        if importlib.util.find_spec("yaml") != None:
            yamlModulePresent = True
        else:
            yamlModulePresent = False
    except ImportError:
        yamlModulePresent = False

    try:
        if importlib.util.find_spec("psutil") != None:
            psutilModulePresent = True
        else:
            psutilModulePresent = False
    except ImportError:
        psutilModulePresent = False
else:
    yamlModulePresent = False
    psutilModulePresent = False

# read default parameters and OS Stats collection spec
try:
    with open(configFile, "r") as file:
        # uncomment below to test local parsing of yaml file where pythin 3 is not present
        # yamlModulePresent = False

        # use limited yaml reader when yaml is not available
        if yamlModulePresent == True:
            import yaml
            JAStats = yaml.load(file, Loader=yaml.FullLoader)
            file.close()
        else:
            JAStats = JAGlobalLib.JAYamlLoad(configFile)

        if debugLevel > 1:
            print(
                'DEBUG-2 Content of config file: {0}, read to JAStats: {1}'.format(configFile, JAStats))

        if statsLogFileName == None:
            if JAStats['GatherLogStatsLogFile'] != None:
                statsLogFileName = JAStats['GatherLogStatsLogFile']
            else:
                statsLogFileName = 'JAGatherLogStats.log'

        if cacheLogFileName == None:
            if JAStats['GatherLogStatsCacheFile'] != None:
                cacheLogFileName = JAStats['GatherLogStatsCacheFile']
            else:
                cacheLogFileName = 'JAGatherLogStats.cache'

        for key, value in JAStats['Environment'].items():
            if key == 'All':
                # if parameters are not yet defined, read the values from this section
                # values in this section work as default if params are defined for
                # specific environment
                JAGatherEnvironmentSpecs(key, value)

            if value.get('HostName') != None:
                if re.match(value['HostName'], thisHostName):
                    # current hostname match the hostname specified for this environment
                    # read all parameters defined for this environment
                    JAGatherEnvironmentSpecs(key, value)
                    myEnvironment = key

        # if conig file does not have values for below, assign default values
        if dataPostIntervalInSec == 0:
            # 60 seconds
            dataPostIntervalInSec = 60
        if maxProcessingTimeForAllEvents == 0:
           maxProcessingTimeForAllEvents = dataPostIntervalInSec / 2 
        if dataCollectDurationInSec == 0:
            # close to one hour
            dataCollectDurationInSec = 3540
        if disableWarnings == None:
            disableWarnings = True
        if verifyCertificate == None:
            verifyCertificate = False
        if maxCPUUsageForEvents[0] == 0:
            # SKIP processing log files when CPU usage exceeds 80%
            maxCPUUsageForEvents[0] = 80
        if maxCPUUsageForEvents[1] == 0:
            # SKIP processing priority 1 events of log files when CPU usage exceeds 70%
            maxCPUUsageForEvents[1] = 70
        if maxCPUUsageForEvents[2] == 0:
            # SKIP processing priority 2 events of log files when CPU usage exceeds 60%
            maxCPUUsageForEvents[2] = 60
        if maxCPUUsageForEvents[3] == 0:
            # SKIP processing priority 3 events of log files when CPU usage exceeds 50%
            maxCPUUsageForEvents[3] = 50
        if maxLogLines == None:
            maxLogLines = 10

        if statsLogFileName == None:
            statsLogFileName = "JAGatherLogStats.log"
        if cacheLogFileName == None:
            cacheLogFileName = "JAGatherLogStats.cache"

        dateTimeFormatType = None
        # read spec for each log file
        # LogFile:
        # Name: <fileName>
        # Service:
        ###         Name: name
        # PatternPass: string containing regular expression
        # PatternFail: string containing regular expression
        # PatternCount: string containing regular expression
        # PatternSum: leading text key1 dummy value1 dummy key2 dummy value2 dummy....
        # PatternAverage: leading text key1 dummy value1 dummy key2 dummy value2 dummy....
        # PatternVariablePrefix: text variable text
        for key, value in JAStats['LogFile'].items():
            
            tempPatternList = [ None] * (maxPatternIndex)
            tempPatternPresent = [False] * (maxPatternIndex)
            
            ## default priority 3, lowest
            tempPatternList[patternIndexForPriority] = 3
            tempPatternPresent[patternIndexForPriority] = True

            if value.get('LogFileName') != None:
                logFileName = str(value.get('LogFileName')).strip()

            if processSingleLogFileName != None:
                # need to process single log file, skip rest
                if logFileName != processSingleLogFileName:
                    continue

            if value.get('PatternPass') != None:
                tempPatternList[patternIndexForPatternPass] = str(value.get('PatternPass')).strip()
                tempPatternPresent[patternIndexForPatternPass] = True

            if value.get('PatternFail') != None:
                tempPatternList[patternIndexForPatternFail] = str(value.get('PatternFail')).strip()
                tempPatternPresent[patternIndexForPatternFail] = True
                
            if value.get('PatternCount') != None:
                tempPatternList[patternIndexForPatternCount] = str(value.get('PatternCount')).strip()
                tempPatternPresent[patternIndexForPatternCount] = True

            if value.get('PatternSum') != None:
                tempPatternList[patternIndexForPatternSum] = str(value.get('PatternSum')).strip()
                tempPatternPresent[patternIndexForPatternSum] = True

            if value.get('PatternAverage') != None:
                tempPatternList[patternIndexForPatternAverage] = str(value.get('PatternAverage')).strip()
                tempPatternPresent[patternIndexForPatternAverage] = True

            if value.get('PatternDelta') != None:
                tempPatternList[patternIndexForPatternDelta] = str(value.get('PatternDelta')).strip()
                tempPatternPresent[patternIndexForPatternDelta] = True

            if value.get('Priority') != None:
                tempPatternList[patternIndexForPriority] = value.get('Priority')

            if value.get('PatternLog') != None:
                tempPatternList[patternIndexForPatternLog] = str(value.get('PatternLog')).strip()
                tempPatternPresent[patternIndexForPatternLog] = True

            if value.get('PatternVariablePrefix') != None:
                tempPatternList[patternIndexForVariablePrefix] = str(value.get('PatternVariablePrefix')).strip()
                tempPatternPresent[patternIndexForVariablePrefix] = True

            if value.get('PatternVariablePrefixGroup') != None:
                tempPatternList[patternIndexForVariablePrefixGroup] = str(value.get('PatternVariablePrefixGroup')).strip()
                tempPatternPresent[patternIndexForVariablePrefixGroup] = True

            if logFileName != None:     
                JAStatsSpec[logFileName][key] = list(tempPatternList)
                    
                if debugLevel > 1:
                    print('DEBUG-2 key: {0}, value: {1}, pass, fail, count search strings: {2}'.format(
                        key, value, JAStatsSpec[logFileName][key]))

            # initialize counts to 0
            # set present flag if that count is to be posted to web server
            logStats[key][patternIndexForPatternPass*2] = 0
            logStats[key][patternIndexForPatternPass*2+1] = tempPatternPresent[patternIndexForPatternPass]
            logStats[key][patternIndexForPatternFail*2] = 0
            logStats[key][patternIndexForPatternFail*2+1] = tempPatternPresent[patternIndexForPatternFail]
            logStats[key][patternIndexForPatternCount*2] = 0
            logStats[key][patternIndexForPatternCount*2+1] = tempPatternPresent[patternIndexForPatternCount]
            ### data to be posted may have multiple values, initialize it to be a list
            logStats[key][patternIndexForPatternSum*2] = 0
            ### for sum, data is posted if sample count is non=zero, no pattern present flag used
            logStats[key][patternIndexForPatternSum*2+1] = []
            ### data to be posted may have multiple values, initialize it to be a list
            logStats[key][patternIndexForPatternAverage*2] = []
            ### for average, data is posted if sample count is non=zero, no pattern present flag used
            logStats[key][patternIndexForPatternAverage*2+1] = []
            logStats[key][patternIndexForPatternDelta*2] = 0
            ### for delta, data is posted if sample count is non=zero, no pattern present flag used
            logStats[key][patternIndexForPatternDelta*2+1] = []
            
            ### set to None, it will be set to proper value later before posting to web server
            logStats[key][patternIndexForVariablePrefix*2] = None
            logStats[key][patternIndexForVariablePrefix*2+1] = tempPatternPresent[patternIndexForVariablePrefix]
            ### set to None, it will be set to proper value later before posting to web server
            logStats[key][patternIndexForVariablePrefixGroup*2] = None
            logStats[key][patternIndexForVariablePrefixGroup*2+1] = tempPatternPresent[patternIndexForVariablePrefixGroup]

            ### initialize logLines[key] list to empty list
            logLines[key] = []

                             
except OSError as err:
    JAStatsExit('ERROR - Can not open configFile:|' +
                configFile + '|' + "OS error: {0}".format(err) + '\n')

print('INFO  DataPostIntervalInSec:{0}, DataCollectDurationInSec: {1}, DisableWarnings: {2}, VerifyCertificate: {3}, WebServerURL: {4}, maxCPUUsageForEvents: {5}, maxProcessingTimeForAllEvents: {6}, DebugLevel: {7}, Version: {8}'.format(
    dataPostIntervalInSec, dataCollectDurationInSec, disableWarnings, verifyCertificate, webServerURL, maxCPUUsageForEvents, maxProcessingTimeForAllEvents, debugLevel, JAVersion))
if debugLevel > 0:
    for key, spec in JAStatsSpec.items():
        print('DEBUG-1 Name: {0}, Fields: {1}'.format(key, spec))

### read the last time this process was started, 
###   if the time elapsed is less than dataCollectDurationInSec, 
###   prev instance is still running, get out
prevStartTime = JAGlobalLib.JAReadTimeStamp( "JAGatherLogStats.PrevStartTime")
if prevStartTime > 0:
    currentTime = time.time()
    if ( prevStartTime +  dataCollectDurationInSec) > currentTime:
        JAStatsExit('WARN - another instance of this program is running, exiting')

### Create a file with current time stamp
JAGlobalLib.JAWriteTimeStamp("JAGatherLogStats.PrevStartTime")

returnResult = ''

### contains key, value pairs of stats to be posted
logStatsToPost = defaultdict(dict)

### has key, logline pairs of logs to be posted
logLinesToPost = defaultdict(dict)

### contains previous sample value of PatternDelta type, key is derived as <serviceName>_<paramName>_delta
previousSampleValues = defaultdict(float)

### contains number of log lines collected per key, key is derived as <serviceName>
logLinesCount = defaultdict(int)

# data to be posted to the web server
# pass fileName containing thisHostName and current dateTime in YYYYMMDD form
logStatsToPost['fileName'] = thisHostName + \
    ".LogStats." + JAGlobalLib.UTCDateForFileName()
logStatsToPost['jobName'] = 'LogStats'
logStatsToPost['hostName'] = thisHostName
logStatsToPost['debugLevel'] = debugLevel
logStatsToPost['componentName'] = componentName
logStatsToPost['platformName'] = platformName
logStatsToPost['siteName'] = siteName
logStatsToPost['environment'] = environment


# data to be posted to the web server
# pass fileName containing thisHostName and current dateTime in YYYYMMDD form
logLinesToPost['fileName'] = thisHostName + \
    ".LogLines." + JAGlobalLib.UTCDateForFileName()
logLinesToPost['jobName'] = 'loki'
logLinesToPost['hostName'] = thisHostName
logLinesToPost['debugLevel'] = debugLevel
logLinesToPost['componentName'] = componentName
logLinesToPost['platformName'] = platformName
logLinesToPost['siteName'] = siteName
logLinesToPost['environment'] = environment

### if log lines are to be saved on web server, send that parameter as part of posting
### this allows saving controlld by client itself
if saveLogsOnWebServer == True:
    logLinesToPost['saveLogsOnWebServer'] = "yes"

headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}


"""
def JAPostDataToWebServer()
This function posts data to web server
Uses below global variables
    global logStats
    global webServerURL, verifyCertificate, logStatsToPost

Return values:
    None

"""


def JAPostDataToWebServer():
    global logStats, debugLevel
    global webServerURL, verifyCertificate, logStatsToPost, logLinesToPost, logEventPriorityLevel
    timeStamp = JAGlobalLib.UTCDateTime()
    if debugLevel > 1:
        print('DEBUG-2 JAPostDataToWebServer() ' +
              timeStamp + ' Posting the stats collected')

    if sys.version_info >= (3, 3):
        import importlib
        import importlib.util
        try:
            if importlib.util.find_spec("requests") != None:
                useRequests = True
            else:
                useRequests = False

            importlib.util.find_spec("json")
            
        except ImportError:
            useRequests = False
    else:
        useRequests = False

    if useRequests == True:
        import requests

        if disableWarnings == True:
            requests.packages.urllib3.disable_warnings()

    numPostings = 0
    # use temporary buffer for each posting
    tempLogStatsToPost = logStatsToPost.copy()

    postData = False

    # sampling interval elapsed
    # push current sample stats to the data to be posted to the web server
    # key - service name
    # values -  value1, presentFlag1, value2, presentFlag2,....
    # { 'AlarmCRIT': [ 0, False, 0, False, 2, True, 0, False],
    #   'ApacheICDR': [ 2, True, 0, False, 0, False, 0, False]}
    #                    pass      fail     count     stats
    for key, values in logStats.items():
    
        tempLogStatsToPost[key] = 'timeStamp=' + timeStamp
        
        floatDataPostIntervalInSec = float(dataPostIntervalInSec)

        if values[patternIndexForPatternPass*2+1] == True:
            tempLogStatsToPost[key] += ",{0}_pass={1:.2f}".format(key,float(values[patternIndexForPatternPass*2]) / floatDataPostIntervalInSec)
            logStats[key][patternIndexForPatternPass*2] = 0
            postData = True
        if values[patternIndexForPatternFail*2+1] == True:
            tempLogStatsToPost[key] += ",{0}_fail={1:.2f}".format(key,float(values[patternIndexForPatternFail*2]) / floatDataPostIntervalInSec)
            logStats[key][patternIndexForPatternFail*2] = 0
            postData = True
        if values[patternIndexForPatternCount*2+1] == True:
            tempLogStatsToPost[key] += ",{0}_count={1:.2f}".format(key, float(values[patternIndexForPatternCount*2])/ floatDataPostIntervalInSec)
            logStats[key][patternIndexForPatternCount*2] = 0
            postData = True
            
        if values[patternIndexForPatternSum*2] > 0 :
            postData = True
            ### sample count is non-zero, stats has value to post
            tempResults = list(values[patternIndexForPatternSum*2+1])

            if debugLevel > 3:
                print("DEBUG-4 JAPostDataToWebServer() PatternSum:{0}".format(tempResults))

            ### tempResults is in the form: [ name1, value1, name, value2,....]
            ### divide the valueX with sampling interval to get tps value
            index = 0
            paramName = ''
            while index < len(tempResults):
                if index % 2 > 0:
                    ### current index has value
                    ### divide the valueX with sampling interval to get tps value
                    tempResultSum = float(tempResults[index]) / floatDataPostIntervalInSec
                    tempLogStatsToPost[key] += ",{0}_{1}_sum={2:.2f}".format( key, paramName, tempResultSum)
                else:
                    ### current index has param name
                    paramName = tempResults[index]
                index += 1
            ### reset count and param list
            logStats[key][patternIndexForPatternSum*2] = 0
            logStats[key][patternIndexForPatternSum*2+1] = []

        if values[patternIndexForPatternDelta*2] > 0 :
            postData = True
            ### sample count is non-zero, stats has value to post
            tempResults = list(values[patternIndexForPatternDelta*2+1])

            if debugLevel > 3:
                print("DEBUG-4 JAPostDataToWebServer() PatternDelta:{0}".format(tempResults))

            ### tempResults is in the form: [ name1, value1, name, value2,....]
            # prev sample value is subracted from current sample to find the change or delta value.
            # these delta values are summed over the sampling interval and divided by sampling intervall to get tps
            index = 0
            paramName = ''
            while index < len(tempResults):
                if index % 2 > 0:
                    ### current index has value
                    ### divide the valueX with sampling interval to get tps value
                    tempResultDelta = float(tempResults[index]) / floatDataPostIntervalInSec
                    tempLogStatsToPost[key] += ",{0}_{1}_delta={2:.2f}".format( key, paramName, tempResultDelta)

                else:
                    ### current index has param name
                    paramName = tempResults[index]
                index += 1
            ### reset count and param list
            logStats[key][patternIndexForPatternDelta*2] = 0
            logStats[key][patternIndexForPatternDelta*2+1] = []

        ### for average type of metrics, need to use sample count of individual key so that for metrics with prefixGroup, 
        ###    average computation uses corresponding sample count
        ### sampleCountList is of type [2,2,2,2,5,5,5,5] where 
        ###      first 2 keys/values, the sample count is 2
        ###      next 2 keys/values, the sample count is 5
        ### relative position of these sample count map to same position in values[patternIndexForPatternAverage*2+1]
        sampleCountList = list( values[patternIndexForPatternAverage*2])               
        if len(sampleCountList) > 0 :
            postData = True
            ### sample count is non-zero, stats has value to post
            tempResults = list(values[patternIndexForPatternAverage*2+1])

            if debugLevel > 3:
                print("DEBUG-4 JAPostDataToWebServer() PatternAverage:{0}, sampleCountList:{1}".format(tempResults, sampleCountList))

            ### tempResults is in the form: [ name1, value1, name, value2,....]
            ### divide the valueX with sample count in sampleCountList to get average value
            index = 0
            paramName = ''
            while index < len(tempResults):
                if index % 2 > 0:
                    ### current index has value
                    tempResultAverage = float(tempResults[index]) / float(sampleCountList[index])
                    tempLogStatsToPost[key] += ",{0}_{1}_average={2:.2f}".format( key, paramName, tempResultAverage)
                else:
                    ### current index has param name
                    paramName = tempResults[index]
                index += 1
            ### empty both lists
            logStats[key][patternIndexForPatternAverage*2] = []
            logStats[key][patternIndexForPatternAverage*2+1] = []

    tempLogStatsToPost['logEventPriorityLevel'] = 'timeStamp={0},logEventPriorityLevel={1}'.format(timeStamp, logEventPriorityLevel)
    
    if postData == True :
        data = json.dumps(tempLogStatsToPost)
        if useRequests == True:
            # post interval elapsed, post the data to web server
            returnResult = requests.post(
                webServerURL, data, verify=verifyCertificate, headers=headers)
            if debugLevel > 1:
                print(
                    'DEBUG-2 JAPostDataToWebServer() logStatsToPost: {0}'.format(tempLogStatsToPost))
            print('INFO JAPostDataToWebServer() Result of posting data to web server ' +
                    webServerURL + ' :\n' + returnResult.text)
            numPostings += 1
        else:
            result = subprocess.run(['curl', '-k', '-X', 'POST', webServerURL, '-H',
                                    "Content-Type: application/json", '-d', data], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            returnStatus = result.stdout.decode('utf-8').split('\n')
            print('INFO JAPostDataToWebServer() result of posting data to web server:{0}\n{1}'.format(
                webServerURL, returnStatus))
            numPostings += 1
    else:
        if debugLevel > 1:
            print(
                'DEBUG-2 JAPostDataToWebServer() No data to post for the key:{0}\n'.format(key))

    JAGlobalLib.LogMsg('INFO  JAPostDataToWebServer() timeStamp: ' + timeStamp +
                       ' Number of stats posted: ' + str(numPostings) + '\n', statsLogFileName, True)

    numPostings = 0
    
    ### now post log lines collected
    # key - service name
    # list - log lines associated with that service name
    for key, lines in logLines.items():
        ### if no value to post, skip it
        if len(lines) == 0:
            continue

        # use temporary buffer for each posting
        tempLogLinesToPost = logLinesToPost.copy()

        tempLogLinesToPost[key] = 'timeStamp=' + timeStamp

        ### values has log files in list
        for line in lines:
            # line = line.rstrip('\n')
            tempLogLinesToPost[key] += line

        if int(logLinesCount[key]) > maxLogLines:
            ### show total number of lines seen
            ###  lines exceeding maxLogLines are not collected in logLines[]
            tempLogLinesToPost[key] += ',' + "..... {0} total lines in this sampling interval .....".format( logLinesCount[key] )
        logLinesCount[key] = 0

        ### empty the list
        logLines[key] = []

        if debugLevel > 1:
            print('DEBUG-2 JAPostDataToWebServer() logLinesToPost: {0}'.format(tempLogLinesToPost))

        data = json.dumps(tempLogLinesToPost)

        if useRequests == True:
            # post interval elapsed, post the data to web server
            returnResult = requests.post(
                webServerURL, data, verify=verifyCertificate, headers=headers)
            
            print('INFO JAPostDataToWebServer() Result of posting log lines to web server ' +
                    webServerURL + ' :\n' + returnResult.text)
            numPostings += 1
        else:
            result = subprocess.run(['curl', '-k', '-X', 'POST', webServerURL, '-H',
                                    "Content-Type: application/json", '-d', data], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            returnStatus = result.stdout.decode('utf-8').split('\n')
            print('INFO JAPostDataToWebServer() result of posting log lines to web server:{0}\n{1}'.format(
                webServerURL, returnStatus))
            numPostings += 1

    JAGlobalLib.LogMsg('INFO  JAPostDataToWebServer() timeStamp: ' + timeStamp +
                       ' Number of log lines posted: ' + str(numPostings) + '\n', statsLogFileName, True)
    return True


"""
If processing the log file first time, start processing from the beginning
If resuming the processing after sleep, resume processing from prev position

"""
# log file info contains filePointer, current position
# ['name']
# ['filePosition']
# ['filePointer']
logFileInfo = defaultdict(dict)


"""
def JAWriteFileInfo()
Save log file name, file pointer position so that processing can resume from this position next time
"""


def JAWriteFileInfo():
    try:
        with open(cacheLogFileName, "w") as file:
            numItems = 0

            for key, value in logFileInfo.items():
                tempPosition = logFileInfo[key]['filePosition']
                tempPrevTime = logFileInfo[key]['prevTime']
                file.write('{0} {1} {2}'.format(
                    key, tempPosition, tempPrevTime))
                numItems += 1
                # close log file that was opened before
                # logFileInfo[key]['filePointer'].close()

            file.close()
        JAGlobalLib.LogMsg('INFO  JAWriteFileInfo() Wrote {0} log file info items to cache file: {1}\n'.format(
            numItems, cacheLogFileName), statsLogFileName, True)

        return True

    except OSError as err:
        errorMsg = 'ERROR - JAWriteFileInfo() Can not open file ' + JAGatherLogStatsCache + \
            ' to save log file info ' + "OS error: {0}".format(err) + '\n'
        print(errorMsg)
        JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
        return False


"""
def JAReadFileInfo()
Read log file name, file pointer position so that processing can resume from this position
"""


def JAReadFileInfo():
    try:
        if os.path.exists(cacheLogFileName) == False:
            return False
        with open(cacheLogFileName, "r") as file:
            while True:
                tempLine = file.readline()
                if not tempLine:
                    break
                fields = tempLine.split(' ')
                if len(fields) >= 3:
                    logFileInfo[fields[0]]['fileName'] = fields[0]
                    logFileInfo[fields[0]]['filePosition'] = fields[1]
                    logFileInfo[fields[0]]['prevTime'] = fields[2]
            file.close()
        return True

    except OSError as err:
        errorMsg = 'INFO - JAReadFileInfo() Can not open file ' + cacheLogFileName + \
            'to read log file info ' + "OS error: {0}".format(err) + '\n'
        print(errorMsg)
        JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)


def JAProcessLogFile(logFileName, startTimeInSec, logFileProcessingStartTime, gatherLogStatsEnabled, debugLevel):
    global averageCPUUsage, thisHostName, logEventPriorityLevel
    logFileNames = JAGlobalLib.JAFindModifiedFiles(
        logFileName, thisHostName, startTimeInSec, debugLevel)

    if logFileNames == None:
        return False

    for fileName in logFileNames:
        # use passed startTimeInSec if prev time is not stored for this file before
        prevTimeInSec = startTimeInSec

        if debugLevel > 0:
            print('DEBUG-1 JAProcessLogFile() Processing log file: ' + fileName)
        if logFileInfo.get(fileName) == None:
            firstTime = True
        elif logFileInfo[fileName].get('filePosition') == None:
            firstTime = True
        else:
            filePosition = int(logFileInfo[fileName].get('filePosition'))

            # if the file was overwritten with same log file name,
            # current file size can be less than filePosition store before
            if os.path.getsize(fileName) < filePosition:
                firstTime = True
            else:
                firstTime = False
                file = logFileInfo[fileName].get('filePointer')
                prevTimeInSec = logFileInfo[fileName].get('prevTime')

        # first time, open the file
        if firstTime == True:
            try:
                file = open(fileName, "r")
            except OSError as err:
                errorMsg = 'ERROR - JAProcessLogFile() Can not open logFile:| ' + fileName + \
                    '|' + "OS error: {0}".format(err) + '\n'
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
                # store error status so that next round, this will not be tried
                logFileInfo[fileName]['filePosition'] = 'ERROR'
                continue
        else:
            try:
                # if this program is just started and it read file position from cache file,
                # file pointer fill be None, need to open the file fresh
                if file == None:
                    file = open(fileName, "r")

                # position file pointer to the previous position
                file.seek(filePosition)
            except OSError as err:
                errorMsg = 'ERROR - JAProcessLogFile() Can not seek position in logFile:|' + \
                    fileName + '|' + "OS error: {0}".format(err) + '\n'
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
                # store error status so that next round, this will not be tried
                logFileInfo[fileName]['filePosition'] = 'ERROR'
                continue
        
        if gatherLogStatsEnabled == True:
            # if elapsed time is greater than max time for all events, SKIP processing log file for events
            elapsedTimeInSec = time.time() - logFileProcessingStartTime
            if elapsedTimeInSec > maxProcessingTimeForAllEvents:
                gatherLogStatsEnabled =  False

        # if gatherLogStatsEnabled is set to False, just move the file pointer to end of the file
        # so that next time, search can start from that position onwards.
        # do not search for patterns in log lines
        # this is to avoid overloading the system when CPU usage is higher than max limit set
        if gatherLogStatsEnabled == False:
            try:
                # position 0 bytes from end of file
                file.seek(0, 2)
                # end of file, save position info
                logFileInfo[fileName]['fileName'] = fileName
                logFileInfo[fileName]['filePointer'] = file
                logFileInfo[fileName]['filePosition'] = file.tell()
                logFileInfo[fileName]['prevTime'] = time.time()

            except OSError as err:
                errorMsg = 'ERROR - JAProcessLogFile() Can not go to end of file in logFile:|' + \
                    fileName + '|' + "OS error: {0}".format(err) + '\n'
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
                # store error status so that next round, this will not be tried
                logFileInfo[fileName]['filePosition'] = 'ERROR'
                continue

        else:
            # gatherLogStats enabled
            while True:
                # read line by line
                tempLine = file.readline()
                if not tempLine:
                    # end of file, pause processing for now
                    logFileInfo[fileName]['fileName'] = fileName
                    logFileInfo[fileName]['filePointer'] = file
                    logFileInfo[fileName]['filePosition'] = file.tell()
                    logFileInfo[fileName]['prevTime'] = time.time()
                    if debugLevel > 0:
                        print(
                            'DEBUG-1 JAProcessLogFile() Reached end of log file: ' + fileName)
                    break

                # SKIP short lines
                if len(tempLine) < 2:
                    continue

                if debugLevel > 3:
                    print(
                        'DEBUG-4 JAProcessLogFile() processing log line:' + tempLine + '\n')

                # search results are stored in logStats in below form
                # key - service name
                # values -  value1, presentFlag1, value2, presentFlag2,....
                # { 'AlarmCRIT': [ 0, False, 0, False, 2, True, 0, False],
                #   'ApacheICDR': [ 2, True, 0, False, 0, False, 0, False]}
                #                    pass      fail     count     stats

                # search for pass, fail, count, stats patterns of each service associated with this log file
                for key, values in JAStatsSpec[logFileName].items():
                    eventPriority = int(values[patternIndexForPriority])

                    patternMatched = patternLogMatched = False
                    
                    if debugLevel > 3:
                        print('DEBUG-4 JAProcessLogFile() searching for patterns:{0}|{1}|{2}|{3}|{4}|{5}\n'.format(
                            values[patternIndexForPatternPass], values[patternIndexForPatternFail], values[patternIndexForPatternCount], 
                            values[patternIndexForPatternSum], values[patternIndexForPatternAverage],values[patternIndexForPatternDelta]))
                    
                    if averageCPUUsage > maxCPUUsageForEvents[eventPriority]:
                        if logEventPriorityLevel == maxCPUUsageLevels:
                            ### first time log file processing skipped, store current event priorityy
                            logEventPriorityLevel = eventPriority
                        elif logEventPriorityLevel > eventPriority :
                            ## if previous event priority skipped is higher than current priority,
                            ##   save new priority
                            logEventPriorityLevel = eventPriority
                    else:
                        ### proceed with search if current CPU usage is lower than max CPU usage allowed
                        index = 0

                        ### if variable prefix is defined for current service, 
                        ###   see whether the variable prefix pattern is present in current line
                        variablePrefix = None
                        if values[patternIndexForVariablePrefix] != None:
                            variablePrefixSearchPattern = r'{0}'.format( values[patternIndexForVariablePrefix])
                            myResults = re.search( variablePrefixSearchPattern, tempLine)
                            if myResults == None:
                                ### since variable prefix is not matching, SKIP processing this line any further
                                # since variable prefix will be prefixed to variables, if that is not present,
                                #  no need to match any other patterns for this service 
                                continue
                            else:
                                if values[patternIndexForVariablePrefixGroup] != None:
                                    ### use the group value; based on pattern match, as variable prefix.
                                    ### Log line: 2021-10-05T01:09:03.249334 Stats MicroService25 total key1 9 dummy1 total key2 4.50 dummy2
                                    ###                                                        ^^ <-- variablePrefixGroupValues (two groups)
                                    ### PatternVariablePrefix: Stats MicroService(\d)(\d) total
                                    ###                                                ^ <-- variable prefix, group 2
                                    ###  use 2nd group value as variable prefix for the *_avrage metrics variable
                                    ###  PatternVariablePrefixGroup: 2
                                    variablePrefix = myResults.group(int(values[patternIndexForVariablePrefixGroup]))
                                else:
                                    variablePrefix = myResults.group(1)

                        ### values is indexed from 0 to patternIndexForPatternSum / patternIndexForPatternAverage / patternIndexForPatternDelta
                        ### logStats[key] is indexed with twice the value
                        while index < len(values):

                            if index == patternIndexForPriority or index == patternIndexForVariablePrefix or index == patternIndexForVariablePrefixGroup or values[index] == None:
                                index += 1
                                continue

                            if index == patternIndexForPatternLog and patternLogMatched == False:
                                searchPattern = r'{0}'.format(values[index])
                                ### search for matching PatternLog regardless of whether stats type pattern is found or not.
                                if re.search(searchPattern, tempLine) != None:
                                    ### matching pattern found, collect this log line
                                    if int(logLinesCount[key]) < maxLogLines:
                                        ### store log lines if number of log lines to be collected within a sampling interval is under maxLogLines
                                        logLines[key].append(tempLine)
                                    ### increment the logLinesCount
                                    logLinesCount[key] += 1
                                    patternLogMatched = True

                            elif patternMatched != True:
                                logStatsKeyValueIndexEven = index * 2
                                logStatsKeyValueIndexOdd = logStatsKeyValueIndexEven + 1
                                
                                searchPattern = r'{0}'.format(values[index])
                                if index == patternIndexForPatternSum or index == patternIndexForPatternAverage or index == patternIndexForPatternDelta :
                                    ### special processing needed to extract the statistics from current line
                                    
                                    myResults = re.findall( searchPattern, tempLine)
                                    if myResults != None and len(myResults) > 0 :
                                        ### current line has stats in one or more places. Aggregate the values
                                        ### the pattern spec is in the format
                                        ###   <pattern>(Key1)<pattern>(value1)<pattern>key2<pattern>value2....
                                        numStats = 0

                                        ### make a copy of current list values
                                        tempStats = list(logStats[key][logStatsKeyValueIndexOdd])

                                        ### make a copy of sampleCountList values for average type metrics
                                        if index == patternIndexForPatternAverage :
                                            sampleCountList = list(logStats[key][logStatsKeyValueIndexEven])

                                        ### myResults is of the form = [ (key1, value1, key2, value2....)]
                                        tempResults = myResults.pop(0)

                                        if debugLevel > 3:
                                            print("DEBUG-4 JAProcessLogFile() processing line with PatternDelta, PatternSum or PatternAverage, search result:{0}\n Previous values:{1}".format(myResults, tempStats))
                                        tempKey = ''
                                        appendCurrentValueToList = False
                                        indexToCurrentKeyInTempStats = 0
                                        for tempResult in tempResults:
                                                
                                            if numStats % 2 == 0:
                                                ### if current name has space, replace it with '_'
                                                tempResult = re.sub('\s','_',tempResult)

                                                ### if variable prefix is present, prefix that to current key
                                                if variablePrefix != None :
                                                    tempResult = '{0}_{1}'.format( variablePrefix, tempResult)

                                                ### if current key is NOT present in list, append it
                                                # if len(tempStats) <= numStats :
                                                try:
                                                    tempIndexToCurrentKeyInTempStats = tempStats.index( tempResult)
                                                    if tempIndexToCurrentKeyInTempStats >= 0 :
                                                        appendCurrentValueToList = False
                                                        ### in order to store key/value pair associated with variable prefefix
                                                        ###    need to find the index at which that variablePrefix_key is present
                                                        ##     in the list and use that to aggregate the value
                                                        indexToCurrentKeyInTempStats = tempIndexToCurrentKeyInTempStats                                                        
                                                except ValueError:
                                                    ### value is NOT present in tempStats list
                                                    appendCurrentValueToList = True
                                                    ### current tempResult is not yet in the list, append it
                                                    tempStats.append(tempResult)
                                                    if index == patternIndexForPatternAverage :
                                                        sampleCountList.append(1)

                                                ### save the key name, this is used to make a combined key later <serviceName>_<key>
                                                tempKey = tempResult
                                            else:
                                                ## value portion of key/ value pair
                                                ## if index is patternIndexForPatternDelta, tempResult is cumulative value, need to subtract previous sample
                                                ## value to get delta value and store it as current sample value.
                                                if  index == patternIndexForPatternDelta:
                                                    serviceNameSubKey = "{0}_{1}".format( key, tempKey)
                                                    tempResultToStore = float(tempResult)
                                                    if previousSampleValues[serviceNameSubKey] != None:
                                                        ### previous value present, subtract prev value from current value to get delta value for current sample
                                                        tempResult = float(tempResult) - previousSampleValues[serviceNameSubKey]
                                                    
                                                    ### store current sample value as is as previous sample
                                                    previousSampleValues[serviceNameSubKey] = tempResultToStore
                                                
                                                if appendCurrentValueToList == True:
                                                    ### current tempResult is not yet in the list, append it
                                                    tempStats.append(float(tempResult))
                                                    ### if working average type metrics, set sample count in the list corresponding to 
                                                    ###     current key in key/value list
                                                    if index == patternIndexForPatternAverage :
                                                        sampleCountList.append(1)

                                                else:
                                                    ### add to existing value
                                                    tempStats[indexToCurrentKeyInTempStats+1] += float(tempResult)

                                                    ### if working average type metrics, increment sample count in the list corresponding to 
                                                    ###     current key in key/value list
                                                    if index == patternIndexForPatternAverage :
                                                        sampleCountList[indexToCurrentKeyInTempStats+1] += 1
                                            numStats += 1

                                        ### for average type, sample count is incremented based for ecach prefix variable key values   
                                        if index == patternIndexForPatternAverage :
                                            logStats[key][logStatsKeyValueIndexEven] = list(sampleCountList)
                                        else:
                                            ### increment sample count
                                            logStats[key][logStatsKeyValueIndexEven] += 1

                                        ### store tempStats as list
                                        logStats[key][logStatsKeyValueIndexOdd] = list(tempStats)

                                        if debugLevel > 3:
                                            print('DEBUG-4 JAProcessLogFile() key: {0}, found pattern:|{1}|, numSamples:{2}, stats: {3}'.format(
                                                key, values[index], logStats[key][logStatsKeyValueIndexEven], logStats[key][logStatsKeyValueIndexOdd] ))
                                        ### get out of the loop
                                        patternMatched = True
                                elif re.search(searchPattern, tempLine) != None:
                                    ### matching pattern found, increment the count 
                                    logStats[key][logStatsKeyValueIndexEven] += 1

                                    if debugLevel > 3:
                                        print('DEBUG-4 JAProcessLogFile() key: {0}, found pattern:|{1}|, stats: {2}'.format(
                                                key, values[index], logStats[key][logStatsKeyValueIndexEven] ))
                                    ### get out of the loop
                                    patternMatched = True
                            
                            ## if both log pattern and stats pattern matched, get out of the while loop
                            if patternMatched == True and patternLogMatched == True:
                                break
                            else:
                                ### increment index so that search continues with next pattern
                                index += 1         
                    ## if log pattern or stats pattern matched, get out of the for loop
                    ## once a given line matched to a log or stats pattern, search for matching pattern stops
                    if patternMatched == True or patternLogMatched == True:
                        break


    return True


# read file info saved during prev run
# JAReadFileInfo()

# reduce process priority
if OSType == 'Windows':

    if psutilModulePresent == True:
        import psutil
        psutil.Process().nice(psutil.LOW_PRIORITY_CLASS)
else:
    # on all unix hosts, reduce to lowest priority
    os.nice(19)
    if debugLevel > 1:
        print("DEBUG-2 process priority: {0}".format(os.nice(0)))

### delete old log files
if OSType == 'Windows':
    ### TBD expand this later 
    logFilesToDelete = None

else:
    tempFileNameToDelete = '{0}*'.format(statsLogFileName)
    result =  subprocess.run(['find', '-name', tempFileNameToDelete, '-mtime', '+7'],stdout=subprocess.PIPE,stderr=subprocess.PIPE) 
    logFilesToDelete = result.stdout.decode('utf-8').split('\n')

if logFilesToDelete != None:
    for deleteFileName in logFilesToDelete:
        if deleteFileName != '':
            os.remove( deleteFileName)

# get current time in seconds since 1970 jan 1
programStartTime = loopStartTimeInSec = time.time()
statsEndTimeInSec = loopStartTimeInSec + dataCollectDurationInSec

# first time, sleep for dataPostIntervalInSec so that log file can be processed and posted after waking up
sleepTimeInSec = dataPostIntervalInSec

# initially, enable log stats gathering.
# disable this if CPU usage average exceeds the threshold level set
JAGatherLogStatsEnabled = True

# take current time, it will be used to find files modified since this time for next round
logFileProcessingStartTime = time.time()

# open all log files, position the file pointer to the end of the file
# this is to avoid counting transactions outside one minute window and showing higher tps than actual
for logFileName in sorted(JAStatsSpec.keys()):
    ### pass 0 for start time reference so that only latest file is picked for processing
    ### pass False for JAGatherLogStatsEnabled so that file pointers are moved to end of file
    JAProcessLogFile(logFileName, 0, logFileProcessingStartTime,
                        False, debugLevel)

# until the end time, keep checking the log file for presence of patterns
# and post the stats per post interval
while loopStartTimeInSec <= statsEndTimeInSec:
    if debugLevel > 0:
        if sys.version_info >= (3, 3):
            myProcessingTime = time.process_time()
        else:
            myProcessingTime = 0
        print('DEBUG-1 log file(s) processing time: {0}, Sleeping for: {1} sec'.format(
            myProcessingTime, sleepTimeInSec))
    time.sleep(sleepTimeInSec)

    # take current time, it will be used to find files modified since this time for next round
    logFileProcessingStartTime = time.time()

    ### for each loop, reset the value
    logEventPriorityLevel = maxCPUUsageLevels

    averageCPUUsage = JAGlobalLib.JAGetAverageCPUUsage()
    if averageCPUUsage > maxCPUUsageForEvents[0]:
        JAGatherLogStatsEnabled = False
        logEventPriorityLevel = 0

    # gather log stats for all logs
    for logFileName in sorted(JAStatsSpec.keys()):
        JAProcessLogFile(logFileName, loopStartTimeInSec, logFileProcessingStartTime,
                         JAGatherLogStatsEnabled, debugLevel)

    # post the data to web server if the gathering is enabled.
    if JAGatherLogStatsEnabled == True:
        # post collected stats to Web Server
        JAPostDataToWebServer()
    else:
        errorMsg = "WARN  Current CPU Usage: {0} is above max CPU usage level specified: {1}, Skipped gathering Log stats".format(
            averageCPUUsage, maxCPUUsageForEvents)
        print(errorMsg)
        JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)

    # if elapsed time is less than post interval, sleep till post interval elapses
    elapsedTimeInSec = time.time() - logFileProcessingStartTime
    if elapsedTimeInSec < dataPostIntervalInSec:
        sleepTimeInSec = dataPostIntervalInSec - elapsedTimeInSec
    else:
        sleepTimeInSec = 0

    # take curren time so that processing will start from current time
    loopStartTimeInSec = logFileProcessingStartTime


# Save file info to be used next round
# JAWriteFileInfo()

if sys.version_info >= (3, 3):
    myProcessingTime = time.process_time()
else:
    myProcessingTime = 'N/A'

programEndTime = time.time()
programExecTime = programEndTime - programStartTime

JAStatsExit('PASS  Processing time this program: {0}, programExecTime: {1}'.format(
    myProcessingTime, programExecTime))
