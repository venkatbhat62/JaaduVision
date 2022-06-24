
"""
This script generates test data in JATest.log.YYYYMMDD so that the JAGatherLogStats.py can send the
simulated data to web server. This is to test the functionality of client processing log files and posting to
web server, web script pushing the data to prometheus gateway, prometheus making the data available to 
grafana, grafana presentation showing the data in dashboards

Parameters passed are:
    simulationType - random (default), sawtooth
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
simulationType = 'random'
testLogFileName = 'JATest.log'
testDurationInSec = 3600
stepTime = 5

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-D", type=int, help="debug level 0 - None, 1,2,3-highest level")
parser.add_argument("-d", type=int, help="duration in seconds")
parser.add_argument("-s", help="simulator type, random (default), sawtooth")

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

startTimeInSec = time.time()
# seed random number generator
seed(1)
traceId = 1

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
    

    ### log messages to log file
    for count in range( int(sleepTimeInSec / 8) ):
        JAGlobalLib.LogMsg('TestMsg Pass\n', testLogFileName, True)
        
        if count % 2 > 0:
            # to test PatternSum
            JAGlobalLib.LogMsg('TestMsg Fail\n', testLogFileName, True)
            msg = "leading text key1 {0} dummy1 key2 {1:.2f} dummy2\n".format( sleepTimeInSec, sleepTimeInSec/2)
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            # to test PatternAverage
            msg = "tps key1 {0} dummy1 key2 {1:.2f} dummy2\n".format( sleepTimeInSec, sleepTimeInSec/2)
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            # to test PatternDelta
            rampupCount += count
            msg = "total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount, rampupCount/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "Stats MicroService1 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount, rampupCount/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "Stats MicroService25 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount+10, (rampupCount+10)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "Stats MicroService26 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount+20, (rampupCount+20)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "Stats MicroService27 total key1 {0} dummy1 total key2 {1:.2f} dummy2\n".format( rampupCount+30, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "Stats client1 total key1 {0} dummy1 total key2 {1:.2f} key3 {2:.2f} dummy3\n".format( rampupCount+30, 100, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "Stats client2 total key1 {0} dummy1 total key2 {1:.2f} key3 {2:.2f} dummy3\n".format( rampupCount+30, 200, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "CSV,client2,{0},{1:.2f},{2:.2f}\n".format( rampupCount+30, rampupCount, (rampupCount+30)/2 )
            JAGlobalLib.LogMsg(msg, testLogFileName, True)

            # generate log to test TracePattern line with timestamp, traceId both in the same line, not a log block
            msg = "TraceId={0:016x} Service1 status=202 test trace line {1}\n".format(traceId, count)
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            
            # generate log to test TraceBlockStart, and TraceBlockEnd sequence
            # here, the traceId is in TraceBlockStart line
            msg = "TraceId={0:016x} Service2 account=1234 Name=JaaduVision test trace line {1}\n".format(traceId, count)
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = " 2nd line of prev trace line {0:016x}\n".format(traceId, count)
            JAGlobalLib.LogMsg(msg, testLogFileName, True, False)

            ## generate log to test TraceBlockStart, TracePattern, TraceBlockEnd sequence
            # here, the traceId is in TracePattern line, data to be masked in 5th line
            msg = "Block1 Service3 test trace line\n"
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = " 2nd line of block status=404\n 3rd line of block \n 4th line of block {0:016x}\n 5th line of block account=1234 Name=JaaduVision \n 6th line of block \n".format(traceId)
            JAGlobalLib.LogMsg(msg, testLogFileName, True, False)

            traceId += count
        elif count % 3 > 0:
            JAGlobalLib.LogMsg('TestMsg Count\n', testLogFileName, True)
    
JAGlobalLib.JAFindModifiedFiles( "{HOSTNAME}Test.py", "JA", 0, 3)            
