
""" 
This script gathers and POSTs OS stats to remote web server
Posts jobName=OSStats, hostName=<thisHostName>, fileName as parameter in URL
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
-D    debugLevel - 0, 1, 2, 3
        default = 0

returnResult
    Print result of operation to log file 

Note - did not add python interpreter location at the top intentionally so that
    one can execute this using python or python3 depending on python version on target host

Author: havembha@gmail.com, 2021-07-04

2021-08-15 Added capability to collect file system usage percentage for given filesystem name(s)
    Added capability use sar data if present instead of collecting data fresh

2021-12-20 When config file is not passed, used OS specific config file if present with the name
    JAGatherOSStats<OSType>.yml where OSType can be Windows, Linux, ...
    Else, generic config file JAGatherOSStats.yml is used.

    If multiple process instances are present with the same process name, the stats are
      aggregated for all those process instances.

"""
import os, sys, re
import datetime
import JAGlobalLib
import time
import subprocess
import signal
from collections import defaultdict

### MAJOR 1, minor 10, buildId 01
JAVersion = "01.10.01"

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
prevCPUStats = [None, None, None, None, None, None, None, None]

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
            global webServerURL, disableWarnings, verifyCertificate, numSamplesToPost

    """

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
    if debugLevel > 1 :
        print('DEBUG-2 JAGatherEnvironmentSpecs(), DataPostIntervalInSec:{0}, DataCollectDurationInSec: {1}, DisableWarnings: {2}, verifyCertificate: {3}, WebServerURL: {4}'.format( dataPostIntervalInSec, dataCollectDurationInSec, disableWarnings, verifyCertificate, webServerURL))

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

def JAGetProcessStats( processNames, fields ):
    """
    This function gets CPU, MEM, VSZ, RSS used by processes 
    Fields supported are
        CPU, MEM, VSZ, RSS as given by ps aux command

    Returns stats in the form
        process_Name_field=fieldValue,process_Name_field=fieldValue,...
    """
    global psutilModulePresent
    myStats = ''
    comma = ''
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
            print("ERROR JAGetProcessStats() install psutil module to use this feature")
            return None

    else:
      ### get process stats for all processes
      result = subprocess.run( ['ps', 'aux'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      index = 0
      lines = result.stdout.decode('utf-8').split('\n')
      for line in lines:
        line = re.sub('\s+', ' ', line)
        if len(line) < 5:
            continue
        try:
            ### line is of the form with 11 columns total
            ### USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
            parent, pid, CPUPercent, MEMPercent, VSZ, RSS, TTY, STAT, START, TIME, COMMAND = line.split(' ', 10)

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
                    ### replace ., - with _
                    shortProcessName = re.sub(r'[\.\-]', '_', shortProcessName)
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
    """
    myStats = ''
    comma = ''
    global configFile
    if fileSystemNames == None:
        print('ERROR JAGetFileSystemUsage() NO filesystem name passed')
        return None

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
        index = 0
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
    This function gets socket counts on Linux hosts
      Sockets in established, and time_wait state can be counted separately
      Can also count all sockets, in all states

    Fields supported are
       total, established, time_wait

    """
    myStats = '' 
    comma = '' 
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
        if re.match(r'^tcp|^udp|^  TCP|^  UDP', line) == None:
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
        Else if psutil is not supported in current python version, and
            sysstat or sa path is present, stats are derived using sar command

    If OSType is Windows,
        use psutil, if present, to get data
        else, print error, return empty string

    return data in CSV format (name1=value1,name2=value2,..) 
       or empty string if can't be computed

    """
    global psutilModulePresent
    myStats = '' 
    comma = ''
    global OSType, OSName, OSVersion, debugLevel, prevCPUStats
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-u'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            if psutilModulePresent == True :
                myStats = "cpu_percent_used={1:f}".format( psutil.cpu_percent() )
            else:
                try:
                    # Read first line from /proc/stat. It should start with "cpu"
                    # and contains times spent in various modes by all CPU's totalled.
                    #
                    with open("/proc/stat") as procfile:
                        cpustats = procfile.readline().split()

                        # ensure first line has cpu info
                        if cpustats[0] == 'cpu':
                            if prevCPUStats[1] != None:

                                #
                                # Refer to "man 5 proc" (search for /proc/stat) for information
                                # about which field means what.
                                #
                                # Here we do calculation as simple as possible:
                                # CPU% = 100 * time_doing_things / (time_doing_things + time_doing_nothing)
                                #
                                user_time = float(cpustats[1]) - prevCPUStats[1]   
                                nice_time = float(cpustats[2]) - prevCPUStats[2]     
                                system_time = float(cpustats[3]) - prevCPUStats[3]

                                idle_time = float(cpustats[4]) - prevCPUStats[4]   
                                iowait_time = float(cpustats[5]) - prevCPUStats[5]    

                                time_doing_things = user_time + nice_time + system_time
                                time_doing_nothing = idle_time + iowait_time
                                total_time = time_doing_things + time_doing_nothing

                                # Calculate a percentage of change since last run:
                                #
                                cpu_percentage = 100.0 * time_doing_things/total_time 

                                comma = ''
                                if 'cpu_percent_used' in fields:
                                    myStats = myStats +  "{0}cpu_percent_used={1:f}".format(comma, cpu_percentage )
                                    comma = ','
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

                            prevCPUStats[0] = cpustats[0]
                            prevCPUStats[1] = float(cpustats[1])
                            prevCPUStats[2] = float(cpustats[2])
                            prevCPUStats[3] = float(cpustats[3])
                            prevCPUStats[4] = float(cpustats[4])
                            prevCPUStats[5] = float(cpustats[5])

                except OSError:
                    errorMsg = "ERROR JAGetCPUTimesPercent() fields:|{0}|,install psutils on this server to get OS stats".format(fields)
                    print(errorMsg)
                    JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
            return myStats

    elif OSType == 'Windows' :
        if psutilModulePresent == True :
            myStats = "cpu_percent_used={1:f}".format( psutil.cpu_percent() )
        else:
            errorMsg = "ERROR JAGetCPUTimesPercent() fields:|{0}|, install psutils on this server to get OS stats".format( fields)
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)
        return myStats

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
            print("ERROR JAGetCPUTimesPercent() NO sar data available from {0} to {1}".format( JAFromTimeString, JAToTimeString))
            return myStats

        ### compute start time 10 times more than dataPostIntervalInSec
        ### expect to see sar data collected in this duration
        JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
        return JAGetCPUTimesPercent( fields, True )

    for line in lines:
        ### remove extra space
        line = re.sub('\s+', ' ', line)

        if re.search('%user', line) != None:
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
                elif 'cpu_percent_used' in fields:
                    ### total CPU usage is to be returned
                    ### compute this as  100 - idle
                    if tempHeadingFields[ columnCount ] == 'idle' :
                        myStats = myStats + "{0}cpu_percent_used={1:f}".format( comma, 100 - float( field ))

                columnCount += 1

        else:
            prevLine = line

    return myStats

