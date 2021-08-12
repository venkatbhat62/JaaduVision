
""" 
This script gathers and POSTs OS stats to remote web server
Posts jobName=OSStats, hostName=<thisHostName>, fileName as parameter in URL
Posts <key> {metric1=value1, metric2=value2...} one line per key type as data

Parameters passed are:
    configFile - yaml file containing stats to be collected
        default - get it from JAGlobalVars.yml 
    webServerURL - post the data collected to web server 
        default - get it from JAGlobalVars.yml
    samplingInterval - sample data at this periodicity, in seconds
        default - get it from JAGlobalVars.yml
    dataPostInterval - post data at this periodicity, in seconds
        default - get it from JAGlobalVars.yml
            if samplingInterval is one min, and dataPostInterval is 10 min,  
                it will post 10 samples
    debugLevel - 0, 1, 2, 3
        default = 0

returnResult
    Print result of operation to log file 

Note - did not add python interpreter location at the top intentionally so that
    one can execute this using python or python3 depending on python version on target host

Author: havembha@gmail.com, 2021-07-04
"""
import os, sys, re
import datetime
import JAGlobalLib
import psutil
import time

## global default parameters
configFile = '' 
webServerURL = ''
samplingInterval = 0
dataPostInterval = 0
debugLevel = 0
JAOSStatsLogFileName =  None 
componentName = ''
platformName = ''
siteName = ''

### take current timestamp
JAOSStatsStartTime = datetime.datetime.now()

## parse arguments passed from command line
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-D", type=int, help="debug level 0 - None, 1,2,3-highest level")
parser.add_argument("-c", help="yaml file containing stats to be collected, default - JAGatherOSStats.yml")
parser.add_argument("-U", help="web server URL to post the data, default - get it from configFile")
parser.add_argument("-i", type=int, help="sampling interval, default - get it from configFile")
parser.add_argument("-I", type=int, help="data post interval, default - get it from configFile")
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
    samplingInterval = args.i

if args.I:
    dataPostInterval = args.I

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
    print('DEBUG-1 Parameters passed configFile:{0}, webServerURL:{1}, samplingInterval:{2}, debugLevel:{3}, componentName:{4}, plaformName:{5}, siteName: {6}, environment: {7}\n'.format(configFile, webServerURL, samplingInterval, dataPostInterval, debugLevel, componentName, platformName, siteName, environment))

def JAOSStatsExit(reason):
    print(reason)
    JAOSStatsEndTime = datetime.datetime.now()
    JAOSStatsDuration = JAOSStatsEndTime - JAOSStatsStartTime
    JAOSStatsDurationInSec = JAOSStatsDuration.total_seconds()
    JAGlobalLib.LogMsg('{0}, processing duration:{1} sec\n'.format(reason,JAOSStatsDurationInSec ), JAOSStatsLogFileName, True)
    sys.exit()

### use default config file
if configFile == '':
    configFile = "JAGatherOSStats.yml"

### OS stats spec dictionary
### contains keys like cpu_times, cpu_percent, virtual_memory etc that match to the 
###   psutil.<functionName>
### values are like {Fields: user, system, idle, iowait} 
###    CSV field names match to the field names referred in psutil.

JAOSStatsSpec = {}
### get current hostname
import platform
thisHostName = platform.node()

### show warnings by default 
JADisableWarnings = False
### verify server certificate by default
JAVerifyCertificate = True

if sys.version_info >= (3,3):
    import importlib
    try:
        importlib.util.find_spec("yaml")
        yamlModulePresent = True
    except ImportError:
        yamlModulePresent = False
else:
    yamlModulePresent = False


