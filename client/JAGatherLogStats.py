#!/usr/bin/python3

""" 
This script gathers and POSTs log stats to remote web server
Posts jobName=LogStats, hostName=<thisHostName>, fileName as parameter in URL
Posts <key> {metric1=value1, metric2=value2...} one line per key type as data

Parameters passed are:
    configFile - yaml file containing stats to be collected
        default - JAGatherLogStats.yml 
    webServerURL - post the data collected to web server 
        default - get it from JAGatherLogStats.yml 
    dataPostIntervalInSec - post data at this periodicity, in seconds
        default - get it from JAGatherLogStats.yml
    dataCollectDurationInSec - collect data for this duration once started
            when started from crontab, run for this duration and exit
            default - get it from JAGatherLogStats.yml

    debugLevel - 0, 1, 2, 3
        default = 0

returnResult
    Print result of operation to log file 

Author: havembha@gmail.com, 2021-07-18
"""
import yaml 
from collections import defaultdict
import os, sys, re
import datetime 
import JAGlobalLib
import time
import subprocess
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
               err = subprocess.CalledProcessError(self.returncode, self.args, output=self.stdout)
               raise err
               return self.returncode

        def sp_run(*popenargs, **kwargs):
            input = kwargs.pop("input", None)
            check = kwargs.pop("handle", False)
            if input is not None:
                if 'stdin' in kwargs:
                    raise ValueError('stdin and input arguments may not both be used.')
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
                raise subprocess.CalledProcessError(returncode, popenargs, output=outs)
            return CompletedProcess(popenargs, returncode, stdout=outs, stderr=errs)

            subprocess.run = sp_run
            # ^ This monkey patch allows it work on Python 2 or 3 the same way


## global default parameters
configFile = None 
webServerURL = None
dataPostIntervalInSec = 0
dataCollectDurationInSec = 0
debugLevel = 0
statsLogFileName =  None 
componentName = None
platformName = None
siteName = None
disableWarnings = None
verifyCertificate = None
cacheLogFileName = None

### contains current stats
logStats = defaultdict(dict)
### Linux time reference URL - https://www.cyberciti.biz/faq/linux-unix-formatting-dates-for-display/
dateTimeFormats = defaultdict(dict)
dateTimeFormats['ISO']      = ['yyyy-mm-ddTHH:MM:SS',   '\d\d\d\d-\d\d-\d\dT\d\d:\d\d:\d\d']
dateTimeFormats['USA']      = ['mm-dd-yyyy HH:MM:SS',   '\d\d-\d\d-\d\d\d\d \d\d:\d\d:\d\d']
dateTimeFormats['EU']       = ['dd-mm-yyyy HH:MM:SS',   '\d\d-\d\d-\d\d\d\d \d\d:\d\d:\d\d']
dateTimeFormats['apache']   = ['dd-bbb-yyyy HH:MM:SS',  '\d\d/\w\w\w/\d\d\d\d:\d\d:\d\d:\d\d']
dateTimeFormats['time']     = ['HH:MM:SS',              '\d\d:\d\d:\d\d']


### take current timestamp
statsStartTimeInSec = statsEndTimeInSec = time.time() 

## parse arguments passed from command line
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-D", type=int, help="debug level 0 - None, 1,2,3-highest level")
parser.add_argument("-c", help="yaml file containing stats to be collected, default - JAGatherLogStats.yml")
parser.add_argument("-U", help="web server URL to post the data, default - get it from configFile")
parser.add_argument("-i", type=int, help="data post interval in sec, default - get it from configFile")
parser.add_argument("-d", type=int, help="data collect duration in sec, default - get it from configFile")
parser.add_argument("-C", help="component name, default - none")
parser.add_argument("-P", help="platform name, default - none")
parser.add_argument("-S", help="site name, default - none")
parser.add_argument("-E", help="environment like dev, test, uat, prod, default - test")
parser.add_argument("-l", help="log file name, including path name")

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

if debugLevel > 0 :
    print('DEBUG-1 Parameters passed configFile: {0}, WebServerURL: {1}, dataPostIntervalInSec: {2}, dataCollectDurationInSec: {3}, debugLevel: {4}, componentName: {5}, platformName: {6}, siteName: {7}, environment: {8}'.format(configFile, webServerURL, dataPostIntervalInSec, dataCollectDurationInSec, debugLevel, componentName, platformName, siteName, environment))

def JAStatsExit(reason):
    print(reason)
    JAStatsDurationInSec = statsEndTimeInSec - statsStartTimeInSec
    JAGlobalLib.LogMsg( '[0} processing duration: {1} sec\n'.format( reason, JAStatsDurationInSec, statsLogFileName, True))
    sys.exit()