def JAGetCPUPercent():
    """
    Get total CPU usage that includes all types of use. This is computed as 100 - idle time.

    """
    myFields = ['cpu_percent_used']
    myStats = JAGetCPUTimesPercent( myFields )  

    return myStats

def JAGetVirtualMemory(fields, recursive=False):
    myStats = ''
    comma = ''
    global OSType, OSName, OSVersion, debugLevel
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-r'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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
                    print("ERROR JAGetVirtualMemory() NO sar data available from {0} to {1}".format( JAFromTimeString, JAToTimeString))
                    return myStats

                ### compute start time 10 times more than dataPostIntervalInSec
                ### expect to see sar data collected in this duration
                JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
            
            for line in lines:
                ### remove extra space
                line = re.sub('\s+', ' ', line)

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
        else:
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
                        divideByToConvertToGB = 1000000
                        if tempFields[2] != None:
                            if tempFields[2] == 'kB':
                                divideByToConvertToGB = 1000000
                            elif tempFields[2] == 'mB':
                                divideByToConvertToGB = 1000
                            
                        if tempFields[0] == 'MemTotal:':
                            if 'total' in fields:
                                memTotal = value = int(tempFields[1])/divideByToConvertToGB
                                myStats = myStats + '{0}total={1}'.format(comma, value)     
                                comma = ','
                        elif tempFields[0] == 'MemAvailable:':
                            if 'available' in fields:
                                value = int(tempFields[1])/divideByToConvertToGB
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
                                memFree = value /divideByToConvertToGB 
                        elif tempFields[0] == 'Committed_AS:':
                            if 'commit' in fields:
                                value = int(tempFields[1])
                                myStats = myStats + '{0}commit={1}'.format(comma, value)
                                comma = ','

                    if 'memused' in fields:
                        if memTotal != None and memFree != None:
                            myStats = myStats + '{0}memused={1}'.format(comma, int(memTotal - memFree))      

            except OSError:
                errorMsg = "ERROR JAGetSwapMemory() can't read /proc/meminfo"
                print(errorMsg)
                JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    elif OSType == 'Windows' :
        print("ERROR JAGetVirtualMemory() fields:|{0}|, install psutils on this server to get OS stats".format(fields))
        return myStats

    return myStats

