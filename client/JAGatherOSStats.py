
""" 
This script gathers and POSTs OS stats to remote web server
Posts jobName=OSStats, hostName=<thisHostName>, fileName, component, platform, site, environment, debugLevel as parameter in URL
Posts <key> {metric1=value1, metric2=value2...} one line per key type as data

Parameters passed are:
-c    configFile - yaml file containing stats to be collected
        default -  JAGatherOSStats[<OSType>].yml
-U    webServerURL - post the data collected to web server 
        default - get it from config file
-i    dataPostIntervalInSec - sample data at this periodicity, in seconds
        default - get it from config file
-d    dataCollectDurationInSec - post data for this duration, in seconds
        default - get it from config file
            if dataPostIntervalInSec is one min, and dataCollectDurationInSec is 10 min,  
                it will post 10 samples
-C component Name or host type, this value can be used in grafana dashboard to select a host
-S site name, this value can be used in grafana dashboard to select a host
-E environment, like dev, test, prod. This value can be used in grafana dashboard to select a host
-D    debugLevel - 0, 1, 2, 3
        default = 0
-l logFileName, initial part of log file name

returnResult
    Print result of operation to log file 

Note - did not add python interpreter location at the top intentionally so that
    one can execute this using python or python3 depending on python version on target host

Author: havembha@gmail.com, 2021-07-04

Execution flow
   Get OSType, OSName, OSVersion
   If config file not passed, use OSType specific config file name if present with the name JAGatherOSStats<OSType>.yml 
   Else use default file JAGatherOSStats.yml
   Based on python version, check for availability of yaml, psutil modules
   Read config file, using current hostname, gather matching environment spec
   If another instance of this program running, wait for that task to complete
   Delete log file older than 7 days (not supported on windows yet)
   Call below stats gathering functions to get initial snapshot. These values will be used later to find delta values between two sample intervals
      psutil.cpu_times_percent(), psutil.cpu_percent()
      JAGetCPUPercent(), JAGetDiskIOCounters(), JAGetNetworkIOCounters()
   While current time less than data collection end time,
     Sleep for the data post interval (in sec)
     For each stats type enabled in config file,
        Gather stats using appropriate method
        Parse the stats to formulate the data in fieldNameX1=valueY1,fieldNameX1=valueY2,... format
     Convert data to json string
     If requests module is present, use that to post the data to web server
     Else, use curl to post the data to web server

 2021-08-15 Added capability to collect file system usage percentage for given filesystem name(s)
    Added capability use sar data if present instead of collecting data fresh

2021-12-20 When config file is not passed, used OS specific config file if present with the name
    JAGatherOSStats<OSType>.yml where OSType can be Windows, Linux, ...
    Else, generic config file JAGatherOSStats.yml is used.

    If multiple process instances are present with the same process name, the stats are
      aggregated for all those process instances.

2022-07-10 version 1.30.00
    Supported sending data to influxDB

2022-09-10 version 1.31.00
    Collected OS_uptime and process elapsed time (etime) in Linux (not supported on Windows yet)
"""
import os, sys, re
import datetime
import JAGlobalLib
import time
import subprocess
import signal
from collections import defaultdict

### MAJOR 1, minor 31, buildId 00
JAVersion = "01.31.00"

## global default parameters
### config file containing OS Stats to be collected, intervals, and WebServer info
configFile = '' 
### web server URL to post the OS stats data, per environment
webServerURL = ''
### how often to post the data to Web Server
dataPostIntervalInSec = 0
### how long to collect the data once the process is started
dataCollectDurationInSec = 0
### debug level 0, none, 1 to 3, 3 highest info
debugLevel = 0
### log file name to log debug messages
JAOSStatsLogFileName =  None 

# path name to search for sysstat or sar files on Linux hosts
JASysStatFilePathName  = None

### used to post the data with host identifier, not used for grafana
###  stored in stats file on web server for other processing
componentName = ''
platformName = ''
siteName = ''
### file system names whose usage level is to be collected
JAOSStatsFileSystemName = None

### take current timestamp
JAOSStatsStartTime = datetime.datetime.now()

### these are used to get sar data using -s and -e options
JAFromTimeString = None
JAToTimeString =  None
### used to derive the sar data file name based on today's date
JADayOfMonth = None

### cache file name
JAGatherOSStatsCache = "JAGatherOSStats.cache"

### keys DBType, influxdbBucket, influxdbOrg
###    default DBType is Prometheus
DBDetails = {}
DBDetails['DBType'] = "Prometheus"
retryDurationInHours = 48
retryOSStatsBatchSize = 100 

### YYYYMMDD will be appended to this name to make daily file where retry stats are kept
retryOSStatsFileNamePartial = "JARetryOSStats."
### this file handle points to current retry log stats file. If not None, it points to position in file at which new data is to be written
retryOSStatsFileHandleCurrent = None

## parse arguments passed from command line
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-D", type=int, help="debug level 0 - None, 1,2,3-highest level")
parser.add_argument("-c", help="yaml file containing stats to be collected, default - JAGatherOSStats.yml")
parser.add_argument("-U", help="web server URL to post the data, default - get it from configFile")
parser.add_argument("-i", type=int, help="data post interval, default - get it from configFile")
parser.add_argument("-d", type=int, help="data collection duration, default - get it from configFile")
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
    JAOSStatsLogFileName = args.l

if debugLevel > 0 :
    print('DEBUG-1 Parameters passed configFile:{0}, webServerURL:{1}, dataPostIntervalInSec:{2}, debugLevel:{3}, componentName:{4}, plaformName:{5}, siteName: {6}, environment: {7}\n'.format(configFile, webServerURL, dataPostIntervalInSec, debugLevel, componentName, platformName, siteName, environment))

def JASignalHandler(sig, frame):
    JAOSStatsExit("Control-C pressed")

signal.signal(signal.SIGINT, JASignalHandler)


def JAOSStatsExit(reason):
    print(reason)
    JAOSStatsEndTime = datetime.datetime.now()
    JAOSStatsDuration = JAOSStatsEndTime - JAOSStatsStartTime
    JAOSStatsDurationInSec = JAOSStatsDuration.total_seconds()
    JAGlobalLib.LogMsg('{0}, processing duration:{1} sec\n'.format(reason,JAOSStatsDurationInSec ), JAOSStatsLogFileName, True)
    ### write prev start time of 0 so that next time process will run
    JAGlobalLib.JAWriteTimeStamp("JAGatherOSStats.PrevStartTime", 0)
    sys.exit()


### OS stats spec dictionary
### contains keys like cpu_times, cpu_percent, virtual_memory etc that match to the 
###   psutil.<functionName>
### values are like {Fields: user, system, idle, iowait} 
###    CSV field names match to the field names referred in psutil.

JAOSStatsSpec = {}

### CPU usage history
prevStatsSample = [None] * 12
prevStatsSampleTime = 0
prevStats = None
prevCPUPercentage = "used=0"
prevNetworkStats = defaultdict(dict)
prevDiskIOStats = [0] * 10

### get current hostname
import platform
thisHostName = platform.node()
### if long name with name.domain, make it short
hostNameParts = thisHostName.split('.')
thisHostName = hostNameParts[0]

### get OSType, OSName, and OSVersion. These are used to execute different python
###  functions based on compatibility to the environment
OSType, OSName, OSVersion = JAGlobalLib.JAGetOSInfo( sys.version_info, debugLevel)

errorMsg  = "JAGatherOSStats.py Version:{0}, OSType: {1}, OSName: {2}, OSVersion: {3}".format(JAVersion, OSType, OSName, OSVersion)
print(errorMsg)
JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

### use default config file, expect this file in home directory where this script is placed
if configFile == '':
    ### depending on OSType, use different default config file if present
    configFile = "JAGatherOSStats" + OSType + ".yml"
    if os.path.exists( configFile) != True:
        ### use a file name without OSType
        configFile = "JAGatherOSStats.yml"

### show warnings by default, used while posting data to Web Server
disableWarnings = None
### verify server certificate by default, used while posting data to Web Server
verifyCertificate = None