### use default config file
if configFile == None:
    configFile = "JAGatherLogStats.yml"
### list containing log file names
JALogFileNames = []

### stats spec with service name as key
JAStatsSpec = defaultdict(dict) 

### get current hostname
import platform
thisHostName = platform.node()

### based on current hostName, this variable will be set to Dev, Test, Uat, Prod etc
myEnvironment= None

numSamplesToPost = None
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
def JAGatherEnvironmentSpecs( key, values ):

    ### declare global variables
    global dataPostIntervalInSec, dataCollectDurationInSec 
    global webServerURL, disableWarnings, verifyCertificate, numSamplesToPost

    for myKey, myValue in values.items():
        if debugLevel > 1 :
            print('DEBUG-2 JAGatherEnvironmentSpecs() key: {0}, value: {1}'.format( myKey, myValue))
        if myKey == 'DataPostIntervalInSec': 
            if dataPostIntervalInSec == 0:
                if myValue != None:
                    dataPostIntervalInSec = int(myValue)
                elif key == 'All':
                    ### apply default if value is not defined in environment and 'All' section
                    dataPostIntervalInSec = 60

        elif myKey == 'DataCollectDurationInSec': 
            if dataCollectDurationInSec == 0:
                if myValue != None:
                    dataCollectDurationInSec = int(myValue)
                elif key == 'All': 
                    dataCollectDurationInSec = 600 

        elif myKey == 'WebServerURL':
            if webServerURL == None:
                if myValue != None:
                    webServerURL = myValue 
                elif key == 'All':
                    JAStatsExit( 'ERROR mandatory param WebServerURL not available')

        elif myKey == 'DisableWarnings': 
            if disableWarnings == None:
                if myValue != None:
                    disableWarnings = myValue
                elif key == 'All':
                    disableWarnings = True

        elif myKey == 'VerifyCertificate':
            if verifyCertificate == None:
                if myValue != None:
                    verifyCertificate = myValue
                elif key == 'All':
                    verifyCertificate = True

        if debugLevel > 1 :
            print('DEBUG-2 JAGatherEnvironmentSpecs(), DataPostIntervalInSec:{0}, DataCollectDurationInSec: {1}, DisableWarnings: {2}, verifyCertificate: {3}, WebServerURL: {4}'.format( dataPostIntervalInSec, dataCollectDurationInSec, disableWarnings, verifyCertificate, webServerURL))

## read default parameters and OS Stats collection spec
try:
    with open(configFile, "r") as file:
        JAStats = yaml.load(file, Loader=yaml.FullLoader)
        
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
                ### if parameters are not yet defined, read the values from this section
                ###  values in this section work as default if params are defined for 
                ###  specific environment
                JAGatherEnvironmentSpecs( key, value )

            if value.get('HostName') != None:
                if re.match( value['HostName'], thisHostName):
                    ### current hostname match the hostname specified for this environment
                    ###  read all parameters defined for this environment
                    JAGatherEnvironmentSpecs( key, value )
                    myEnvironment = key 

        dateTimeFormatType = None 
        ### read spec for each log file
        ### LogFile: 
        ###     Name: <fileName>
        ###     Service:
        ###         Name: name
        ###         PatternPass: string containing regular expression
        ###         PatternFail: string containing regular expression
        ###         PatternCount: string containing regular expression
        for key, value in JAStats['LogFile'].items():
            patternPass =  patternFail = patternCount = None
            patternPassPresent =  patternFailPresent = patternCountPresent = False 
                # JAGatherServiceSpec(currentLogFileName, value)
            if value.get('LogFileName') != None:
                logFileName = str(value.get('LogFileName'))

            if value.get('DateTimeFormat') != None:
                dateTimeFormat = str(value.get('DateTimeFormat'))
                for key, values in dateTimeFormats.items():
                    if dateTimeFormat == values[1]:
                        dateTimeFormatType = key
                if dateTimeFormatType == None:
                    print('ERROR Unsupported DateTimeFormat:' + dateTimeFormat + ' for LogFileName:' + logFileName)

            if value.get('PatternPass') != None:
                patternPass = value.get('PatternPass')
                patternPassPresent = True 

            if value.get('PatternFail') != None:
                patternFail = value.get('PatternFail')
                patternFailPresent = True

            if value.get('PatternCount') != None:
                patternCount = value.get('PatternCount')
                patternCountPresent = True

            if logFileName != None:
                JAStatsSpec[logFileName][key] = [ patternPass, patternFail, patternCount]
                if debugLevel > 1 :
                    print('DEBUG-2 key: {0}, value: {1} {2}'.format( key, value, JAStatsSpec[logFileName][key]) )
            #if dateTimeFormat != None:
            #    JAStatsSpec[logFileName]['DateTimeFormat'] = re.compile(dateTimeFormat)
            #if dateTimeFormatType != None:
            #    JAStatsSpec[logFileName]['DateTimeFormatType'] = dateTimeFormatType
            ### initialize counts to 0
            ###  set present flag if that count is to be posted to web server
            logStats[key] = [ 0,patternPassPresent,0,patternFailPresent,0,patternCountPresent]

        file.close()