def JAGetSwapMemory(fields, recursive=False):
    myStats = ''
    comma = ''
    global OSType, OSName, OSVersion, debugLevel
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if JASysStatFilePathName != None and JASysStatFilePathName != '':
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-S'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
                    print("ERROR JAGetSwapMemory() NO sar data available from {0} to {1}".format( JAFromTimeString, JAToTimeString))
                    return myStats

                ### compute start time 10 times more than dataPostIntervalInSec
                ### expect to see sar data collected in this duration
                JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
            
            for line in lines:
                ### remove extra space
                line = re.sub('\s+', ' ', line)

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
        else:
            ### add logic to get values directly if possible
            myStats = ''
        
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
                    divideByToConvertToGB = 1000000
                    if tempFields[2] != None:
                        if tempFields[2] == 'kB':
                            divideByToConvertToGB = 1000000
                        elif tempFields[2] == 'mB':
                            divideByToConvertToGB = 1000
                        
                    if tempFields[0] == 'SwapTotal:':
                        if 'total' in fields:
                            swapTotal = int(tempFields[1])/divideByToConvertToGB
                            myStats = myStats + '{0}total={1}'.format(comma, swapTotal)     
                            comma = ','
                    elif tempFields[0] == 'SwapFree:':
                        if 'free' in fields:
                            swapFree = int(tempFields[1])/divideByToConvertToGB
                            myStats = myStats + '{0}free={1}'.format(comma, swapFree)
                            comma = ','
                    if swapTotal != None and swapFree != None:
                        if swapTotal > 0 and 'percent' in fields:
                            myStats = myStats + '{0}percent={1}'.format(comma, 100 * swapFree/swapTotal) 
                        break

        except OSError:
            errorMsg = "ERROR JAGetSwapMemory() can't read /proc/meminfo"
            print(errorMsg)
            JAGlobalLib.LogMsg(errorMsg, JAOSStatsLogFileName, True)

    elif OSType == 'Windows' :
        myStats = ''

    if myStats == '':
        print("ERROR JAGetSwapMemory() fields:|{0}|, install psutils on this server to get OS stats".format(fields))

    return myStats

def JAGetDiskIOCounters(fields, recursive=False):
    myStats = ''
    comma = ''
    global OSType, OSName, OSVersion, debugLevel
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if OSName == 'rhel' or OSName == 'ubuntu':
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-b'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            print("ERROR JAGetDiskIOCounters() fields:|{0}|, install psutils on this server to get OS stats".format(fields))
            return myStats

    elif OSType == 'Windows' :
        print("ERROR JAGetDiskIOCounters() fields:|{0}|, install psutils on this server to get OS stats".format(fields))
        return myStats

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
            print("ERROR JAGetDiskIOCounters() NO sar data available from {0} to {1}".format( JAFromTimeString, JAToTimeString))
            return myStats

        ### compute start time 10 times more than dataPostIntervalInSec
        ### expect to see sar data collected in this duration
        JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
    
    for line in lines:
        ### remove extra space
        line = re.sub('\s+', ' ', line)

        if re.search('rtps', line) != None:
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

    return myStats

