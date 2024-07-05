
"""
This script generates test data in various log files so that the JAGatherLogStats.py can send the
simulated data to web server. Different types of log files are created so that log file search can
cover different possibilities.
- JATest.daily.log.YYYYMMDD - single file per day
- JATest.multiple.log.\d+.YYYYMMDD - multiple files per day
- JATest.single.log - single file across many days

This is to test the functionality of client processing log files and posting to web server, 
web script pushing the data to DB like prometheus gateway or influxdb, DB making the data available to 
grafana, grafana presentation showing the data in dashboards

Parameters passed are:
    simulationType - random, predefined (default)
    debugLevel - 0,1,2,3, default 0

Author: havembha@gmail.com, 2021/08/01

Note: python interpreter is not mentioned at the start of the script so that it can be run 
   with whatever python version available on target host

"""
import datetime, time
import JAGlobalLib
#import os, sys, re
from random import seed
from random import randint

debugLevel = 3
simulationType = 'predefined'
testLogFileDaily = 'JATest.daily.log'
testLogFileMultiple = 'JATest.multiple.log'
testLogFileSingle = 'JATest.single.log'
testDurationInSec = 3600
stepTime = 5

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-D", type=int, help="debug level 0 - None, 1,2,3-highest level")
parser.add_argument("-d", type=int, help="duration in seconds")
parser.add_argument("-s", help="simulation type, predefined (default), random")

args = parser.parse_args()
if args.D:
    debugLevel = args.D
if args.d:
    testDurationInSec = args.d
if args.s:
    simulationType = args.s

if debugLevel > 0 :
    print('DEBUG-1 Parameters passed simultionType: {0}, testDurationInSec: {1}, debugLevel: {2}'.format(simulationType, testDurationInSec, debugLevel))

def JATestExit(reason):
    print(reason)
    exit()

lastFileTime = startTimeInSec = time.time()
# seed random number generator
seed(1)
traceId = 1

### increment file count for every 30 min
fileCount = 0
sleepTimeInSec = 0

while ( time.time() - startTimeInSec) < testDurationInSec:
    if simulationType == 'random':
        ### sleep for random time
        sleepTimeInSec = randint(0, 60)

    else:
        sleepTimeInSec += stepTime
        if sleepTimeInSec > 60:
            sleepTimeInSec = 5

    if debugLevel > 2:
        print('DEBUG-3 simulationType: {0}, sleeping for: {1}'.format( simulationType, sleepTimeInSec))

    time.sleep( sleepTimeInSec)

    rampupCount = 0

    currentTime = time.time()
    deltaTimeInMin = int((currentTime - lastFileTime) / 60)
    if ( deltaTimeInMin > 10 ):
        fileCount += 1
        lastFileTime = currentTime
    testLogFileNameMultiple = "{0}.{1}".format(testLogFileMultiple, fileCount)
    testLogFileNameSingle = "{0}".format(testLogFileSingle)
    testLogFileNameDaily = "{0}".format(testLogFileDaily)
    
    ### log messages to log file
    for count in range( int(sleepTimeInSec / 8) ):
        JAGlobalLib.LogMsg('TestMsg Pass\n', testLogFileNameMultiple, True)
        JAGlobalLib.LogMsg('TestMsg Pass\n', testLogFileNameSingle, False)
        JAGlobalLib.LogMsg('TestMsg Pass\n', testLogFileNameDaily, True)
        
        if count % 2 > 0:
            # to test PatternSum
            JAGlobalLib.LogMsg('TestMsg Fail\n', testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg('TestMsg Fail\n', testLogFileNameSingle, False)
            JAGlobalLib.LogMsg('TestMsg Fail\n', testLogFileNameDaily, True)

            msg = "leading text key1 {0} dummy1 key2 {1:.2f} dummy2\n".format( sleepTimeInSec, sleepTimeInSec/2)
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            # to test PatternAverage
            msg = "tps key1 {0} dummy1 key2 {1:.2f} dummy2\n".format( sleepTimeInSec, sleepTimeInSec/2)
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            # to test PatternDelta
            rampupCount += count
            msg = "total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount, rampupCount/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = "Stats MicroService1 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount, rampupCount/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = "Stats MicroService25 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount+10, (rampupCount+10)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = "Stats MicroService26 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount+20, (rampupCount+20)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = "Stats MicroService27 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount+30, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = "Stats client1 total key1 {0} dummy1 total key2 {1:.2f} key3 {2:.2f} dummy3\n".format( rampupCount+30, 100, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = "Stats client2 total key1 {0} dummy1 total key2 {1:.2f} key3 {2:.2f} dummy3\n".format( rampupCount+30, 200, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = "CSV,client2,{0},{1:.2f},{2:.2f}\n".format( rampupCount+30, rampupCount, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)

            # generate log to test TracePattern line with timestamp, traceId both in the same line, not a log block
            msg = "TraceId={0:016x} Service1 status=202 test trace line {1}\n".format(traceId, count)
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            # generate log to test TraceBlockStart, and TraceBlockEnd sequence
            # here, the traceId is in TraceBlockStart line
            msg = "TraceId={0:016x} Service2 account=1234 Name=JaaduVision test trace line {1}\n".format(traceId, count)
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = " 2nd line of prev trace line {0:016x}\n".format(traceId, count)
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)

            ## generate log to test TraceBlockStart, TracePattern, TraceBlockEnd sequence
            # here, the traceId is in TracePattern line, data to be masked in 5th line
            msg = "Block1 Service3 test trace line\n"
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)
            
            msg = " 2nd line of block status=404\n 3rd line of block \n 4th line of block {0:016x}\n 5th line of block account=1234 Name=JaaduVision \n 6th line of block \n".format(traceId)
            JAGlobalLib.LogMsg(msg, testLogFileNameMultiple, True, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameSingle, False)
            JAGlobalLib.LogMsg(msg, testLogFileNameDaily, True)

            traceId += count
        elif count % 3 > 0:
            JAGlobalLib.LogMsg('TestMsg Count\n', testLogFileNameMultiple, True)
            JAGlobalLib.LogMsg('TestMsg Count\n', testLogFileNameSingle, False)
            JAGlobalLib.LogMsg('TestMsg Count\n', testLogFileNameDaily, True)
    
JAGlobalLib.JAFindModifiedFiles( "{HOSTNAME}Test.py", "JA", 0, 3,'')            
