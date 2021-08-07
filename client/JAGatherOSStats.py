#!/usr/bin/python3

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

Author: havembha@gmail.com, 2021-07-04
"""
import yaml
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
    print(f'DEBUG-1 Parameters passed configFile:{configFile}, webServerURL:{webServerURL}, samplingInterval:{samplingInterval}, dataPostInterval:{dataPostInterval}, debugLevel:{debugLevel}, componentName:{componentName}, platformName:{platformName}, siteName:{siteName}, environment:{environment}')

def JAOSStatsExit(reason):
    print(f'{reason}')
    JAOSStatsEndTime = datetime.datetime.now()
    JAOSStatsDuration = JAOSStatsEndTime - JAOSStatsStartTime
    JAOSStatsDurationInSec = JAOSStatsDuration.total_seconds()
    JAGlobalLib.LogMsg(f'{reason}, processing duration:{JAOSStatsDurationInSec} sec\n', JAOSStatsLogFileName, True)
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

## read default parameters and OS Stats collection spec
try:
    with open(configFile, "r") as file:
        JAOSStats = yaml.load(file, Loader=yaml.FullLoader)

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

        for statType in JAOSStats['CPU']:
            name = statType.pop('Name')
            JAOSStatsSpec[name] = statType

        ### read Memory stats spec
        ### Memory:
        ###    - Name: virtual_memory
        ###      Fields: total,available
        ###    - Name: swap_memory
        ###      Fields: total,free,percentUsed
        for statType in JAOSStats['Memory']:
            name = statType.pop('Name')
            JAOSStatsSpec[name] = statType

        ### read Disk stats spec
        for statType in JAOSStats['Disk']:
            name = statType.pop('Name')
            JAOSStatsSpec[name] = statType

        ### network stats spec
        for statType in JAOSStats['Network']:
            name = statType.pop('Name')
            JAOSStatsSpec[name] = statType

except OSError as err:
    JAOSStatsExit(f'ERROR - Can not open configFile:|{configFile}|' + "OS error: {0}".format(err) + '\n')

if debugLevel > 0:
    print(f'DEBUG-1 Parameters after reading configFile:{configFile}, webServerURL:{webServerURL}, samplingInterval:{samplingInterval}, dataPostInterval:{dataPostInterval}, debugLevel:{debugLevel}')
    for key, spec in JAOSStatsSpec.items():
        fields = spec['Fields'] 
        print(f'DEBUG-1 Name: {key}, Fields: {fields}')

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
        if re.search( r'vi |more |view |cat ', procName ) == None:
            procCount += 1
            if procCount > 1:
                JAStatsExit(f'WARN - another instance ({procName}) is running, exiting' )

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
    if debugLevel > 1:
        print(f'DEBUG-1 Collecting {key} OS stats for fields: {fields}')

    if key == 'cpu_times_percent':
        stats = psutil.cpu_times_percent()

    elif key == 'cpu_percent':
        stats = psutil.cpu_percent(interval=1)

    elif key == 'virtual_memory':
        stats = psutil.virtual_memory()

    elif key == 'swap_memory':
        stats = psutil.swap_memory()

    elif key == 'disk_io_counters':
        stats = psutil.disk_io_counters()

    elif key == 'net_io_counters':
        stats = psutil.net_io_counters()

    else:
        print(f'ERROR Invaid psutil function name:|{key}| in configFile:|{configFile}|')

    ### remove leading word and brakets from stats
    ### <skipWord>(metric1=value1, metric2=value2....)
    ### svmem(total=9855512576, available=9557807104, percent=3.0, used=105254912, free=9648640000, active=77885440, inactive=28102656, buffers=16416768, cached=85200896, shared=307200, slab=41705472)
    ### convert above like to format like
    ###    virtual_memory_total=9855512576, virtual_memory_available=9557807104,...
    ###    <-- key ------>                  <--- key ----->
    valuePairs = '' 
    tempValue1 = re.split('[\(\)]', f'{stats}') 
    if len(tempValue1) > 1 :
        tempValue2 = tempValue1[1].split(', ')
    else:
        tempValue2=tempValue1
    
    for item in tempValue2:
        if valuePairs == '': 
            if key == 'cpu_percent':
                ### this has the value in the form cpu_percent 3.0
                valuePairs = key + '=' + f'{item}'
            else:
                valuePairs = key + "_" + f'{item}'
        else:
            valuePairs = valuePairs + "," + key + "_" + f'{item}'

    timeStamp = JAGlobalLib.UTCDateTime() 
    OSStatsToPost[key] = f'timeStamp={timeStamp},{valuePairs}'

### Now post the data to web server
import requests
import json
headers= {'Content-type': 'application/json', 'Accept': 'text/plain'} 

if debugLevel > 1:
    print (f'DEBUG-2 OSStatsToPost:{OSStatsToPost}')
if JADisableWarnings == True:
    requests.packages.urllib3.disable_warnings()

returnResult = requests.post( webServerURL, data=json.dumps(OSStatsToPost), verify=JAVerifyCertificate, headers=headers)
print(f'Result of posting data to web server {webServerURL} :\n{returnResult.text}')

JAOSStatsExit( returnResult )