except OSError as err:
    JAStatsExit('ERROR - Can not open configFile:|' + configFile + '|' + "OS error: {0}".format(err) + '\n')

if debugLevel > 0:
    print('DEBUG-1 Parameters after reading configFile: {0}, webServerURL: {1},  dataPostIntervalInSec: {2}, dataCollectDurationInSec: {3}, debugLevel: {4}'.format( configFile, webServerURL,dataPostIntervalInSec, dataCollectDurationInSec, debugLevel) )
    for key, spec in JAStatsSpec.items():
        print('DEBUG-1 Name: {0}, Fields: {1}'.format( key, spec))

### if another instance is running, exit
result =  subprocess.run(['ps', '-ef'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
returnProcessNames = result.stdout.decode('utf-8').split('\n')
procCount = 0
for procName in returnProcessNames:
   if re.search( 'JAGatherLogStats.py', procName ) != None :
       if re.search( r'vi |more |view ', procName ) == None:
           procCount += 1
           if procCount > 1:
                JAStatsExit('WARN - another instance (' + procName + ') is running, exiting' )


returnResult = ''
logStatsToPost = defaultdict(dict) 

### data to be posted to the web server
### pass fileName containing thisHostName and current dateTime in YYYYMMDD form
logStatsToPost['fileName'] = thisHostName + ".LogStats." + JAGlobalLib.UTCDateForFileName()  
logStatsToPost['jobName' ] = 'LogStats'
logStatsToPost['hostName'] = thisHostName
logStatsToPost['debugLevel'] = debugLevel
logStatsToPost['componentName'] = componentName 
logStatsToPost['platformName'] = platformName
logStatsToPost['siteName'] = siteName 
logStatsToPost['environment'] = environment

import requests
import json
headers= {'Content-type': 'application/json', 'Accept': 'text/plain'} 
if disableWarnings == True:
    requests.packages.urllib3.disable_warnings()

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
    global webServerURL, verifyCertificate, logStatsToPost
    timeStamp = JAGlobalLib.UTCDateTime() 
    if debugLevel > 1:
        print('DEBUG-2 JAPostDataToWebServer() ' + timeStamp + ' Posting the stats collected')

    numPostings = 0
    ### sampling interval elapsed
    ### push current sample stats to the data to be posted to the web server
    for key, values in logStats.items():
        logStatsToPost[key] = "timeStamp=" + timeStamp
        if values[1] == True:
            logStatsToPost[key] += "," + key + "_pass=" + str(values[0])
        if values[3] == True:
            logStatsToPost[key] += "," + key + "_fail=" + str(values[2])
        if values[5] == True:
            logStatsToPost[key] += "," + key + "_count=" + str(values[4])

        #logStatsToPost[key] = f'timeStamp={timeStamp},{key}_pass={values[0]},{key}_fail={values[2]},{key}_count={values[4]}'
        ### clear stats for next sampling interval
        values[0] = values[2] = values[4] = 0

    ### post interval elapsed, post the data to web server
    returnResult = requests.post( webServerURL, data=json.dumps(logStatsToPost), verify=verifyCertificate, headers=headers)
    if debugLevel > 1:
        print ('DEBUG-2 logStatsToPost: {0}'.format(logStatsToPost))
        print('Result of posting data to web server ' + webServerURL + ' :\n' + returnResult.text)
    numPostings += 1

    JAGlobalLib.LogMsg('INFO  JAPostDataToWebServer() timeStamp: ' + timeStamp + ' Number of stats posted: ' + str(numPostings) + '\n', statsLogFileName, True)
    return True

"""
If processing the log file first time, start processing from the beginning
If resuming the processing after sleep, resume processing from prev position


"""
### log file info contains filePointer, current position
###  ['name']
###  ['filePosition']
###  ['filePointer']
logFileInfo = defaultdict(dict) 

"""
def JAIsTimeStampInRange( tempLine, startTime  )

This function checks the timestamp in current line,
  if timestamp is greater than or equal to start time passed, returns True
  else, returns False
"""
def JAIsTimeStampInRange( tempLine, startTime, dateTimeFormat, dateTimeFormatType  ):
    returnStatus = True
    if dateTimeFormat == None or dateTimeFormatType == None:
        print('ERROR JAIsTimeStampInRange() Pass values for dateTimeFormat, and dateTimeFormatType')
        return False

    tempDateTime = re.search( dateTimeFormat, tempLine )
    if tempDateTime != None:
        ### current line has time stamp in desired format
        ### convert the timestamp to standard format (match to the type of startTime object)
        if dateTimeFormatType == 'ISO':
            currentTime = startTime
        elif dateTimeFormatType == 'USA':
            currentTime = startTime

        elif dateTimeFormatType == 'EU':
            currentTime = startTime
        
        elif dateTimeFormatType == 'apache':
            currentTime = startTime

        elif dateTimeFormatType == 'time':
            currentTime = startTime

        else:
            print('ERROR JAIsTimeStampInRange() date time format: ' + dateTimeFormat + ', dateTimeFormatType:' + dateTimeFormatType + ' not supported')
            return False

    return returnStatus, timeStampType

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
                file.write(key + ' ' + tempPosition + ' ' +  tempPrevTime + '\n')
                numItems += 1
                ### close log file that was opened before
                ### logFileInfo[key]['filePointer'].close()

            file.close()
        JAGlobalLib.LogMsg('INFO  JAWriteFileInfo() Wrote ' + numItems + ' log file info items to cache file: ' + cacheLogFileName + '\n', statsLogFileName, True)

        return True

    except OSError as err:
        errorMsg = 'ERROR - JAWriteFileInfo() Can not open file ' + JAGatherLogStatsCache + ' to save log file info ' + "OS error: {0}".format(err) + '\n'
        print(errorMsg)
        JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
        return False        
"""
def JAReadFileInfo()
Read log file name, file pointer position so that processing can resume from this position
"""
def JAReadFileInfo():
    try:
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

    except OSError as err:
         errorMsg = 'INFO - JAReadFileInfo() Can not open file ' + cacheLogFileName + 'to read log file info ' + "OS error: {0}".format(err) + '\n'
         print(errorMsg)
         JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
"""
def JAGetModifiedFileNames( logFileName, startTime)
JAGetModifiedFileNames( logFileName, startTime)
Get list of log file names modified in last one min
for each file name,
  find last modified time
  if that time is older than starTime passed, skip that file
  else, store the file name along with last modified time

sort the file names based on ascending time of last modified time

Return Values:
    fileNames in list form

"""
def JAGetModifiedFileNames( logFileName, startTimeInSec, debugLevel):
    ### separate file path and filename portion
    ###  passing both together does not work in python
    ###  head_tail[0] - dirPath
    ###  head_tail[1] - fileName
    head_tail = os.path.split(logFileName)

    ### if  no path specified use ./ (current working directory)
    if head_tail[0] == '' or head_tail[0] == None:
        myDirPath = './'
    else:
        myDirPath = head_tail[0]

    result =  subprocess.run(['find', myDirPath, '-mmin', '-1', '-name', head_tail[1], '-type', 'f' ],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    fileNames = result.stdout.decode('utf-8').split('\n')
    returnFileNames = {}

    for fileName in fileNames:
        if os.path.isfile( fileName) == True:
            fileModifiedTime = os.path.getmtime( fileName )
            if fileModifiedTime > startTimeInSec:
                returnFileNames[ fileModifiedTime ] = fileName
    
    sortedFileNames = []

    for fileMTime, fileName  in sorted(returnFileNames.items()):
        sortedFileNames.append( fileName )

    if debugLevel > 0:
        print('DEBUG-1 JAFindAllLogFileNames() logFileName: {0}, log files changed since epoch time {1}, log files changed since epoch time {2}'.format( logFileName, startTimeInSec, sortedFileNames) )
    return sortedFileNames

def JAProcessLogFile( logFileName, startTimeInSec, debugLevel ):

   logFileNames = JAGetModifiedFileNames( logFileName, startTimeInSec, debugLevel)

   if len(logFileNames) <= 0:
       return False

   for fileName in logFileNames:
       ### use passed startTimeInSec if prev time is not stored for this file before
       prevTimeInSec = startTimeInSec

       if debugLevel > 0:
            print ('DEBUG-1 JAProcessLogFile() Processing log file: ' + fileName )
       if logFileInfo.get(fileName) == None:
            firstTime = True
       elif logFileInfo[fileName].get('filePosition') == None:
            firstTime = True
       else:
            filePosition = int(logFileInfo[fileName].get('filePosition'))

            ### if the file was overwritten with same log file name,
            ###   current file size can be less than filePosition store before
            if os.path.getsize( fileName ) < filePosition :
                firstTime = True
            else:
                firstTime = False
                file = logFileInfo[fileName].get('filePointer')
                prevTimeInSec = logFileInfo[fileName].get('prevTime')

        ## first time, open the file
       if firstTime == True:
            try:
                file = open(fileName, "r")
            except OSError as err:
                errorMsg = 'ERROR - JAProcessLogFile() Can not open logFile:| ' + fileName + '|' + "OS error: {0}".format(err) + '\n'
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
                ### store error status so that next round, this will not be tried
                logFileInfo[fileName]['filePosition']='ERROR'
                continue
       else:
            try:
                ### if this program is just started and it read file position from cache file,
                ###   file pointer fill be None, need to open the file fresh
                if file == None:
                    file = open(fileName, "r")

                ### position file pointer to the previous position
                file.seek( filePosition )
            except OSError as err:
                errorMsg = 'ERROR - JAProcessLogFile() Can not seek position in logFile:|' + fileName + '|' + "OS error: {0}".format(err) + '\n'
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, statsLogFileName, True)
                ### store error status so that next round, this will not be tried
                logFileInfo[fileName]['filePosition']='ERROR'
                continue

       ### get the date time format to be used while parsing this log file
       #dateTimeFormat = logFileInfo[fileName].get('DateTimeFormat') 
       #dateTimeFormatType = logFileInfo[fileName].get('DateTimeFormatType') 
       while True:
           ### read line by line
           tempLine = file.readline()
           if not tempLine:
               ### end of file, pause processing for now
               logFileInfo[fileName]['fileName'] = fileName 
               logFileInfo[fileName]['filePointer'] = file
               logFileInfo[fileName]['filePosition'] = file.tell()
               logFileInfo[fileName]['prevTime'] = time.time()
               if debugLevel > 0:
                   print ('DEBUG-1 JAProcessLogFile() Reached end of log file: ' + fileName )
               break

           ### search for pass, fail, count patterns of each service associated with this log file
           for key, values in JAStatsSpec[logFileName].items():
               pattern0 = values[0]
               pattern1 = values[1]
               pattern2 = values[2]

               if pattern0 != None and re.search( pattern0, tempLine) != None:
                   logStats[key][0] += 1
               elif pattern1 != None and re.search( pattern1, tempLine) != None:
                   logStats[key][2] += 1
               elif pattern2 != None and re.search( pattern2, tempLine) != None:
                   logStats[key][4] += 1

   return True

### read file info saved during prev run
JAReadFileInfo()

### get current time in seconds since 1970 jan 1
programStartTime = loopStartTimeInSec = time.time() 
statsEndTimeInSec = loopStartTimeInSec + dataCollectDurationInSec

### first time, sleep for dataPostIntervalInSec so that log file can be processed and posted after waking up
sleepTimeInSec = dataPostIntervalInSec

### until the end time, keep checking the log file for presence of patterns
###   and post the stats per post interval
while loopStartTimeInSec  <= statsEndTimeInSec :
   if debugLevel > 0:
       myProcessingTime = time.process_time()
       print('DEBUG-1 log file(s) processing time: {0}, Sleeping for: {1} sec'.format( myProcessingTime, sleepTimeInSec ))
   time.sleep( sleepTimeInSec)

   ### take current time, it will be used to find files modified since this time for next round
   logFileProcessingStartTime = time.time()

   ## gather log stats for all logs
   for logFileName in sorted (JAStatsSpec.keys()):
        JAProcessLogFile( logFileName, loopStartTimeInSec, debugLevel )

   ### post collected stats to Web Server
   JAPostDataToWebServer()

   ### if elapsed time is less than post interval, sleep till post interval elapses
   elapsedTimeInSec = time.time() - logFileProcessingStartTime
   if elapsedTimeInSec < dataPostIntervalInSec :
        sleepTimeInSec = dataPostIntervalInSec - elapsedTimeInSec
   else:
       sleepTimeInSec = 0

   ### take curren time so that processing will start from current time
   loopStartTimeInSec = logFileProcessingStartTime 


### if any data is present, post those
### JAPostDataToWebServer()

### Save file info to be used next round  
JAWriteFileInfo()

myProcessingTime = time.process_time()
programEndTime = time.time()
programExecTime = programEndTime - programStartTime
JAStatsExit( 'PASS  Processing time this program:' + myProcessingTime + ', programExecTime:' + programExecTime )
