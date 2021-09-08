
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
    sys.exit()

startTimeInSec = time.time()
# seed random number generator
seed(1)

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

    ### log messages to log file
    for count in range( int(sleepTimeInSec / 8) ):
        JAGlobalLib.LogMsg('TestMsg Pass\n', testLogFileName, True)
        
        if count % 2 > 0:
            JAGlobalLib.LogMsg('TestMsg Fail\n', testLogFileName, True)
            msg = "leading text key1 {0} dummy1 key2 {1:.2f} dummy2\n".format( sleepTimeInSec, sleepTimeInSec/2)
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
            msg = "tps key1 {0} dummy1 key2 {1:.2f} dummy2\n".format( sleepTimeInSec, sleepTimeInSec/2)
            JAGlobalLib.LogMsg(msg, testLogFileName, True)
        elif count % 3 > 0:
            JAGlobalLib.LogMsg('TestMsg Count\n', testLogFileName, True)
    
            