def JAGatherEnvironmentSpecs( key, values ):
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
            global webServerURL, disableWarnings, verifyCertificate

    """

    ### declare global variables
    global dataPostIntervalInSec, dataCollectDurationInSec
    global webServerURL, disableWarnings, verifyCertificate
    global DBDetails, retryDurationInHours, retryOSStatsBatchSize
    global debugLevel

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
            if webServerURL == None or webServerURL == '':
                if myValue != None:
                    webServerURL = myValue
                elif key == 'All':
                    JAOSStatsExit( 'ERROR mandatory param WebServerURL not available')
        
        elif myKey == 'DisableWarnings':
           if disableWarnings == None:
               if myValue != None:
                   if myValue == 'False' or myValue == False :
                       disableWarnings = False
                   elif myValue == 'True' or myValue == True :
                       disableWarnings = True
                   else:
                       disableWarnings = myValue
               elif key == 'All':
                   disableWarnings = True

        elif myKey == 'VerifyCertificate':
            if verifyCertificate == None:
                if myValue != None:
                    if myValue == 'False' or myValue == False:
                        verifyCertificate = False
                    elif myValue == 'True' or myValue == True:
                        verifyCertificate = True
                    else:
                        verifyCertificate = myValue

                elif key == 'All':
                    verifyCertificate = True
        elif myKey == 'DebugLevel':
            if debugLevel == 0:
                if myValue != None:
                    debugLevel = int(myValue)

        elif myKey == 'RetryDurationInHours':
            if retryDurationInHours == None:
                if myValue != None:
                    retryDurationInHours = int(myValue)

        elif myKey == 'RetryOSStatsBatchSize':
            if myValue != None:
                retryOSStatsBatchSize = int(myValue)

        elif myKey == 'DBDetails':
            if myValue != None:
                tempDBDetailsArray = myValue.split(',')
                if len(tempDBDetailsArray) == 0 :
                    errorMsg = "ERROR JAGatherEnvironmentSpecs() invalid format in DBDetails spec:|{1}|, expected format:DBType=influxdb,influxdbBucket=bucket,influxdbOrg=org".format(keyValuePair, myValue)
                    print(errorMsg)
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

                for keyValuePair in tempDBDetailsArray:
                    fieldArray = keyValuePair.split('=')
                    if len(fieldArray) > 0:
                        DBDetails[fieldArray[0]] = fieldArray[1]
                    else:
                        errorMsg = "ERROR JAGatherEnvironmentSpecs() invalid format in DB spec:|{0}|, DBDetails:|{1}|".format(keyValuePair, myValue)
                        print(errorMsg)
                        JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)



    if debugLevel > 1 :
        print('DEBUG-2 JAGatherEnvironmentSpecs(), DataPostIntervalInSec:{0}, DataCollectDurationInSec: {1}, DisableWarnings: {2}, verifyCertificate: {3}, WebServerURL: {4}'.format( dataPostIntervalInSec, dataCollectDurationInSec, disableWarnings, verifyCertificate, webServerURL))

### Now post the data to web server
import json
headers= {'Content-type': 'application/json', 
        'Accept': 'text/plain', 
        'Connection': "keep-alive",
        'Keep-Alive': "timeout=60" } 


def JAPostDataToWebServer(tempOSStatsToPost, useRequests, storeUponFailure):
    global requestSession
    """
    Post data to web server
    Returns True up on success, False upon failure
    """
    global webServerURL, verifyCertificate, debugLevel, headers, retryOSStatsFileHandleCurrent, fileNameRetryStatsPost
    OSStatsPostSuccess = True

    data = json.dumps(tempOSStatsToPost)
    if debugLevel > 1:
        print('DEBUG-2 JAPostDataToWebServer() tempOSStatsToPost: {0}'.format(tempOSStatsToPost))
    if debugLevel > 0:
        print('DEBUG-1 JAPostDataToWebServer() size of tempOSStatsToPost: {0}'.format(sys.getsizeof(tempOSStatsToPost)))
    if useRequests == True:
        try:
            # post interval elapsed, post the data to web server
            returnResult = requestSession.post(
                webServerURL, data, verify=verifyCertificate, headers=headers, timeout=(dataCollectDurationInSec/2))
            resultText = returnResult.text
        except requestSession.exceptions.RequestException as err:
            resultText = "<Response [500]> requestSession.post() Error posting data to web server {0}, exception raised","error:{1}".format(webServerURL, err)
            OSStatsPostSuccess = False
    else:
        try:
            result = subprocess.run(['curl', '-k', '-X', 'POST', webServerURL, '-H', "Accept: text/plain", '-H',
                                    "Content-Type: application/json", '-d', data], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            resultText = result.stdout.decode('utf-8').split('\n')
        except Exception as err:
            resultText = "<Response [500]> subprocess.run(curl) Error posting data to web server {0}, exception raised, error:{1}".format(webServerURL, err)
            OSStatsPostSuccess = False

    resultLength = len(resultText)
    if resultLength > 1 :
        try:            
            statusLine = str(resultText[-80:])
            if re.search(r'\[2\d\d\]', statusLine) == None :
                if re.search(r'\[4\d\d\]|\[5\d\d\]', statusLine) != None:
                    OSStatsPostSuccess = False 
            else:   
                matches = re.findall(r'<Response \[2\d\d\]>', str(resultText), re.MULTILINE)
                if len(matches) == 0:
                    OSStatsPostSuccess = False
        except :
            OSStatsPostSuccess = False
    else:
        OSStatsPostSuccess = False

    
    if OSStatsPostSuccess == False:
        print(resultText)
        if resultLength > 1 :
            JAGlobalLib.LogMsg(resultText[resultLength-1], JAOSStatsLogFileName, True)
        if retryOSStatsFileHandleCurrent != None and storeUponFailure == True:
            if retryOSStatsFileHandleCurrent == None :
                try:
                    retryOSStatsFileHandleCurrent = open( fileNameRetryStatsPost,"a")
                except OSError as err:
                    errorMsg = 'ERROR - Can not open file:{0}, OS error: {1}'.format(fileNameRetryStatsPost, err)
                    print(errorMsg)
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

            if retryOSStatsFileHandleCurrent != None :
                try:
                    ### if DBType is influxdb and retryStatsFileHandle is not None, store current data to be sent later
                    retryOSStatsFileHandleCurrent.write( data + '\n')
                except OSError as err:
                    errorMsg = "ERROR JAPostDataToWebServer() could not append data to retryStatsFile, error:{0}".format(err)
                    print(errorMsg)
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

                except Exception as err:
                    errorMsg = "ERROR Unknwon error:{0}".format( err )
                    print(errorMsg)
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
        else:
            print("ERROR JAPostDataToWebServer() posting data:{0}\n".format(tempOSStatsToPost))
    else:
        print("INFO JAPostDataToWebServer() posted data to web server successfully")
    return OSStatsPostSuccess

def JARetryOSStatsPost(currentTime):
    """
    This function tries to send the retryOSStats to web server
    """
    global useRequests, debugLevel, retryOSStatsBatchSize, retryDurationInHours, retryOSStatsFileNamePartial

    ### find history files with updated time within retryDurationInHours
    ###   returned files in sorted order, oldest file fist
    retryOSStatsFileNames = JAGlobalLib.JAFindModifiedFiles(
        retryOSStatsFileNamePartial + "*", (currentTime - retryDurationInHours * 3600), debugLevel, thisHostName)

    returnStatus = True
    for retryOSStatsFileName in retryOSStatsFileNames :
        if debugLevel > 0:
            print("DEBUG-1 JARetryOSStatsPost() processing retry log stats file:|{0}".format(retryOSStatsFileName))
        try:
            numberOfRecordsSent = 0
            ### read each line from a file and send to web server
            retryFileHandle = open ( retryOSStatsFileName, "r")
            while returnStatus == True:
                tempLine = retryFileHandle.readline()
                if not tempLine:
                    break
                ### Need to pass dictionary type object to JAPostDataToWebServer()
                returnStatus = JAPostDataToWebServer(json.loads(tempLine), useRequests, False)
                if returnStatus == True:
                    numberOfRecordsSent += 1

            retryFileHandle.close()

            if returnStatus == True:
                if numberOfRecordsSent > 0:
                    ### delete the file
                    os.remove( retryOSStatsFileName)
                    errorMsg = "INFO JARetryOSStatsPost() retry passed for OSStats file:{0}, numberOfRecordsSent:|{1}|, deleted this file".format(retryOSStatsFileName, numberOfRecordsSent)
                else:
                    errorMsg = "INFO No record to send in file:{0}".format(retryOSStatsFileName)
            else:
                errorMsg = 'WARN JARetryOSStatsPost() retry failed for OSStats file:{0}'.format(retryOSStatsFileName)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

        except IOError as err:
            errorMsg = "INFO file in open state already, skipping file: {0}".format(retryOSStatsFileName)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

        except OSError as err:
            errorMsg = "ERROR JARetryOSStatsPost() not able to read the file:|{0}, error:{1}".format(retryOSStatsFileName, err)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

if sys.version_info >= (3,3):
    import importlib
    try:
        from importlib import util
        util.find_spec("yaml")
        yamlModulePresent = True
    except ImportError:
        yamlModulePresent = False

    try:
        from importlib import util
        if util.find_spec("psutil") != None:
            psutilModulePresent = True
            import psutil
        else:
            psutilModulePresent = False
    except ImportError:
        psutilModulePresent = False

else:
    yamlModulePresent = False
    psutilModulePresent = False


## read default parameters and OS Stats collection spec
try:
    with open(configFile, "r") as file:

        ### use limited yaml reader when yaml is not available
        if yamlModulePresent == True:
            try:
                import yaml
                JAOSStats = yaml.load(file, Loader=yaml.FullLoader)
                file.close()
            except:
                JAOSStats = JAGlobalLib.JAYamlLoad( configFile )
        else:
            JAOSStats = JAGlobalLib.JAYamlLoad( configFile )
        if debugLevel > 1 :
            print('DEBUG-2 Content of config file: {0}, read to JAStats: {1}'.format(configFile, JAOSStats))


        if JAOSStatsLogFileName == None:
            if JAOSStats['LogFileName'] != None:
                JAOSStatsLogFileName = JAOSStats['LogFileName']
            else:
                JAOSStatsLogFileName = 'JAGatherOSStats.log'

        if JASysStatFilePathName == None:
            if JAOSStats['SysStatPathName'] != None:
                JASysStatFilePathName = '{0}'.format(JAOSStats['SysStatPathName'])
                ### replace any space
                JASysStatFilePathName = re.sub('\s','', JASysStatFilePathName)

                if JASysStatFilePathName != '':
                    ### if path does not end with '/', add it.
                    if JASysStatFilePathName.endswith('/') != True :
                        JASysStatFilePathName = JASysStatFilePathName + '/'

            if JASysStatFilePathName == None or JASysStatFilePathName == '': 
                ### for redhat linux and ubuntu, use default path for sar
                if OSType == 'Linux' :
                    if OSName == 'rhel' :
                        JASysStatFilePathName = '/var/log/sa/'
                    elif OSName == 'ubuntu' :
                        JASysStatFilePathName = '/var/log/sysstat/'

            ### if the directory or path does not exist, make the name empty
            if os.path.exists( JASysStatFilePathName) == False:
                JASysStatFilePathName = None

        for key, value in JAOSStats['Environment'].items():
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

        for key, value in JAOSStats['OSStats'].items():
            if value.get('Name') != None:
                statType = value.get('Name')

            if value.get( 'Fields' ) != None:
                fields =  value.get( 'Fields')

            fsNames = ''
            if statType == 'filesystem' :
                if value.get('FileSystemNames') != None:
                    ### file system names will be in CSV format
                    fsNames = value.get('FileSystemNames')
            elif statType == 'process' :
                if value.get('ProcessNames') != None:
                    ### process names will be in CSV format
                    fsNames = value.get('ProcessNames')

            JAOSStatsSpec[statType] = [ fields, fsNames ]

            if debugLevel > 1:
                print('DEBUG-2 key: {0}, OSStatType: {1}, fields: {2}, fsNames: {3}'.format(key, statType, fields, fsNames ) )

except OSError as err:
    JAOSStatsExit('ERROR - Can not open configFile:|{0}|, OS error: {1}\n'.format(configFile,err)) 

print('INFO  - Parameters after reading configFile:{0}, webServerURL:{1}, dataPostIntervalInSec:{2}, dataCollectDurationInSec:{3}, sysstatPathName: {4}, debugLevel: {5}\n'.format(configFile, webServerURL, dataPostIntervalInSec, dataCollectDurationInSec, JASysStatFilePathName, debugLevel))
if debugLevel > 0:
    for key, spec in JAOSStatsSpec.items():
        fields = spec[0] 
        fsNames = spec[1] 
        print('DEBUG-1 Name: {0}, Fields: {1}, fsNames: {2}'.format(key, fields, fsNames))

import platform
### if another instance is running, exit
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


### get current time in seconds since 1970 jan 1
programStartTime = loopStartTimeInSec = time.time()
statsEndTimeInSec = loopStartTimeInSec + dataCollectDurationInSec

### wait for twice the data collection duration for any prev instance to complete
waitTime = dataCollectDurationInSec * 2
OSUptime = JAGlobalLib.JAGetUptime(OSType)

while waitTime > 0:
    ### read the last time this process was started, 
    ###   if the time elapsed is less than dataCollectDurationInSec, 
    ###   prev instance is still running, get out
    prevStartTime = JAGlobalLib.JAReadTimeStamp( "JAGatherOSStats.PrevStartTime")
    if prevStartTime > 0:
        currentTime = time.time()
        if ( prevStartTime +  dataCollectDurationInSec) > currentTime:
            ### if host just started, the PrevStartTime file can have recent time, but, process will not be running
            ### if uptime is less than data collection duration, continue processing
            if OSUptime > 0 and OSUptime < dataCollectDurationInSec:
                break
            errorMsg = "INFO - Another instance of this program still running, sleeping for 10 seconds"
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
            ### sleep for 10 seconds, decrement waitTime by 10 seconds
            time.sleep(10)
            waitTime -= 10
        else:
            break
    else:
        break
    
if waitTime <= 0:
    JAOSStatsExit('ERROR - another instance of this program is running, exceeded max wait time:{0}, exiting'.format(dataCollectDurationInSec * 2))

### Create a file with current time stamp
JAGlobalLib.JAWriteTimeStamp("JAGatherOSStats.PrevStartTime")

if retryDurationInHours == None:
    retryDurationInHours = 0

### if retryDurationInHours is not zero, open file in append mode to append failed postings
if retryDurationInHours > 0:
    fileNameRetryStatsPost = retryOSStatsFileNamePartial + JAGlobalLib.UTCDateForFileName()
    retryOSStatsFileHandleCurrent = None
    
### delete old log files
if OSType == 'Windows':
    ### TBD expand this later 
    logFilesToDelete = None

else:
    tempFileNameToDelete = '{0}*'.format(JAOSStatsLogFileName)
    result =  subprocess.run(['find', '-name', tempFileNameToDelete, '-mtime', '+7'],stdout=subprocess.PIPE,stderr=subprocess.PIPE) 
    logFilesToDelete = result.stdout.decode('utf-8').split('\n')

if logFilesToDelete != None:
    for deleteFileName in logFilesToDelete:
        if deleteFileName != '':
            os.remove( deleteFileName)


returnResult = ''
OSStatsToPost = {}

### data to be posted to the web server
### pass fileName containing thisHostName and current dateTime in YYYYMMDD form
OSStatsToPost['fileName'] = thisHostName + ".OSStats." + JAGlobalLib.UTCDateForFileName()  
OSStatsToPost['jobName' ] = 'OSStats'
OSStatsToPost['hostName'] = thisHostName
OSStatsToPost['debugLevel'] = debugLevel
OSStatsToPost['componentName'] = componentName 
OSStatsToPost['platformName'] = platformName
OSStatsToPost['siteName'] = siteName 
OSStatsToPost['environment'] = environment

if DBDetails['DBType'] == 'Influxdb' :
    OSStatsToPost['DBType'] = 'Influxdb'
    OSStatsToPost['InfluxdbBucket'] = DBDetails['InfluxdbBucket']
    OSStatsToPost['InfluxdbOrg'] = DBDetails['InfluxdbOrg']
    storeUponFailure = True
else:
    storeUponFailure = False

### process retryOSStats files if present with time stamp within retryDurationInHours
if retryDurationInHours > 0 :
    skipRetry = False 
    ### read the last time this process was started, 
    ###   if the time elapsed is less than 24 times dataCollectDurationInSec, 
    ###   prev instance is still running, get out
    prevStartTime = JAGlobalLib.JAReadTimeStamp( "JAGatherOSStats.RetryStartTime")
    if prevStartTime > 0:
        currentTime = time.time()
        if ( prevStartTime + 24 * dataCollectDurationInSec) > currentTime:
            errorMsg = 'INFO - Previous retry operation still in progress'
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
            skipRetry = True

    if skipRetry == False:
        ### Create a file with current time stamp
        JAGlobalLib.JAWriteTimeStamp("JAGatherOSStats.RetryStartTime")
        if OSType == 'Windows':
            errorMsg = "ERROR RetryDurationInHours is not suppported on Windows, history data not sent to webserver automatically"
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
            JAGlobalLib.JAWriteTimeStamp("JAGatherOSStats.RetryStartTime", 0)
        else:
            procId = os.fork()
            if procId == 0:
                ### child process
                JARetryOSStatsPost(programStartTime)
                JAGlobalLib.JAWriteTimeStamp("JAGatherOSStats.RetryStartTime", 0)
                errorMsg = "INFO Retry operation completed"
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
                sys.exit(0)



def JAGetProcessStats( processNames, fields ):
    """
    Get OS uptime and record it as OS_Uptime in number of hours

    This function gets CPU, MEM, VSZ, RSS, etime used by processes 
    Fields supported are
        CPU, MEM, VSZ, RSS as given by ps aux command
        etime - process elapsed in number of days
    Returns stats in the form
        process_Name_field=fieldValue,process_Name_field=fieldValue,...

    On Windows, 
        Use psutil.process_iter() to get a list of processes, 
        For process whose name match to the process name passed,
          Get cpu_percent, memory_percent, memory_info attributes
          Prepare stats in the form  processName1_<field1>=<value1>,processName1_<field2>=<value2>,...
    On Linux,
        Use 'ps -aux' to get CPU, MEMORY, VSZ, RSS used by processes.
        For process whose name match to the process name passed,
          Parse line, extract CPU, MEM, VSZ, RSS values
          Replace '-', '.', ' ' with '' in process name to meet variable name format accepted by prometheus/influxdb/grafana
          Prepare stats in the form  processName1_<field1>=<value1>,processName1_<field2>=<value2>,...
           
    Return values in CSV format processName1_<field1>=<value1>,processName1_<field2>=<value2>,...
      or empty string up on error

    """
    global psutilModulePresent
    errorMsg = myStats = comma = ''
    global configFile
    if processNames == None:
        print('ERROR JAGetProcessStats() NO process name passed')
        return None


    ### separate field names
    fieldNames = re.split(',', fields)

    ### if in CSV format, separate the process names 
    tempProcessNames = processNames.split(',')

    # contains current process stats in name=value list
    # key - processNameField, value = fieldValue
    procStats = {}

    if OSType == 'Windows':
       # import wmi        
        procStats['OS_uptime'] = "{0:1.2f}".format(float(time.time() - psutil.boot_time()) /  (24 * 3600))
 
        if psutilModulePresent == True :
            for proc in psutil.process_iter():
                try:
                    # Get process name & pid from process object.
                    processName = proc.name()
                    processName = processName.replace(".exe","",1)
                    if processName in tempProcessNames:
                        pInfoDict = proc.as_dict(attrs=[ 'cpu_percent','memory_percent', 'memory_info'])
                        dummy = pInfoDict['memory_info']
                        # print("VSZ:{0} RSS:{1}".format(dummy.rss, dummy.vms))
                        # print( pInfoDict)

                        ### collect data if the field name is enabled for collection
                        for field in fieldNames:
                            if field == 'CPU':
                                fieldValue = pInfoDict['cpu_percent']
                            elif field == 'MEM':
                                fieldValue = pInfoDict['memory_percent']
                            elif field == 'VSZ' :
                                fieldValue = dummy.vms
                            elif field == 'RSS' :
                                fieldValue = dummy.rss
                            #elif field == 'etime':
                            #    fieldValue = 0
                            else:
                                errorMsg = 'ERROR JAGetProcessStats() Unsupported field name:{0}, check Fields definition in Process section of config file:{1}\n'.format(field, configFile)
                                print( errorMsg )
                                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
                                continue

                            procNameField = '{0}_{1}'.format(processName,field)
                            if procNameField not in procStats:
                                procStats[procNameField] = float(fieldValue)
                            else:
                                ### sum the values if current processNameField is already present
                                procStats[procNameField] += float(fieldValue)

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    errorMsg = 'ERROR JAGetProcessStats() Unsupported field name:{0}, check Fields definition in Process section of config file:{1}\n'.format(field, configFile)
                    print( errorMsg )
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
                    continue
                    
        else:
            errorMsg = "ERROR JAGetProcessStats() install psutil module to use this feature"

    else:
        try:
            ### first parameter of /proc/uptime is number of seconds since OS start
            with open("/proc/uptime") as procfile:
                uptimeInSec, dummy  = procfile.readline().split()

                ### convert seconds to days.
                procStats['OS_uptime'] = "{0:1.2f}".format( float(uptimeInSec) / (24 * 3600) )
                if debugLevel > 0:
                    print("DEBUG-1 JAGetProcessStats() OS_uptime: {0} days".format(procStats['OS_uptime']))
                procfile.close()

        except OSError as err:
            errorMsg = "ERROR JAGetProcessStats() OSError:{0}, not able to derive OSUptime from /proc/uptime".format(err)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
            procStats['OS_uptime'] = None

        ### get process stats for all processes
        # result = subprocess.run( ['ps', 'aux'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = subprocess.run( ['ps', '-eo', '%cpu,%mem,vsz,rss,etime,cmd'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        lines = result.stdout.decode('utf-8').split('\n')
        for line in lines:
            line = re.sub('\s+', ' ', line)
            if len(line) < 5:
                continue
            try:
                ### ps aux output line is of the form with 11 columns total
                ### USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
                # parent, pid, CPUPercent, MEMPercent, VSZ, RSS, TTY, STAT, START, TIME, COMMAND = line.split(' ', 10)

                # ps -eo %cpu,%mem,vsz,rss,etime,cmd output is of the form with 6 columns total
                # %CPU %MEM    VSZ   RSS     ELAPSED CMD
                # 0.0  0.0   1744  1076    21:30:57 /init
                CPUPercent, MEMPercent, VSZ, RSS, elapsedTime, COMMAND = line.split(' ', 5)
                tempCommand = '{0}'.format(COMMAND)

                for processName in tempProcessNames:
                    ### if current process name is at starting position of the command
                    ###   gather stats 
                    if re.match( processName, tempCommand) != None :

                        processNameParts = processName.split('/')
                        if processNameParts[-1] != None :
                            shortProcessName = processNameParts[-1]
                        else:
                            shortProcessName = processName
                        ### replace ., - with ''
                        shortProcessName = re.sub(r'[\.\-]', '', shortProcessName)
                        ### remove space from process name
                        shortProcessName = re.sub('\s+','',shortProcessName)

                        ### collect data if the field name is enabled for collection
                        for field in fieldNames:
                            if field == 'CPU':
                                fieldValue = CPUPercent
                            elif field == 'MEM':
                                fieldValue = MEMPercent
                            elif field == 'VSZ' :
                                fieldValue = VSZ
                            elif field == 'RSS' :
                                fieldValue = RSS
                            elif field == 'etime' :
                                if elapsedTime.find(":") >= 0 :
                                    if elapsedTime.find('-') >= 0 :
                                        ### convert [D+-][HH:]MM:SS to number of seconds
                                        tempNumberOfDays,tempHoursMinSec = elapsedTime.split('-')
                                    else:
                                        tempNumberOfDays = 0
                                        tempHoursMinSec = elapsedTime
                                tempTimeFields = tempHoursMinSec.split(':')
                                if len(tempTimeFields) > 2:
                                    ### elapsed time has HH:MM:SS portion
                                    elapsedTimeInHours = float(tempTimeFields[0]) + float(tempTimeFields[0])/60 + float(tempTimeFields)/3600
                                else:
                                    ### elapsed time has MM:SS portion only
                                    elapsedTimeInHours = float(tempTimeFields[0])/60 + float(tempTimeFields)/3600
                                fieldValue = tempNumberOfDays + elapsedTimeInHours/24
                                
                            else:
                                errorMsg = 'ERROR JAGetProcessStats() Unsupported field name:{0}, check Fields definition in Process section of config file:{1}\n'.format(field, configFile)
                                print( errorMsg )
                                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
                                continue

                            procNameField = '{0}_{1}'.format(shortProcessName,field)
                            if procNameField not in procStats:
                                procStats[procNameField] = float(fieldValue)
                            else:
                                ### sum the values if current processNameField is already present
                                procStats[procNameField] += float(fieldValue)

            except:
                ## ignore error
                if debugLevel > 0:
                    errorMsg = 'ERROR JAGetProcessStats() Not enough params in line:{0}\n'.format(line)
                    print( errorMsg )
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    ### now prepare procStats in single line in CSV format
    comma=''
    for procNameField, fieldValue in procStats.items():
        myStats = myStats + '{0}{1}={2}'.format(comma,procNameField, fieldValue)
        comma=','
    
    return myStats

def JAGetFileSystemUsage( fileSystemNames, fields, recursive=False ):
    """
    This function gets the file system usage
    Fields supported are
        percent_used - percent usage
        size_used - used space in GB, any space less than GB is xlated to GB

    Returns stats in the form
        fsName_fieldName=fieldValue,fsName_fieldName=fieldValue,...
        '/' is removed from file system name while printing above stats

    On Windows,
       Use shutil.disk_usage() to get disk usage data
       Replace ':' with '' for drive name
       Prepare variable names in the form <drive>_percent_used, <drive>_size_used (size in GB)

    On Linux,
        Use 'df- h' to get file system space info.
        For each file system name in the output
            If file system name match with desired file system name
               replace '/' with '' in file system name
               Prepare variable names in the form <fileSystemName>_percent_used, <fileSystemName>_size_used (size in GB)

    Return the values in CSV format <fileSystemName>_percent_used,<fileSystemName>_size_used,...
      or empty string upon error

    """
    errorMsg = myStats = comma = ''
    global configFile
    if fileSystemNames == None:
        print('ERROR JAGetFileSystemUsage() NO filesystem name passed')
        return myStats

    ### separate field names
    fieldNames = re.split(',', fields)

    ### if in CSV format, separate the file system names 
    tempFileSystemNames = fileSystemNames.split(',')

    if OSType == 'Windows':
        import shutil
        for fs in tempFileSystemNames:
            if os.path.isdir(  fs ) != True:
                ### diff hosts may have diff file systems, it is allowed to list file system spec to include
                ###  file system of all host types, even though each host does not have all file systems.
                ### this is NOT an error condition
                if debugLevel > 0:
                    print("WARN JAGetFileSystemUsage.py() drive {0} not present, can't gather stats for it".format(fs) )
                continue
            
            stats = shutil.disk_usage(fs)
            ### remove : from name so that this fs name can be sent as file system name to grafana
            fs = fs.strip(":")

            # print(stats)
            ### collect data if the field name is enabled for collection
            for field in fieldNames:

                if field == 'percent_used' :
                    if stats.total > 0:
                        percent = stats.used / stats.total
                    else:
                        percent = 0
                    ### print as integer, to  skip % value to be printed
                    myStats = myStats + '{0}{1}_{2}={3}'.format(comma,fs, field, percent ) 
                    comma = ','
                elif field == 'size_used' :
                    if stats.total > 0:
                        usedGB = stats.used / 1000000000
                    myStats = myStats + '{0}{1}_{2}={3}'.format(comma,fs, field, usedGB) 
                    comma = ','
                else:
                    errorMsg = 'ERROR JAGetFileSystemUsage() Unsupported field name:{0}, check Fields definition in FileSystem section of config file:{1}\n'.format(field, configFile)
                    print( errorMsg )
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)


    else:
      for fs in tempFileSystemNames:
        if os.path.isdir(  fs ) != True:
            ### diff hosts may have diff file systems, it is allowed to list file system spec to include
            ###  file system of all host types, even though each host does not have all file systems.
            ### this is NOT an error condition
            if debugLevel > 0:
                print("WARN JAGetFileSystemUsage.py() File System {0} not present, can't gather stats for it".format(fs) )
            continue

        result = subprocess.run( ['df', '-h', fs], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        lines = result.stdout.decode('utf-8').split('\n')
        for line in lines:
            line = re.sub('\s+', ' ', line)
            if len(line) < 5:
                continue
            try:
                ### get max 5 items 
                device, size, used, available, percent, mountpoint = line.split(' ', 5)
                if mountpoint == fs:

                    ### take out '/' from file system name
                    fsName = fs.replace('/','')

                    ### collect data if the field name is enabled for collection
                    for field in fieldNames:

                        if field == 'percent_used' :
                            percent = percent.replace('%','')
                            ### print as integer, to  skip % value to be printed
                            myStats = myStats + '{0}{1}_{2}={3}'.format(comma,fsName, field, percent ) 
                            comma = ','

                        elif field == 'size_used' :
                            if re.search( r'G$', used ) != None:
                                usedGB = used.replace('G','')
                            elif re.search( r'M$', used ) != None:
                                usedGB = int(used.replace('M','')) / 1000
                            elif re.search( r'K$', used ) != None:
                                usedGB = int(used.replace('K','')) / 1000000
                            else:
                                usedGB = used
                            myStats = myStats + '{0}{1}_{2}={3}'.format(comma,fsName, field, usedGB) 
                            comma = ','
                        else:
                            errorMsg = 'ERROR JAGetFileSystemUsage() Unsupported field name:{0}, check Fields definition in FileSystem section of config file:{1}\n'.format(field, configFile)
                            print( errorMsg )
                            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
            except:
                ## ignore error
                if debugLevel > 0:
                    errorMsg = 'ERROR JAGetFileSystemUsage() Not enough params in line:{0} for file system: {1}\n'.format(line, fs)
                    print( errorMsg )
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
    return myStats

def JAGetSocketStats(fields, recursive=False):
    """
    This function gets socket counts
      Sockets in established, and time_wait state can be counted separately
      Can also count all sockets, in all states

    Fields supported are
       total, established, time_wait

    On Windows and Linux,
        Use 'netstat -an' to get a list of sockets
        For the line starting with ^tcp|^tcp6|^udp|^udp6|^  TCP|^  UDP'
           If the line contains ESTABLISHED word, increment established count
           Else If the line contains TIME_WAIT word, increment timewait count
           Else if total is opted, increment total count
        Prepare the variables in the form established=<value>,time_wait=<value>,total=<value>

    Return data in CSV format established=<value>,time_wait=<value>,total=<value> 
       or empty string if can't be computed

    """
    myStats = comma = '' 
    ### separate field names
    fieldNames = re.split(',', fields)
   
    ### netstat -an works on unix, as well as in windows power shell
    ###   output columns are different
    ###  Since only ESTA, TIME_WAIT strings are searched, column order does not matter
    result = subprocess.run( ['netstat', '-an'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines = result.stdout.decode('utf-8').split('\n')
    
    socketEstablished = 0
    socketTimeWait = 0
    socketTotal = 0

    for line in lines:
        if re.match(r'^tcp|^tcp6|^udp|^udp6|^  TCP|^  UDP', line) == None:
            ### skip this line, not a TCP or UDP connection line
            continue
        if len(line) < 5:
            continue

        for field in fieldNames:
            if field == 'established':
                if re.search( 'ESTABLISHED', line) != None:
                    socketEstablished += 1
                    
            elif field == 'time_wait':
                if re.search ('TIME_WAIT', line) != None:
                    socketTimeWait += 1
                    
            elif field == 'total':
                socketTotal += 1

    for field in fieldNames:
        if field == 'established':
            myStats = myStats + '{0}{1}={2}'.format( comma, field, socketEstablished)
            comma = ','

        elif field == 'time_wait':
            myStats = myStats + '{0}{1}={2}'.format( comma, field, socketTimeWait)
            comma = ','

        if field == 'total' :
            myStats = myStats + '{0}{1}={2}'.format( comma, field, socketTotal)
            comma = ','
            
    return myStats


def JAGetCPUTimesPercent(fields, recursive=False):
    """
    This function gets CPU states in percentage
    Fields supported are
        user, system, idle, iowait

    If OSType is Linux,
        If SysStatPathName is defined, stats are derived using sar command
            This is to avoid additional overhead in collecting the stats
        Else stats are derived using /proc/stat file contents

    If OSType is Windows,
        use psutil, if present, to get data
        else, print error, return empty string

    return data in CSV format (name1=value1,name2=value2,..) 
       or empty string if can't be computed

    """
    global psutilModulePresent
    errorMsg = myStats = comma = ''
    global OSType, OSName, OSVersion, debugLevel, prevStatsSample, prevStats, prevStatsSampleTime, prevCPUPercentage
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            if debugLevel > 1:
                print("DEBUG-2 JAGetCPUTimesPercent() OSType:{0}, using 'sar -u' to get data".format(OSType))

            prevLine = tempHeadingFields = ''
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-u', '-i', str(dataPostIntervalInSec)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            lines = result.stdout.decode('utf-8').split('\n')
            ### lines of the form
            ###
            ### Linux 5.11.0-25-generic (havembha)      08/22/2021      _x86_64_        (8 CPU)
            ###
            ### 05:20:15 PM     CPU     %user     %nice   %system   %iowait    %steal     %idle
            ### 05:30:01 PM     all      0.12      0.00      0.06      0.11      0.00     99.71
            ### Average:        all      0.12      0.00      0.06      0.11      0.00     99.71
            if len( lines ) < 5:
                ### if sar does not have sample between the given start and end time, single line output will be present
                ### change the start time to -10 min and call this function again
                if recursive == True :
                    print("ERROR JAGetCPUTimesPercent() sar data NOT available, cmd:|sar -f {0}sa{1} -s {2} -e {3} -u".format( JASysStatFilePathName,JADayOfMonth,JAFromTimeString,JAToTimeString))
                    return myStats

                ### compute start time 10 times more than dataPostIntervalInSec
                ### expect to see sar data collected in this duration
                JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
                return JAGetCPUTimesPercent( fields, True )

            idleTime = iowaitTime = 0

            for line in lines:
                ### remove extra space
                line = re.sub('\s+', ' ', line)
                if len(line) < 5:
                    continue

                if debugLevel > 2:
                    print("DEBUG-3 JAGetCPUTimesPercent() sar output line: {0}".format(line))

                if re.search('%user', line) != None:
                    ### remove % sign from headings
                    line = re.sub('%', '', line)

                    ### heading line, separte the headings
                    tempHeadingFields = line.split(' ')
                    if debugLevel > 2:
                        print("DEBUG-3 JAGetCPUTimesPercent() sar output headings: {0}".format(tempHeadingFields))

                elif re.search('Average', line) != None:
                    ### Average line, parse prev line data
                    tempDataFields = prevLine.split(' ')

                    if debugLevel > 2:
                        print("DEBUG-3 JAGetCPUTimesPercent() sar output data fields: {0}".format(tempDataFields))

                    columnCount = 0
                    for field in tempDataFields :
                        if tempHeadingFields[ columnCount ] in fields:
                            ### this column data is opted, store the data
                            myStats = myStats + '{0}{1}={2}'.format( comma, tempHeadingFields[ columnCount ], field)
                            comma = ','
                                                        
                        ### total CPU usage is to be returned
                        ### compute this as  100 - idle
                        if tempHeadingFields[ columnCount ] == 'idle' :
                            idleTime = float(tempDataFields[columnCount])
                        elif tempHeadingFields[ columnCount ] == 'iowait' :
                            iowaitTime = float(tempDataFields[columnCount])

                        columnCount += 1

                    if 'used' in fields:
                        myStats = myStats + "{0}used={1:f}".format( comma, 100 - (idleTime+iowaitTime))
                        comma = ','
                        if debugLevel > 2:
                            print("DEBUG-3 JAGetCPUTimesPercent() idleTime:{0}, iowaitTime:{1}".format(idleTime, iowaitTime))

                else:
                    prevLine = line

        else:
            if debugLevel > 1:
                print("DEBUG-2 JAGetCPUTimesPercent() OSType:{0}, using /proc/stat to get data for fields:{1}".format(OSType, fields))

            try:
                # Read first line from /proc/stat. It should start with "cpu"
                # and contains times spent in various modes by all CPU's totalled.
                #
                with open("/proc/stat") as procfile:
                    cpustats = procfile.readline().split()

                    # ensure first line has cpu info
                    if cpustats[0] == 'cpu':
                        if prevStatsSample[1] != None:
                            currentTime = time.time()
                            if currentTime - prevStatsSampleTime < 5:
                                if 'used' in fields:
                                    return prevCPUPercentage
                                elif prevStats != None:
                                    ### use stats stored last time
                                    return prevStats
                                   
                            ### else continue processing
                            prevStatsSampleTime = currentTime
                            #
                            # Refer to "man 5 proc" (search for /proc/stat) for information
                            # about which field means what.
                            #
                            # Here we do calculation as simple as possible:
                            # CPU% = 100 * time_doing_things / (time_doing_things + time_doing_nothing)
                            #
                            user_time = float(cpustats[1]) - prevStatsSample[1]  +  float(cpustats[2]) - prevStatsSample[2]     
                            system_time = float(cpustats[3]) - prevStatsSample[3]

                            idle_time = float(cpustats[4]) - prevStatsSample[4]   
                            iowait_time = float(cpustats[5]) - prevStatsSample[5]   
                            cpustatsLen = len(cpustats) 
                            if cpustatsLen > 5:
                                irqTime = float(cpustats[6]) - prevStatsSample[6]
                                if cpustatsLen > 6:
                                    softirqTime = float(cpustats[7]) - prevStatsSample[7]
                                    if cpustatsLen > 7:
                                        stealTime =  float(cpustats[8]) - prevStatsSample[8] 
                                    else:
                                        stealTime = 0                                      
                                else:
                                    softirqTime = 0
                            else:
                                irqTime = 0

                            time_doing_things = user_time + system_time + irqTime + softirqTime + stealTime
                            time_doing_nothing = idle_time + iowait_time
                            total_time = time_doing_things + time_doing_nothing

                            if total_time > 0 :
                                # Calculate a percentage of change since last run:
                                #
                                cpu_percentage = 100.0 - ((100 * time_doing_nothing)/total_time )

                                comma = ''
                                if 'used' in fields:
                                    myStats = myStats +  "{0}used={1:f}".format(comma, cpu_percentage )
                                    comma = ','
                                    prevCPUPercentage = "used={0:f}".format(cpu_percentage )
                                else:
                                    if 'user' in fields:
                                        myStats = myStats + "{0}user={1:f}".format(comma, 100 *(user_time/total_time) )
                                        comma = ','
                                    if 'system' in fields:
                                        myStats = myStats + "{0}system={1:f}".format(comma, 100 * (system_time/total_time) )
                                        comma = ','
                                    if 'idle' in fields:
                                        myStats = myStats + "{0}idle={1:f}".format(comma, 100 * (idle_time/total_time) )
                                        comma = ','
                                    if 'iowait' in fields:
                                        myStats = myStats + "{0}iowait={1:f}".format(comma, 100 * (iowait_time/total_time) )
                                        comma = ','
                                    ### store for future
                                    prevStats = myStats

                        prevStatsSample[0] = cpustats[0]
                        count = 1
                        cpustatsLen = len(cpustats)
                        while count < cpustatsLen:
                            prevStatsSample[count] = float(cpustats[count])
                            count = count + 1
            except OSError as err:
                errorMsg = "ERROR JAGetCPUTimesPercent() OSError:{0}, fields:|{1}|,install psutils on this server to get OS stats".format(err, fields)
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
    
    elif OSType == 'Windows' :
        if psutilModulePresent == True :
            if 'used' in fields:
                ### psutil.cpu_present() returns value only, need to put it in field=value format
                myStats = "used={0:f}".format( psutil.cpu_percent() )
                if debugLevel > 1:
                    print("DEBUG-2 JAGetCPUTimesPercent() OSType:{0}, using psutil.cpu_percent() to get data".format(OSType))
            else:
                myStats = psutil.cpu_times_percent()
                if debugLevel > 1:
                    print("DEBUG-2 JAGetCPUTimesPercent() OSType:{0}, using psutil.cpu_times_percent() to get data".format(OSType))

        else:
            errorMsg = "ERROR JAGetCPUTimesPercent() fields:|{0}|, install psutils on this server to get OS stats".format( fields)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
    
    return myStats

def JAGetCPUPercent():
    """
    Get total CPU usage that includes all types of use. This is computed as 100 - idle time.

    """
    myFields = ['used']
    myStats = JAGetCPUTimesPercent( myFields )  

    return myStats

def JAGetVirtualMemory(fields, recursive=False):
    """
    This function gets virtual memory at the system level
    Fields supported depends on fields in sar output, or fields returned by psutil
    
    On Windows
        If psutil is present, use that to get data

    On Linux
        If sar file path is passed,
            Use 'sar -r' to get data
            Parse each line, extract the column values based on desired fields passed
            Prepare the return value in the form <field1>=<value1>,<field2>=<value2>,...
        Else If psutil is present, use that to get data
    
        Else, use /proc/meminfo to extract data
            Prepare the return value in the form <field1>=<value1>,<field2>=<value2>,...
           
    return data in CSV format (name1=value1,name2=value2,..) 
       or empty string if can't be computed

    """
    errorMsg = myStats = comma = ''
    global OSType, OSName, OSVersion, debugLevel
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            if debugLevel > 1:
                print("DEBUG-2 JAGetVirtualMemory() OSType:{0}, using 'sar -r' to get data".format(OSType))

            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-r', '-i', str(dataPostIntervalInSec)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            lines = result.stdout.decode('utf-8').split('\n')
            ### lines of the form
            ###
            ### Linux 5.11.0-25-generic (havembha)      08/22/2021      _x86_64_        (8 CPU)
            ###
            ### 07:40:15 PM kbmemfree   kbavail kbmemused  %memused kbbuffers  kbcached  kbcommit   %commit  kbactive   kbinact   kbdirty
            ### 07:50:04 PM   4552636   7017144    644284      8.00     84640   2484420   1824748     14.90   1065344   2042064       304
            ### Average:      4552636   7017144    644284      8.00     84640   2484420   1824748     14.90   1065344   2042064       304

            if len( lines ) < 5:
                ### if sar does not have sample between the given start and end time, single line output will be present
                ### change the start time to -10 min and call this function again
                if recursive == True :
                    print("ERROR JAGetVirtualMemory() sar data NOT available, cmd:|sar -f {0}sa{1} -s {2} -e {3} -r".format( JASysStatFilePathName,JADayOfMonth,JAFromTimeString,JAToTimeString))
                    return myStats

                ### compute start time 10 times more than dataPostIntervalInSec
                ### expect to see sar data collected in this duration
                JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
            
            for line in lines:
                ### remove extra space
                line = re.sub('\s+', ' ', line)
                if len(line) < 5:
                    continue

                if re.search('kbmemfree', line) != None:
                    ### remove % sign from headings
                    line = re.sub('%', '', line)

                    ### heading line, separte the headings
                    tempHeadingFields = line.split(' ')

                elif re.search('Average', line) != None:
                    ### Average line, parse prev line data
                    tempDataFields = prevLine.split(' ')

                    columnCount = 0
                    for field in tempDataFields :
                        if tempHeadingFields[ columnCount ] in fields:
                            ### this column data is opted, store the data
                            myStats = myStats + '{0}{1}={2}'.format( comma, tempHeadingFields[ columnCount ], field)
                            comma = ','
                        columnCount += 1
                else:
                    prevLine = line

        elif psutilModulePresent == True: 
            myStats = psutil.virtual_memory()
            if debugLevel > 1:
                print("DEBUG-2 JAGetVirtualMemory() OSType:{0}, using psutil.virtual_memory() to get data".format(OSType))
        else:
            if debugLevel > 1:
                print("DEBUG-2 JAGetVirtualMemory() OSType:{0}, using /proc/meminfo to get data".format(OSType))
            ###  get total, free, percent used using /proc/meminfo
            try:
                with open("/proc/meminfo") as procfile:
                    memTotal = None
                    memFree = None

                    while True:
                        tempLine = procfile.readline()
                        if not tempLine:
                            break
                        tempLine = re.sub(r'\s+', ' ', tempLine)
                        tempFields = tempLine.split(' ')
                            
                        if tempFields[0] == 'MemTotal:':
                            if 'total' in fields:
                                memTotal = value = int(tempFields[1])
                                myStats = myStats + '{0}total={1}'.format(comma, value)     
                                comma = ','
                        elif tempFields[0] == 'MemAvailable:':
                            if 'available' in fields:
                                value = int(tempFields[1])
                                myStats = myStats + '{0}available={1}'.format(comma, value)
                                comma = ','
                            if 'kbavail' in fields:
                                value = int(tempFields[1])
                                myStats = myStats + '{0}kbavail={1}'.format(comma, value)
                                comma = ','
                        elif tempFields[0] == 'MemFree:':
                            if 'kbmemfree' in fields:
                                value = int(tempFields[1])
                                myStats = myStats + '{0}kbmemfree={1}'.format(comma, value)
                                comma = ','
                                memFree = value  
                        elif tempFields[0] == 'Committed_AS:':
                            if 'commit' in fields:
                                value = int(tempFields[1])
                                myStats = myStats + '{0}commit={1}'.format(comma, value)
                                comma = ','

                    if 'memused' in fields:
                        if memTotal != None and memFree != None and memTotal > 0 :
                            myStats = myStats + '{0}memused={1}'.format(comma, (100*(memTotal - memFree))/memTotal )       

            except OSError as err:
                errorMsg = "ERROR JAGetSwapMemory() error reading/parsing contents of /proc/meminfo {0}".format(err)
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    elif OSType == 'Windows' :
        if psutilModulePresent == True: 
            myStats = psutil.virtual_memory()
            if debugLevel > 1:
                print("DEBUG-2 JAGetVirtualMemory() OSType:{0}, using psutil.virtual_memory() to get data".format(OSType))

        else:
            errorMsg = "ERROR JAGetVirtualMemory() fields:|{0}|, install psutils on this server to get OS stats".format(fields)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    return myStats

def JAGetSwapMemory(fields, recursive=False):
    """
    This function gets swap memory at the system level
    Fields supported depends on fields in sar output, or fields returned by psutil
    
    On Windows
        If psutil is present, use that to get data

    On Linux
        If sar file path is passed,
            Use 'sar -S' to get data
            Parse each line, extract the column values based on desired fields passed
            Prepare the return value in the form <field1>=<value1>,<field2>=<value2>,...
        Else If psutil is present, use that to get data
    
        Else, use /proc/meminfo to extract data
            Prepare the return value in the form <field1>=<value1>,<field2>=<value2>,...
           
    return data in CSV format <field1>=<value1>,<field2>=<value2>,... 
       or empty string if can't be computed

    """

    errorMsg = myStats = comma = ''
    global OSType, OSName, OSVersion, debugLevel
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            if debugLevel > 1:
                print("DEBUG-2 JAGetSwapMemory() OSType:{0}, using 'sar -S' to get data".format(OSType))
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-S', '-i', str(dataPostIntervalInSec)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            lines = result.stdout.decode('utf-8').split('\n')
            ### lines of the form
            ###
            ### Linux 5.11.0-25-generic (havembha)      08/22/2021      _x86_64_        (8 CPU)
            ###
            ### 07:40:15 PM kbswpfree kbswpused  %swpused  kbswpcad   %swpcad
            ### 07:50:04 PM   4194300         0      0.00         0      0.00
            ### Average:      4194300         0      0.00         0      0.00

            if len( lines ) < 5:
                ### if sar does not have sample between the given start and end time, single line output will be present
                ### change the start time to -10 min and call this function again
                if recursive == True :
                    print("ERROR JAGetSwapMemory() sar data NOT available, cmd:|sar -f {0}sa{1} -s {2} -e {3} -S".format( JASysStatFilePathName,JADayOfMonth,JAFromTimeString,JAToTimeString))
                    return myStats

                ### compute start time 10 times more than dataPostIntervalInSec
                ### expect to see sar data collected in this duration
                JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
            
            for line in lines:
                ### remove extra space
                line = re.sub('\s+', ' ', line)
                if len(line) < 5:
                    continue

                if re.search('kbswpfree', line) != None:
                    ### remove % sign from headings
                    line = re.sub('%', '', line)

                    ### heading line, separte the headings
                    tempHeadingFields = line.split(' ')

                elif re.search('Average', line) != None:
                    ### Average line, parse prev line data
                    tempDataFields = prevLine.split(' ')

                    columnCount = 0
                    for field in tempDataFields :
                        if tempHeadingFields[ columnCount ] in fields:
                            ### this column data is opted, store the data
                            myStats = myStats + '{0}{1}={2}'.format( comma, tempHeadingFields[ columnCount ], field)
                            comma = ','
                        columnCount += 1
                else:
                    prevLine = line
        
            if debugLevel > 1:
                    print("DEBUG-2 JAGetSwapMemory() OSType:{0}, using /proc/meminfo to get total and free data".format(OSType))

            ### now get total, free, percent used using /proc/meminfo
            try:
                with open("/proc/meminfo") as procfile:
                    swapTotal = None
                    swapFree = None

                    while True:
                        tempLine = procfile.readline()
                        if not tempLine:
                            break
                        tempLine = re.sub(r'\s+', ' ', tempLine)
                        tempFields = tempLine.split(' ')
                            
                        if tempFields[0] == 'SwapTotal:':
                            if 'total' in fields:
                                swapTotal = int(tempFields[1])
                                myStats = myStats + '{0}total={1}'.format(comma, swapTotal)     
                                comma = ','
                        elif tempFields[0] == 'SwapFree:':
                            if 'free' in fields:
                                swapFree = int(tempFields[1])
                                myStats = myStats + '{0}free={1}'.format(comma, swapFree)
                                comma = ','
                        if swapTotal != None and swapFree != None:
                            break

            except OSError:
                errorMsg = "ERROR JAGetSwapMemory() can't read /proc/meminfo"
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
        elif psutilModulePresent == True :
            myStats = psutil.swap_memory()
            if debugLevel > 1:
                    print("DEBUG-2 JAGetSwapMemory() OSType:{0}, using psutil.swap_memory() to get data".format(OSType))

        else:
            if debugLevel > 1:
                    print("DEBUG-2 JAGetSwapMemory() OSType:{0}, using /proc/meminfo to get total and free data".format(OSType))
            ### collect basic info
            ### now get total, free, percent used using /proc/meminfo
            try:
                with open("/proc/meminfo") as procfile:
                    swapTotal = None
                    swapFree = None

                    while True:
                        tempLine = procfile.readline()
                        if not tempLine:
                            break
                        tempLine = re.sub(r'\s+', ' ', tempLine)
                        tempFields = tempLine.split(' ')
                            
                        if tempFields[0] == 'SwapTotal:':
                            if 'total' in fields:
                                swapTotal = int(tempFields[1])
                                myStats = myStats + '{0}total={1}'.format(comma, swapTotal)     
                                comma = ','
                        elif tempFields[0] == 'SwapFree:':
                            if 'free' in fields:
                                swapFree = int(tempFields[1])
                                myStats = myStats + '{0}free={1}'.format(comma, swapFree)
                                comma = ','
                        if swapTotal != None and swapFree != None:
                            break

            except OSError as err:
                errorMsg = "ERROR JAGetSwapMemory() can't read /proc/meminfo, OSError:{0}".format(err)
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    elif OSType == 'Windows' :
        if psutilModulePresent == True :
            myStats = psutil.swap_memory()
        if debugLevel > 1:
                print("DEBUG-2 JAGetSwapMemory() OSType:{0}, using psutil.swap_memory() to get data".format(OSType))

    if myStats == '':
        errorMsg = "ERROR JAGetSwapMemory() fields:|{0}|, install psutils on this server to get OS stats".format(fields)
        print(errorMsg)
        JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    return myStats

def JAGetDiskIOCounters(fields, recursive=False):
    """
    This function gets disk IO values for all disks combined.
    The values returned are delta values from previous sample (not the total value from system start)
    Fields supported depends on fields in sar output, or fields returned by psutil
    
    On Windows
        If psutil is present, use that to get data
        When called first time, sample is stored as previous value
        When called subsequent time, previous sample value is subtracted from current value to derive delta value
        Prepared the returned values in the form <field1>=<value1>,<field2>=<value2>,...

    On Linux
        If sar file path is passed,
            Use 'sar -b' to get data. sar output is in delta format already.
            Parse each line, extract the column values based on desired fields passed
            Prepare the return value in the form <field1>=<value1>,<field2>=<value2>,...
        Else If psutil is present, use that to get data
            When called first time, sample is stored as previous value
            When called subsequent time, previous sample value is subtracted from current value to derive delta value
    
        Else, use 'vmstat -D' to extract data
            When called first time, sample is stored as previous value
            When called subsequent time, previous sample value is subtracted from current value to derive delta value
            Prepare the return value in the form <field1>=<value1>,<field2>=<value2>,...
           
    return data in CSV format <field1>=<value1>,<field2>=<value2>,... 
       or empty string if can't be computed
       
    """

    errorMsg = myStats = comma = ''
    global OSType, OSName, OSVersion, debugLevel, prevDiskIOStats
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-b', '-i', str(dataPostIntervalInSec)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            lines = result.stdout.decode('utf-8').split('\n')
            ### lines of the form
            ###
            ### Linux 5.11.0-25-generic (havembha)      08/22/2021      _x86_64_        (8 CPU)
            ###
            ### 07:40:15 PM       tps      rtps      wtps      dtps   bread/s   bwrtn/s   bdscd/s
            ### 07:50:04 PM      1.01      0.01      1.00      0.00      0.01     14.87      0.00
            ### Average:         1.01      0.01      1.00      0.00      0.01     14.87      0.00

            if len( lines ) < 5:
                ### if sar does not have sample between the given start and end time, single line output will be present
                ### change the start time to -10 min and call this function again
                if recursive == True :
                    print("ERROR JAGetDiskIOCounters() sar data NOT available, cmd:|sar -f {0}sa{1} -s {2} -e {3} -b".format( JASysStatFilePathName,JADayOfMonth,JAFromTimeString,JAToTimeString))
                    return myStats

                ### compute start time 10 times more than dataPostIntervalInSec
                ### expect to see sar data collected in this duration
                JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
            
            for line in lines:
                ### remove extra space
                line = re.sub('\s+', ' ', line)

                if len(line) < 5:
                    continue

                if re.search('rtps', line) != None:
                    ### remove % sign from headings
                    line = re.sub('%', '', line)

                    ### heading line, separte the headings
                    tempHeadingFields = line.split(' ')

                elif re.search('Average', line) != None:
                    ### Average line, parse prev line data
                    tempDataFields = prevLine.split(' ')

                    if debugLevel > 1:
                        print("DEBUG-2 JAGetDiskIOCounters(), used 'sar -b' to get data:{1}".format(OSType, prevLine))

                    columnCount = 0
                    for field in tempDataFields :
                        tempHeading = tempHeadingFields[ columnCount ] 
                        if tempHeading in fields:
                            ### replace / with _
                            tempHeading = re.sub(r'/', '', tempHeading)
                            ### this column data is opted, store the data
                            myStats = myStats + '{0}{1}={2}'.format( comma, tempHeading, field)
                            comma = ','
                        columnCount += 1
                else:
                    prevLine = line

        elif psutilModulePresent == True:
            tempStats = psutil.disk_io_counters()
            if debugLevel > 1:
                print("DEBUG-2 JAGetDiskIOCounters() OSType:{0}, used psutil.disk_io_counters() to get data:{1}".format(OSType, tempStats))
            havePrevData = prevDiskIOStats[0]
            count = 0
            tempStatsLen = len(tempStats)
            while count < tempStatsLen:
                fieldName = tempStats._fields[count]
                fieldValue = tempStats[count]
                if havePrevData > 0:
                    fieldValue = fieldValue - prevDiskIOStats[count]
                prevDiskIOStats[count] = tempStats[count]
                myStats = myStats + "{0}{1}={2}".format(comma,fieldName,fieldValue) 
                comma = ','
                count = count + 1
        else:
            if debugLevel > 1:
                print("DEBUG-2 JAGetDiskIOCounters() OSType:{0}, used 'vmstat -D' to get total and free data".format(OSType))

            try:
                ### run 'vmstat -D' to get disk stats
                result = subprocess.run( ['vmstat','-D'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                lines = result.stdout.decode('utf-8').split('\n')
                ### lines of the form
                """
                    27 disks
                        0 partitions
                    2232 total reads
                    3561 merged reads
                196006 read sectors
                    1064 milli reading
                    9563 writes
                    2010 merged writes
                8421616 written sectors
                    11293 milli writing
                        0 inprogress IO
                    25 milli spent IO
                """
                readCount = writeCount = 0

                if debugLevel > 1:
                    print("DEBUG-2 JAGetDiskIOCounters(), used 'vmstat -D' to get data:{0}".format(lines))

                for line in lines:
                    ### remove extra space
                    line = re.sub('\s+', ' ', line)
                    words = re.split(' ', line)

                    if len( words ) >= 2:
                        if words[2] == 'total' and words[3] == 'reads':
                            readCount = int(words[1])  
                        elif words[2] == 'writes':
                            writeCount = int(words[1])  

                ### if prev sample is present, compute delta
                ### read_count,write_count,read_bytes,write_bytes,tps,rtps,wtps
                if 'read_count' in fields:
                    myStats = myStats + "{0}read_count={1}".format(comma, readCount - prevDiskIOStats[0])
                    comma = ','
                if 'rtps' in fields:
                    myStats = myStats + "{0}rtps={1}".format(comma, (readCount - prevDiskIOStats[0])/dataPostIntervalInSec)
                    comma = ','
                prevDiskIOStats[0] = readCount
                if 'write_count' in fields:
                    myStats = myStats + "{0}write_count={1}".format(comma, writeCount - prevDiskIOStats[1])
                    comma = ','
                if 'wtps' in fields:
                    myStats = myStats + "{0}wtps={1}".format(comma, (writeCount - prevDiskIOStats[1])/dataPostIntervalInSec)
                    comma = ','

                prevDiskIOStats[1] = writeCount
                
            except OSError as err:                           
                errorMsg = "ERROR JAGetDiskIOCounters() OSError:{0}, fields:|{1}|, install psutils on this server to get OS stats".format(err, fields)
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
               
    elif OSType == 'Windows' :
        if psutilModulePresent == True:
            tempStats = psutil.disk_io_counters()
            if debugLevel > 1:
                print("DEBUG-2 JAGetDiskIOCounters() OSType:{0}, used psutil.disk_io_counters() to get data:{1}".format(OSType, tempStats))
            havePrevData = prevDiskIOStats[0]
            count = 0
            tempStatsLen = len(tempStats)
            while count < tempStatsLen:
                fieldName = tempStats._fields[count]
                fieldValue = tempStats[count]
                if havePrevData > 0:
                    fieldValue = fieldValue - prevDiskIOStats[count]
                prevDiskIOStats[count] = tempStats[count]
                myStats = myStats + "{0}{1}={2}".format(comma,fieldName,fieldValue) 
                comma = ','
                count = count + 1

        else:
            errorMsg = "ERROR JAGetDiskIOCounters() fields:|{0}|, install psutils on this server to get OS stats".format(fields)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    return myStats

def JAGetNetworkIOCounters(networkIOFields, recursive=False):
    """
    This function gets network IO values.
    The values returned are delta values from previous sample (not the total value from system start)
    Fields supported depends on fields in sar output, or fields returned by psutil
    
    On Windows 
        If psutil is present, use that to get data
        When called first time, sample is stored as previous value
        When called subsequent time, previous sample value is subtracted from current value to derive delta value
        Prepared the returned values in the form <field1>=<value1>,<field2>=<value2>,...
        Aggregate values for all interface combined

    On Linux
        If sar file path is passed,
            Use 'sar -b' to get data. sar output is in delta format already.
            Parse each line, extract the column values based on desired fields passed
            Prepare the return value in the form <interface>_<field1>=<value1>,<interface>_<field2>=<value2>,...
            Values per interface are returned
        Else If psutil is present, use that to get data
            When called first time, sample is stored as previous value
            When called subsequent time, previous sample value is subtracted from current value to derive delta value
            Aggregate values for all interface combined

        Else, use 'ifconfig -a' to extract data
            When called first time, sample is stored as previous value
            When called subsequent time, previous sample value is subtracted from current value to derive delta value
            Prepare the return value in the form <interface>_<field1>=<value1>,<interface>_<field2>=<value2>,...
            Values per interface are returned

    return data in CSV format <interface>_<field1>=<value1>,<interface>_<field2>=<value2>,... 
       or empty string if can't be computed
       
    """

    errorMsg = myStats = comma = ''
    global OSType, OSName, OSVersion, debugLevel
    global JAFromTimeString, JAToTimeString, JADayOfMonth
    errorMsg = ''

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            if debugLevel > 1:
                print("DEBUG-2 JAGetNetworkIOCounters() OSType:{0}, using 'sar -n DEV' to get data".format(OSType))

            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-n', 'DEV', '-i', str(dataPostIntervalInSec)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            lines = result.stdout.decode('utf-8').split('\n')
            ### lines of the form
            ###
            ### Linux 5.11.0-25-generic (havembha)      08/22/2021      _x86_64_        (8 CPU)
            ###
            ### 07:00:01 PM     IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil
            ### 07:10:01 PM        lo     29.85     29.85     34.08     34.08      0.00      0.00      0.00      0.00
            ### 07:10:01 PM    enp3s0      6.21      6.15      1.79      2.02      0.00      0.00      0.14      0.02
            ### 07:10:01 PM    wlp2s0      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
            ### ....
            ### Average:           lo      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
            ### Average:       enp3s0      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
            ### Average:       wlp2s0      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00

            if len( lines ) < 5:
                ### if sar does not have sample between the given start and end time, single line output will be present
                ### change the start time to -10 min and call this function again
                if recursive == True :
                    print("ERROR JAGetNetworkIOCounters() sar data NOT available, cmd:|sar -f {0}sa{1} -s {2} -e {3} -n DEV".format( JASysStatFilePathName,JADayOfMonth,JAFromTimeString,JAToTimeString))
                    return myStats

                ### compute start time 10 times more than dataPostIntervalInSec
                ### expect to see sar data collected in this duration
                JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )

            ### store prev lines using interface as key
            prevLines = defaultdict(dict)
            storeLines = False
            for line in lines:
                ### remove extra space
                line = re.sub('\s+', ' ', line)
                
                if len(line) < 5:
                    continue

                if re.search('IFACE', line) != None:
                    ### remove % sign from headings
                    line = re.sub('%', '', line)

                    ### heading line, separte the headings
                    tempHeadingFields = line.split(' ')
                    storeLines = True
                elif re.search('Average', line) != None:
                    ### Average line, parse prev line data for each interface
                    for iface, line in prevLines.items():
                        tempDataFields = line.split(' ')

                        if debugLevel > 1:
                            print("DEBUG-2 JAGetNetworkIOCounters() using interface line data:{0}".format(line))

                        columnCount = 0
                        for field in tempDataFields :
                            tempHeading = tempHeadingFields[ columnCount ]
                            if tempHeading in networkIOFields:
                                ### replace / with ''
                                tempHeading = re.sub(r'/', '', tempHeading)
                                ### this column data is opted, store the data in the form fieldName_iface=value
                                myStats = myStats + '{0}{1}_{2}={3}'.format( comma, tempHeading, iface, field)
                                comma = ','
                            columnCount += 1
                    break

                else:
                    if storeLines == True:
                        ### store data per interface
                        ### words[2] has interface name in each data line
                        ### 07:10:01 PM        lo     29.85     29.85     34.08     34.08      0.00      0.00      0.00      0.00
                        ###                  ^^^^ <-- key for prevLines
                        words = line.split(' ')
                        prevLines[ words[2] ] = line

        elif psutilModulePresent == True:
            tempStats = psutil.net_io_counters()
            if debugLevel > 1:
                print("DEBUG-2 JAGetNetworkIOCounters() OSType:{0}, used psutil.net_io_counters() to get data:{1}".format(OSType, tempStats))
            havePrevData = len(prevNetworkStats)
            count = 0
            tempStatsLen = len(tempStats)
            while count < tempStatsLen:
                fieldName = tempStats._fields[count]
                fieldValue = tempStats[count]
                if havePrevData > 0:
                    fieldValue = fieldValue - prevNetworkStats['all'][count]
                prevNetworkStats['all'][count]  = tempStats[count]
                myStats = myStats + "{0}{1}={2}".format(comma,fieldName,fieldValue) 
                comma = ','
                count = count + 1
        else:
            if debugLevel > 1:
                print("DEBUG-2 JAGetNetworkIOCounters() OSType:{0}, used 'ifconfig -a' to get data".format(OSType))
            
            try:
                ### run 'ifconfig -a' to get network stats
                result = subprocess.run( ['ifconfig','-a'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                lines = result.stdout.decode('utf-8').split('\n')
                ### lines of the form
                """
