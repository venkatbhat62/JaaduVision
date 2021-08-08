""""
    This module contains global functions used by JadooAudit

    GetGMTTime() - returns string with current GMT time the form YYYY/MM/DD hh:mm:ss.sss

    Author: havembha@gmail.com, 2021-06-28
"""
import datetime
def UTCDateTime():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f%Z")

def UTCDateTimeForFileName():
    return datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")

def UTCDate():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def UTCDateForFileName():
    return datetime.datetime.utcnow().strftime("%Y%m%d")

def UTCTime():
    return datetime.datetime.utcnow().strftime("%H:%M:%S")

def LogMsg(logMsg, fileName, appendDate=True):
    if appendDate == True:
        logFileName = fileName + "." + UTCDateForFileName()
    else:
        logFileName = fileName

    try:
        logFileStream = open( logFileName, 'a')
    except OSError:
        return 0
    else:
        logFileStream.write( UTCDateTime() + " " + logMsg )
        logFileStream.close()
        return 1

