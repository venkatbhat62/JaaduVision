#!/usr/bin/python3
"""
This script generates test data in JATest.log.YYYYMMDD so that the JAGatherLogStats.py can send the
simulated data to web server. This is to test the functionality of client processing log files and posting to
web server, web script pushing the data to prometheus gateway, prometheus making the data available to 
grafana, grafana presentation showing the data in dashboards

Parameters passed are:
    simulationType - random (default), sawtooth
    debugLevel - 0,1,2,3, default 0

Author: havembha@gmail.com, 2021/08/01

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
parser.add_argument("-d", type=int, help="duratoin in seconds")
parser.add_argument("-s", help="simulator type, random (default), sawtooth")

args = parser.parse_args()
if args.D:
    debugLevel = args.D
if args.d:
    testDurationInSec = args.d
if args.s:
    simulationType = args.s

if debugLevel > 0 :
    print(f'DEBUG-1 Parameters passed simultionType: {simulationType}, testDurationInSec: {testDurationInSec}, debugLevel:{debugLevel}')

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
        print(f'DEBUG-3 simulationType: {simulationType}, sleeping for {sleepTimeInSec}')

    time.sleep( sleepTimeInSec)

    ### log messages to log file
    for count in range( int(sleepTimeInSec / 5) ):
        JAGlobalLib.LogMsg(f'TestMsg Pass\n', testLogFileName, True)
        if count % 2 > 0:
            JAGlobalLib.LogMsg(f'TestMsg Fail\n', testLogFileName, True)
        if count % 3 > 0:
            JAGlobalLib.LogMsg(f'TestMsg Count\n', testLogFileName, True)