enp3s0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.1.221  netmask 255.255.255.0  broadcast 192.168.1.255
        inet6 fe80::f2de:f1ff:fe93:cbc2  prefixlen 64  scopeid 0x20<link>
        ether f0:de:f1:93:cb:c2  txqueuelen 1000  (Ethernet)
        RX packets 7728787  bytes 2574472711 (2.5 GB)
        RX errors 0  dropped 1468  overruns 0  frame 0
        TX packets 2513225  bytes 705897965 (705.8 MB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0
        inet6 ::1  prefixlen 128  scopeid 0x10<host>
        loop  txqueuelen 1000  (Local Loopback)
        RX packets 12838688  bytes 25578760128 (25.5 GB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 12838688  bytes 25578760128 (25.5 GB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

                """
                interface = ''
                ### process lines starting with RX and TX
                for line in lines:
                    ### remove extra space
                    line = re.sub('\s+', ' ', line)
                    fields = re.split(' ', line)

                    if len( fields ) >= 5 and interface != '':
                        if fields[1] == 'RX' and fields[2] == 'packets':
                            ### RX packets 12838688  bytes 25578760128 (25.5 GB)
                            ### 1       2         3      4   5
                            rxPackets = int(fields[3])
                            rxBytes = int(fields[5])
                            havePrevData = len(prevNetworkStats[interface])
                            if havePrevData > 0:
                                if 'packets_recv' in networkIOFields:
                                    myStats = myStats + "{0}packets_recv_{1}={2}".format(comma,interface, rxPackets - prevNetworkStats[interface][0])
                                    comma = ','
                                if 'bytes_recv' in networkIOFields:
                                    myStats = myStats + "{0}bytes_recv_{1}={2}".format(comma,interface, rxBytes - prevNetworkStats[interface][1])
                                    comma = ','
                            prevNetworkStats[interface][0] = rxPackets
                            prevNetworkStats[interface][1] = rxBytes

                        elif fields[1] == 'RX' and fields[2] == 'errors':
                            ### RX errors 0  dropped 0  overruns 0  frame 0
                            ### 0    1    2     3    4    5      6   7    8
                            rxErrors =  int(fields[3])
                            rxDropped =  int(fields[5]) 
                            rxOverrun =  int(fields[7])
                            rxFrame =   int(fields[9])

                            if havePrevData > 0:
                                if 'errin' in networkIOFields:
                                    myStats = myStats + "{0}errin_{1}={2}".format(comma,interface, rxErrors - prevNetworkStats[interface][2])
                                    comma = ','
                                if 'dropin' in networkIOFields:
                                    myStats = myStats + "{0}dropin_{1}={2}".format(comma,interface, rxDropped - prevNetworkStats[interface][3])
                                    comma = ','
                                if 'overrunin' in networkIOFields:
                                    myStats = myStats + "{0}overrunin_{1}={2}".format(comma,interface, rxOverrun - prevNetworkStats[interface][4])
                                    comma = ','
                                if 'framein' in networkIOFields:
                                    myStats = myStats + "{0}framein_{1}={2}".format(comma,interface, rxFrame - prevNetworkStats[interface][5])
                                    comma = ','

                            prevNetworkStats[interface][2] = rxErrors
                            prevNetworkStats[interface][3] = rxDropped
                            prevNetworkStats[interface][4] = rxOverrun
                            prevNetworkStats[interface][5] = rxFrame
                            
                        elif fields[1] == 'TX' and fields[2] == 'packets':
                            ### RX packets 12838688  bytes 25578760128 (25.5 GB)
                            ### 1       2         3      4  5
                            txPackets =  int(fields[3])
                            txBytes =  int(fields[5])
                            if havePrevData > 0:
                                if 'bytes_sent' in networkIOFields:
                                    myStats = myStats + "{0}bytes_sent_{1}={2}".format(comma,interface, txBytes - prevNetworkStats[interface][6])
                                    comma = ','
                                if 'packets_sent' in networkIOFields:
                                    myStats = myStats + "{0}packets_sent_{1}={2}".format(comma,interface, txPackets - prevNetworkStats[interface][7])
                                    comma = ','
                            prevNetworkStats[interface][6] = txBytes
                            prevNetworkStats[interface][7] = txPackets

                        elif fields[1] == 'TX' and fields[2] == 'errors':
                            ### RX errors 0  dropped 0  overruns 0  frame 0
                            ### 1    2     3    4    5      6   7    8    9
                            txErrors =  int(fields[3])
                            txDropped =  int(fields[5] )
                            txOverrun =  int(fields[7])
                            txFrame =   int(fields[9])
                            if havePrevData > 0:
                                if 'errout' in networkIOFields:
                                    myStats = myStats + "{0}errout_{1}={2}".format(comma,interface, txErrors - prevNetworkStats[interface][8])
                                    comma = ','
                                if 'dropout' in networkIOFields:
                                    myStats = myStats + "{0}dropout_{1}={2}".format(comma,interface, txDropped - prevNetworkStats[interface][9])
                                    comma = ','
                                if 'overrunout' in networkIOFields:
                                    myStats = myStats + "{0}errout_{1}={2}".format(comma,interface, txOverrun - prevNetworkStats[interface][10])
                                    comma = ','
                                if 'frameout' in networkIOFields:
                                    myStats = myStats + "{0}errout_{1}={2}".format(comma,interface, txFrame - prevNetworkStats[interface][11])
                                    comma = ','

                            prevNetworkStats[interface][8] = txErrors
                            prevNetworkStats[interface][9] = txDropped
                            prevNetworkStats[interface][10] = txOverrun
                            prevNetworkStats[interface][11] = txFrame
                            
                    elif re.search(r'RUNNING', line) != None:
                        ### store interface values
                        interface = re.sub(r':','', fields[0])
                        if debugLevel > 2:
                            print("DEBUG-3 JAGetNetworkIOCounters() Interface:{0}, line:{1}".format(interface, line))

                return myStats

            except OSError as err:
                errorMsg= "ERROR JAGetNetworkIOCounters() OSError:{0}, fields:|{1}|, install psutils on this server to get OS stats".format(err, networkIOFields)

    elif OSType == 'Windows' :
        if psutilModulePresent == True:
            tempStats = psutil.net_io_counters()
            if debugLevel > 1:
                print("DEBUG-2 JAGetNetworkIOCounters() OSType:{0}, used psutil.net_io_counters() to get data:{1}".format(OSType, tempStats))
            havePrevData = len(prevNetworkStats)
            count = 0
            tempStatsLen = len(tempStats)
            while count < tempStatsLen:
                fieldName = tempStats._fields[count]
                fieldValue = tempStats[count]
                if havePrevData > 0:
                    fieldValue = fieldValue - prevNetworkStats['all'][count]
                prevNetworkStats['all'][count]  = tempStats[count]
                myStats = myStats + "{0}{1}={2}".format(comma,fieldName,fieldValue) 
                comma = ','
                count = count + 1
        else:
            errorMsg= "ERROR JAGetNetworkIOCounters() fields:|{0}|, install psutils on this server to get OS stats".format(networkIOFields)

    if myStats == '':
        print(errorMsg)
        JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    return myStats

if psutilModulePresent == True :
    import psutil


### reduce process priority
if OSType == 'Windows':
    if psutilModulePresent == True:
        p = psutil.Process()
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
else:
    ### on all unix hosts, reduce to lowest priority
    os.nice(19) 
    if debugLevel > 1:
        print("DEBUG-2 process priority: {0}".format( os.nice(0)) )

### first time, sleep for dataCollectDurationInSec so that log file can be processed and posted after waking up
sleepTimeInSec = dataPostIntervalInSec

### get variables so that these can be used in sar first time
JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 2 ) 
JAToTimeString =  JAGlobalLib.JAGetTime( 0 )
JADayOfMonth = JAGlobalLib.JAGetDayOfMonth(0)

### this is to call the first time and ignore the return values
if psutilModulePresent == True :
    psutil.cpu_times_percent()
    psutil.cpu_percent()
else:
    ### this is to get /proc/stat and store as prev value so that next time, sample will be done after sample interval
    JAGetCPUPercent()

### this is to get first disk io sample so that delta can be computed later
JAGetDiskIOCounters('', False)

### this is to get first network sample so that delta can be computed later
JAGetNetworkIOCounters('',False)

if sys.version_info >= (3,3):
    import importlib
    try:
        importlib.util.find_spec("requests")
        importlib.util.find_spec("json")
        import requests
        from urllib3.exceptions import InsecureRequestWarning
        from urllib3 import disable_warnings

        requestSession = requests.session()
        if disableWarnings == True:
            disable_warnings(InsecureRequestWarning)

        useRequests = True
    except ImportError:
        useRequests = False
else:
    useRequests = False


### until the end time, keep checking the log file for presence of patterns
###   and post the stats per post interval
while loopStartTimeInSec  <= statsEndTimeInSec :
  if debugLevel > 0:
    try:
        if sys.version_info.major >= 3 and sys.version_info.minor >= 3:
            myProcessingTime = time.process_time()
        else:
            myProcessingTime = 0
    except:
        myProcessingTime = 0
    print('DEBUG-1 processing time: {0}, Sleeping for: {1} sec'.format( myProcessingTime, sleepTimeInSec ))
  time.sleep( sleepTimeInSec)
  ### take current time, it will be used to find files modified since this time for next round
  logFileProcessingStartTime = time.time()

  JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 2 ) 
  JAToTimeString =  JAGlobalLib.JAGetTime( 0 )
  JADayOfMonth = JAGlobalLib.JAGetDayOfMonth(0)
  
  ### copy constant data portion
  tempOSStatsToPost = OSStatsToPost.copy()

  ### Now gather OS stats
  for key, spec in JAOSStatsSpec.items():
    fields = spec[0]

    ### remove space from fieds
    fields = re.sub('\s+','',fields)

    tempPostData = False

    if debugLevel > 0:
        print('DEBUG-1 Collecting {0} OS stats for fields: {1}, using psutilModule:{2}'.format(key, fields, psutilModulePresent))

    if key == 'cpu_times_percent':
        stats = JAGetCPUTimesPercent(fields)
        if stats != '' and stats != None: 
                tempPostData = True

    elif key == 'cpu_percent':
        stats = JAGetCPUPercent()
        if stats != '' and stats != None: 
            tempPostData = True
            ## stats is of the form stats=<value>
            label, value = re.split('=', '{0}'.format( stats) )
            ### write current CPU usage to history
            JAGlobalLib.JAWriteCPUUsageHistory( value )

    elif key == 'virtual_memory':
        stats = JAGetVirtualMemory(fields)
        if stats != '' and stats != None: 
            tempPostData = True

    elif key == 'swap_memory':
        stats = JAGetSwapMemory(fields)
        if stats != '' and stats != None: 
            tempPostData = True

    elif key == 'process':
        stats = JAGetProcessStats( spec[1], fields )
        if stats != '' and stats != None: 
            tempPostData = True

    elif key == 'disk_io_counters':
        ## psutil.disk_io_counters() gives cumulative value. Delta value is more useful in this case.
        stats = JAGetDiskIOCounters(fields)
        if stats != '' and stats != None: 
            tempPostData = True

    elif key == 'net_io_counters':
        ## psutil.net_io_counters() gives cumulative value. Delta value is more useful in this case.
        stats = JAGetNetworkIOCounters(fields)
        if stats != '' and stats != None: 
            tempPostData = True

    elif key == 'filesystem':
        stats = JAGetFileSystemUsage( spec[1], fields)
        if stats != '' and stats != None: 
            tempPostData = True

    elif key == 'socket_stats':
        stats = JAGetSocketStats(fields)
        if stats != '' and stats != None: 
            tempPostData = True

    else:
        print('ERROR Invaid psutil function name:|{0}| in configFile:|{1}|'.format(key, configFile))

    if debugLevel > 0:
        print('DEBUG-1 Collected data:{0}'.format(stats))

    if tempPostData == True :
        ### remove leading word and brakets from stats
        ### <skipWord>(metric1=value1, metric2=value2....)
        ### svmem(total=9855512576, available=9557807104, percent=3.0, used=105254912, free=9648640000, active=77885440, inactive=28102656, buffers=16416768, cached=85200896, shared=307200, slab=41705472)
        ### convert above like to format like
        ###    virtual_memory_total=9855512576, virtual_memory_available=9557807104,...
        ###    <-- key ------>                  <--- key ----->
        valuePairs = '' 
        tempValue1 = re.split('[\(\)]', '{0}'.format(stats) ) 
        if len(tempValue1) > 1 :
            tempValue2 = tempValue1[1].split(', ')
        else:
            if re.search( ',', '{0}'.format(stats) ) != None :
                ### for the values derived without the use of psutil, the values are in the form
                ### ["['socket_total=2', 'socket_established=2', 'socket_time_wait=0']"]
                ###     <----------------------------------------------------------> extract this portion
                ###   and split fields to make separate list tempValue2 
                tempValue2 = '{0}'.format(stats).split(',')
            else:
                tempValue2=tempValue1
        comma = ''    
        for item in tempValue2:
            if item != '':
                valuePairs = valuePairs + '{0}{1}_{2}'.format(comma, key, item)
                comma = ','
        if valuePairs != '':
            timeStamp = JAGlobalLib.UTCDateTime() 
            tempOSStatsToPost[key] = 'timeStamp={0},{1}'.format(timeStamp, valuePairs)

  JAPostDataToWebServer(tempOSStatsToPost, useRequests, storeUponFailure)
    
  ### if elapsed time is less than post interval, sleep till post interval elapses
  elapsedTimeInSec = time.time() - logFileProcessingStartTime
  if elapsedTimeInSec < dataCollectDurationInSec :
       sleepTimeInSec = dataPostIntervalInSec - elapsedTimeInSec
       if sleepTimeInSec < 0 :
           sleepTimeInSec = 0
  else:
       sleepTimeInSec = 0

  ### take curren time so that processing will start from current time
  loopStartTimeInSec = logFileProcessingStartTime

### close fileNameRetryStatsPost
if retryOSStatsFileHandleCurrent != None :
    retryOSStatsFileHandleCurrent.close()

try:
    if sys.version_info.major >= 3 and sys.version_info.minor >= 3:
        myProcessingTime = time.process_time()
    else:
        myProcessingTime = 'N/A'
except:
    myProcessingTime = 'N/A'
programEndTime = time.time()
programExecTime = programEndTime - programStartTime
JAOSStatsExit( 'PASS  Processing time this program: {0}, programExecTime: {1}'.format( myProcessingTime, programExecTime ))