## read default parameters and OS Stats collection spec
try:
    with open(configFile, "r") as file:

        ### use limited yaml reader when yaml is not available
        if yamlModulePresent == True:
            import yaml
            JAOSStats = yaml.load(file, Loader=yaml.FullLoader)
            file.close()
        else:
            JAStats = JAGlobalLib.JAYamlLoad( configFile )
        if debugLevel > 1 :
            print('DEBUG-2 Content of config file: {0}, read to JAStats: {1}'.format(configFile, JAOSStats))

        if samplingInterval == 0:
            if JAOSStats['Default']['SamplingIntervalInSec'] != None:
                samplingInterval = int(JAOSStats['Default']['SamplingIntervalInSec'])
            else:
                samplingInterval = 60
        if dataPostInterval == 0:
            if JAOSStats['Default']['DataPostIntervalInSec'] != None:
                dataPostInterval = int(JAOSStats['Default']['DataPostIntervalInSec'])
            else:
                dataPostInterval = 600

        if JAOSStatsLogFileName == None:
            if JAOSStats['LogFileName'] != None:
                JAOSStatsLogFileName = JAOSStats['LogFileName']
            else:
                JAOSStatsLogFileName = 'JAGatherOSStats.log'

        if webServerURL == '':

            ### check to which environment current host belongs to
            for env in JAOSStats['Environment']:
                ### get environment spec from config file
                if JAOSStats['Environment'][env] != None:
                    tempEnvironment = JAOSStats['Environment'][env]

                    ## see whether the current hostname matches to environment
                    if re.search( tempEnvironment, thisHostName) != None:
                        ### get web server URL matching to current environment
                        if JAOSStats['Default'][env]['WebServerURL'] != None:
                            webServerURL = JAOSStats['Default'][env]['WebServerURL']
                        if JAOSStats['Default'][env]['JADisableWarnings'] != None:
                            JADisableWarnings = JAOSStats['Default'][env]['JADisableWarnings']
                        if JAOSStats['Default'][env]['JAVerifyCertificate'] != None:
                            JAVerifyCertificate = JAOSStats['Default'][env]['JAVerifyCertificate']
        ### read CPU stats spec
        ### format:
        ### CPU:
        ###    - Name: cpu_times
        ###      Fields: user, system, idle, iowait
        ###    - Name: cpu_percent
        ###      Fields: percentUsed

        if 'CPU' in JAOSStats.keys() :
            for statType in JAOSStats['CPU']:
                name = statType.pop('Name')
                JAOSStatsSpec[name] = statType

        ### read Memory stats spec
        ### Memory:
        ###    - Name: virtual_memory
        ###      Fields: total,available
        ###    - Name: swap_memory
        ###      Fields: total,free,percentUsed
        if 'Memory' in JAOSStats.keys() :
            for statType in JAOSStats['Memory']:
                name = statType.pop('Name')
                JAOSStatsSpec[name] = statType

        if 'Disk' in JAOSStats.keys() :
            ### read Disk stats spec
            for statType in JAOSStats['Disk']:
                name = statType.pop('Name')
                JAOSStatsSpec[name] = statType

        if 'Network' in JAOSStats.keys() :
            ### network stats spec
            for statType in JAOSStats['Network']:
                name = statType.pop('Name')
                JAOSStatsSpec[name] = statType

except OSError as err:
    JAOSStatsExit('ERROR - Can not open configFile:|{0}|, OS error: {1}\n'.format(configFile,err)) 

if debugLevel > 0:
    print('DEBUG-1 Parameters after reading configFile:{0}, webServerURL:{1}, samplingInterval:{2}, dataPostInterval:{3}, debugLevel: {4}\n'.format(configFile, webServerURL, samplingInterval, dataPostInterval, debugLevel))
    for key, spec in JAOSStatsSpec.items():
        fields = spec['Fields'] 
        print('DEBUG-1 Name: {0}, Fields: {1}'.format(key, fields))

### if another instance is running, exit
import subprocess,platform

if platform.system() == 'Windows':
    result =  subprocess.run(['tasklist'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)

else:
    result =  subprocess.run(['ps', '-ef'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)

returnProcessNames = result.stdout.decode('utf-8').split('\n')
procCount = 0
for procName in returnProcessNames:
    if re.search( 'JAGatherOSStats.py', procName ) != None :
        if re.search( r'vi |vim |more |view |cat ', procName ) == None:
            procCount += 1
            if procCount > 1:
                JAStatsExit('WARN - another instance ({0}) is running, exiting\n'.format(procName) )

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

### Now gather OS stats
for key, spec in JAOSStatsSpec.items():
    fields = spec['Fields']
    tempPostData = False

    if debugLevel > 1:
        print('DEBUG-1 Collecting {0} OS stats for fields: {1}'.format(key, fields))

    if key == 'cpu_times_percent':
        stats = psutil.cpu_times_percent()
        tempPostData = True

    elif key == 'cpu_percent':
        stats = psutil.cpu_percent(interval=1)
        tempPostData = True

    elif key == 'virtual_memory':
        stats = psutil.virtual_memory()
        tempPostData = True

    elif key == 'swap_memory':
        stats = psutil.swap_memory()
        tempPostData = True

    elif key == 'disk_io_counters':
        stats = psutil.disk_io_counters()
        tempPostData = True

    elif key == 'net_io_counters':
        stats = psutil.net_io_counters()
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
            tempValue2=tempValue1
    
        for item in tempValue2:
            if valuePairs == '': 
                if key == 'cpu_percent':
                    ### this has the value in the form cpu_percent 3.0
                    valuePairs = '{0}={1}'.format(key,item)
                else:
                    valuePairs = '{0}_{1}'.format(key,item) 
            else:
                valuePairs = '{0},{1}_{2}'.format(valuePairs, key, item)

        timeStamp = JAGlobalLib.UTCDateTime() 
        OSStatsToPost[key] = 'timeStamp={0},{1}'.format(timeStamp, valuePairs)

### Now post the data to web server
import requests
import json
headers= {'Content-type': 'application/json', 'Accept': 'text/plain'} 

if debugLevel > 1:
    print ('DEBUG-2 OSStatsToPost:{0}'.format( OSStatsToPost) )
if JADisableWarnings == True:
    requests.packages.urllib3.disable_warnings()

returnResult = requests.post( webServerURL, data=json.dumps(OSStatsToPost), verify=JAVerifyCertificate, headers=headers)
print('INFO  - Result of posting data to web server {0} :\n{1}'.format(webServerURL, returnResult.text))

JAOSStatsExit( returnResult )