def JAGetNetworkIOCounters(fields, recursive=False):
    myStats = ''
    comma = ''
    global OSType, OSName, OSVersion, debugLevel
    global JAFromTimeString, JAToTimeString, JADayOfMonth

    if OSType == 'Linux':
        if OSName == 'rhel' or OSName == 'ubuntu':
            result = subprocess.run( ['sar', '-f', JASysStatFilePathName + 'sa' + JADayOfMonth, '-s', JAFromTimeString, '-e', JAToTimeString, '-n', 'EDEV'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            print("ERROR JAGetNetworkIOCounters() fields:|{0}|, install psutils on this server to get OS stats".format(fields))
            return myStats

    elif OSType == 'Windows' :
        print("ERROR JAGetNetworkIOCounters() fields:|{0}|, install psutils on this server to get OS stats".format(fields))
        return myStats

    lines = result.stdout.decode('utf-8').split('\n')
    ### lines of the form
    ###
    ### Linux 5.11.0-25-generic (havembha)      08/22/2021      _x86_64_        (8 CPU)
    ###
    ### 07:40:15 PM     IFACE   rxerr/s   txerr/s    coll/s  rxdrop/s  txdrop/s  txcarr/s  rxfram/s  rxfifo/s  txfifo/s
    ### 07:50:04 PM        lo      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
    ### 07:50:04 PM    enp3s0      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
    ### 07:50:04 PM    wlp2s0      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
    ### Average:           lo      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
    ### Average:       enp3s0      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00
    ### Average:       wlp2s0      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00

    if len( lines ) < 5:
        ### if sar does not have sample between the given start and end time, single line output will be present
        ### change the start time to -10 min and call this function again
        if recursive == True :
            print("ERROR JAGetNetworkIOCounters() NO sar data available from {0} to {1}".format( JAFromTimeString, JAToTimeString))
            return myStats

        ### compute start time 10 times more than dataPostIntervalInSec
        ### expect to see sar data collected in this duration
        JAFromTimeString = JAGlobalLib.JAGetTime( dataPostIntervalInSec * 23 )
    
    for line in lines:
        ### remove extra space
        line = re.sub('\s+', ' ', line)

        if re.search('IFACE', line) != None:
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
            ### TBD enhance this to select a line with desired interface
            prevLine = line

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
        print('DEBUG-1 Collecting {0} OS stats for fields: {1}'.format(key, fields))

     if psutilModulePresent == True :
        if key == 'cpu_times_percent':
            stats = psutil.cpu_times_percent()
            tempPostData = True

        elif key == 'cpu_percent':
            stats = psutil.cpu_percent(interval=1)
            tempPostData = True

            ## stats is of the form stats <value>
            value = '{:.2f}'.format(stats)
            ### write current CPU usage to history
            JAGlobalLib.JAWriteCPUUsageHistory( value )

        elif key == 'virtual_memory':
            stats = psutil.virtual_memory()
            tempPostData = True

        elif key == 'swap_memory':
            stats = psutil.swap_memory()
            tempPostData = True

        elif key == 'process':
            stats = JAGetProcessStats( spec[1], fields )
            tempPostData = True

        elif key == 'disk_io_counters':
            stats = psutil.disk_io_counters()
            tempPostData = True

        elif key == 'net_io_counters':
            stats = psutil.net_io_counters()
            tempPostData = True

        elif key == 'filesystem':
            ### fsNames in index 1 of spec[]
            stats = JAGetFileSystemUsage( spec[1], fields)
            tempPostData = True

        elif key == 'socket_stats':
            stats = JAGetSocketStats(fields)
            tempPostData = True

        else:
            print('ERROR Invaid psutil function name:|{0}| in configFile:|{1}|'.format(key, configFile))

     else:
        ### get stats from sar data
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
            stats = JAGetDiskIOCounters(fields)
            if stats != '' and stats != None: 
                tempPostData = True

        elif key == 'net_io_counters':
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
    
        for item in tempValue2:
            if item != '':
                if valuePairs == '': 
                    if key == 'cpu_percent':
                        if re.search('cpu_percent_used', item) == None:
                            ### this has the value in the form cpu_percent 3.0
                            valuePairs = '{0}_used={1}'.format(key,item)
                        else:
                            ### this has the value in the form cpu_percent_used=3.0
                            valuePairs = '{0}'.format(item)
                    else:
                        valuePairs = '{0}_{1}'.format(key,item) 
                else:
                    valuePairs = '{0},{1}_{2}'.format(valuePairs, key, item)
        if valuePairs != '':
            timeStamp = JAGlobalLib.UTCDateTime() 
            tempOSStatsToPost[key] = 'timeStamp={0},{1}'.format(timeStamp, valuePairs)

  ### Now post the data to web server
  import json
  headers= {'Content-type': 'application/json', 'Accept': 'text/plain'} 
  if sys.version_info >= (3,3):
    import importlib
    try:
          importlib.util.find_spec("requests")
          importlib.util.find_spec("json")
          useRequests = True
    except ImportError:
          useRequests = False
  else:
    useRequests = False

  import json
  data = json.dumps(tempOSStatsToPost)
  if useRequests == True:
    import requests

    if debugLevel > 1:
        print ('DEBUG-2 OSStatsToPost:{0}'.format( tempOSStatsToPost) )
    if disableWarnings == True:
        requests.packages.urllib3.disable_warnings()

    returnResult = requests.post( webServerURL, data, verify=verifyCertificate, headers=headers)
    print('INFO  - Result of posting data to web server {0} :\n{1}'.format(webServerURL, returnResult.text))
  else:
      result =  subprocess.run(['curl', '-k', '-X', 'POST', webServerURL, '-H', "Content-Type: application/json", '-d', data],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
      returnStatus = result.stdout.decode('utf-8').split('\n')
      print('INFO - Result of posting data to web server {0}'.format( returnStatus ))

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
