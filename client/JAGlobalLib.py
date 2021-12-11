""""
    This module contains global functions used by JadooAudit

    GetGMTTime() - returns string with current GMT time the form YYYY/MM/DD hh:mm:ss.sss
    JAYamlLoad(fileName) - reads the yaml file, returns data in dictionary

    Author: havembha@gmail.com, 2021-06-28
"""
import datetime, platform, re, sys, os

JACPUUsageFileName = 'JACPUUsage.data'

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

def JAGetTime( deltaSeconds ):
    tempTime = datetime.datetime.now()
    deltaTime = datetime.timedelta(seconds=deltaSeconds)
    newTime = tempTime - deltaTime
    return newTime.strftime("%H:%M:%S")

def JAGetDayOfMonth( deltaSeconds ):
    tempTime = datetime.datetime.now()
    deltaTime = datetime.timedelta(seconds=deltaSeconds)
    newTime = tempTime - deltaTime
    newTimeString = newTime.strftime("%d")
    return newTimeString 

def LogMsg(logMsg, fileName, appendDate=True):
    if appendDate == True:
        logFileName = "{0}.{1}".format( fileName, UTCDateForFileName())
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

"""
Basic function to read config file in yaml format
Use this on host without python 3 or where yaml is not available

"""
def JAYamlLoad(fileName ):
    from collections import defaultdict
    import re
    yamlData = defaultdict(dict)
    paramNameAtDepth = {0: '', 1: '', 2: '', 3:'', 4: ''}
    leadingSpacesAtDepth = {0: 0, 1: None, 2: None, 3: None, 4: None}
    prevLeadingSpaces = 0
    currentDepth = 0
    currentDepthKeyValuePairs = defaultdict(dict)

    try:
        with open(fileName, "r") as file:
            depth = 1

            while True:
                tempLine =  file.readline()
                if not tempLine:
                    break
                ### SKIP comment line
                if re.match(r'\s*#', tempLine):
                    continue

                tempLine = tempLine.rstrip("\n")
                if re.match("---", tempLine) :
                    continue
                if len(tempLine) == 0:
                    continue
                ### remove leading and trailing spaces, newline
                lstripLine = tempLine.lstrip()
                if len(lstripLine) == 0:
                    continue

                ## separate param name and value, split to two parts, the value itself may have ':'
                params = lstripLine.split(':', 1)
                ## remove leading space from value field
                params[1] = params[1].lstrip()

                # based on leading spaces, determine depth
                leadingSpaces = len(tempLine)-len(lstripLine)
                if leadingSpaces == prevLeadingSpaces:

                    if leadingSpaces == 0:
                        if params[1] == None or len(params[1]) == 0 :
                            ### if value does not exist, this is the start of parent/child definition
                            paramNameAtDepth[currentDepth+1] = params[0]

                        else:
                            ### top layer, assign the key, value pair as is to yamlData
                            yamlData[params[0]] = params[1]
                    else:
                        ### store key, value pair with current depth dictionary
                        currentDepthKeyValuePairs[params[0]] = params[1]

                    leadingSpacesAtDepth[currentDepth+1] = leadingSpaces

                elif leadingSpaces < prevLeadingSpaces:
                    ### store key, value pair of prev depth 
                    for key, values in currentDepthKeyValuePairs.items():
                        if currentDepth == 1:
                            if paramNameAtDepth[1] not in yamlData.keys() :
                                yamlData[ paramNameAtDepth[1]] = {}
                            
                            yamlData[ paramNameAtDepth[1] ][key] = values

                        elif currentDepth == 2:
                            if paramNameAtDepth[1] not in yamlData.keys() :
                                yamlData[ paramNameAtDepth[1]] = {}
                            if paramNameAtDepth[2] not in yamlData[paramNameAtDepth[1]].keys() :
                                yamlData[ paramNameAtDepth[1]][paramNameAtDepth[2]] = {}

                            yamlData[paramNameAtDepth[1]][paramNameAtDepth[2]][key] = values
                        elif currentDepth == 3:
                            if paramNameAtDepth[1] not in yamlData.keys() :
                                yamlData[ paramNameAtDepth[1]] = {}
                            if paramNameAtDepth[2] not in yamlData[paramNameAtDepth[1]].keys() :
                                yamlData[ paramNameAtDepth[1]][paramNameAtDepth[2]] = {}
                            if paramNameAtDepth[3] not in yamlData[paramNameAtDepth[1]][paramNameAtDepth[2]].keys() :
                                yamlData[ paramNameAtDepth[1]][paramNameAtDepth[2]][paramNameAtDepth[3]] = {}
                            yamlData[paramNameAtDepth[1]][paramNameAtDepth[2]][paramNameAtDepth[3]][key] = values

                    currentDepthKeyValuePairs = defaultdict(dict)
                    
                    if leadingSpacesAtDepth[currentDepth-1] == leadingSpaces:
                        currentDepth -= 1
                    elif leadingSpacesAtDepth[currentDepth-2] == leadingSpaces:
                        currentDepth -= 2
                    elif leadingSpacesAtDepth[currentDepth-3] == leadingSpaces:
                        currentDepth -= 3
                    prevLeadingSpaces = leadingSpaces

                    if params[1] == None or len(params[1]) == 0 :
                        ### if value does not exist, this is the start of parent/child definition
                        paramNameAtDepth[currentDepth+1] = params[0]
                elif leadingSpaces > prevLeadingSpaces:
                    leadingSpacesAtDepth[currentDepth+1] = leadingSpaces
                    currentDepth += 1
                    prevLeadingSpaces = leadingSpaces
                    if params[1] == None or len(params[1]) == 0 :
                        ### if value does not exist, this is the start of parent/child definition
                        paramNameAtDepth[currentDepth+1] = params[0]
                    else:
                        ### save current key, value 
                        currentDepthKeyValuePairs[params[0]] = params[1]

            for key, values in currentDepthKeyValuePairs.items():
                if currentDepth == 1:
                    if paramNameAtDepth[1] not in yamlData.keys() :
                        yamlData[ paramNameAtDepth[1]] = {}
                            
                    yamlData[ paramNameAtDepth[1] ][key] = values

                elif currentDepth == 2:
                    if paramNameAtDepth[1] not in yamlData.keys() :
                        yamlData[ paramNameAtDepth[1]] = {}
                    if paramNameAtDepth[2] not in yamlData[paramNameAtDepth[1]].keys() :
                        yamlData[ paramNameAtDepth[1]][paramNameAtDepth[2]] = {}

                    yamlData[paramNameAtDepth[1]][paramNameAtDepth[2]][key] = values
                elif currentDepth == 3:
                    if paramNameAtDepth[1] not in yamlData.keys() :
                        yamlData[ paramNameAtDepth[1]] = {}
                    if paramNameAtDepth[2] not in yamlData[paramNameAtDepth[1]].keys() :
                        yamlData[ paramNameAtDepth[1]][paramNameAtDepth[2]] = {}
                    if paramNameAtDepth[3] not in yamlData[paramNameAtDepth[1]][paramNameAtDepth[2]].keys() :
                        yamlData[ paramNameAtDepth[1]][paramNameAtDepth[2]][paramNameAtDepth[3]] = {}
                    yamlData[paramNameAtDepth[1]][paramNameAtDepth[2]][paramNameAtDepth[3]][key] = values
            file.close()
            return yamlData

    except OSError as err:
        print('ERROR Can not read file:|' + fileName + '|, ' + "OS error: {0}".format(err) + '\n')
        return yamlData

import os

def JAFindModifiedFiles(fileName, sinceTimeInSec, debugLevel, thisHostName):
    """
        This function returns file names in a directory that are modified since given GMT time in seconds
        if sinceTimeInSec is 0, latest file is picked up regardless of modified time
        Can be used instead of find command
    """
    head_tail = os.path.split( fileName )
    ### if no path specified, use ./ (current working directory)
    if head_tail[0] == '' or head_tail[0] == None:
        myDirPath = './'
    else:
        myDirPath = head_tail[0]

    fileNameWithoutPath = head_tail[1]

    ### if fileName has variable {HOSTNAME}, replace that with current short hostname
    if re.search(r'{HOSTNAME}', fileNameWithoutPath) != None:
        fileNameWithoutPath = re.sub(r'{HOSTNAME}', thisHostName, fileNameWithoutPath)

    if debugLevel > 1 :
        print('DEBUG-2 JAFileFilesModified() filePath:{0}, fileName: {1}'.format( myDirPath, fileNameWithoutPath))

    import fnmatch
    import glob

    ### return buffer
    returnFileNames = []
    fileNames = {}

    try:
        ### get all file names in desired directory with matching file spec
        for file in glob.glob(myDirPath + "/" + fileNameWithoutPath):
        
            if debugLevel > 2 :
                print('DEBUG-3 JAFileFilesModified() fileName: {0}, match to desired fileNamePattern: {1}'.format(file, fileNameWithoutPath) )

            ### now check the file modified time, if greater than or equal to passed time, save the file name
            fileModifiedTime = os.path.getmtime ( file )
            if fileModifiedTime >= sinceTimeInSec :
                fileNames[ fileModifiedTime ] = file 
                if debugLevel > 2 :
                    print('DEBUG-3 JAFileFilesModified() fileName: {0}, modified time: {1}, later than desired time: {2}'.format( file, fileModifiedTime, sinceTimeInSec) )
    except OSError as err:
        errorMsg = "ERROR JAFileFilesModified() Not able to find files in fileName: {0}, error:{1}".format( myDirPath, err)
        print( errorMsg)
        
    sortedFileNames = []
    for fileModifiedTime, fileName in sorted ( fileNames.items() ):
        sortedFileNames.append( fileName )

    if debugLevel > 0 :
        print('DEBUG-1 JAFileFilesModified() modified files in:{0}, since gmtTimeInSec:{1}, fileNames:{2}'.format( fileName, sinceTimeInSec, sortedFileNames) )

    ### if sinceTimeInSec is zero, pick up latest file only
    if sinceTimeInSec == 0:
        if len(sortedFileNames) > 0:
            ### return single file as list
            return [sortedFileNames[-1]]
    
    return sortedFileNames

def JAGetOSInfo(pythonVersion, debugLevel):
    """
    Returns 
        OSType like Linux, Windows
        OSName like rhel for Redhat Linux, ubuntu for Ubuntu, Windows for Windows
        OSVersion like
            7 (for RH7.x), 8 (for RH8.x) for Redhat release
            20 (for Ubuntu)
            10, 11 for Windows

    """
    OSType = platform.system()
    if OSType == 'Linux' :
        try:
            with open("/etc/os-release", "r") as file:
                while True:
                    tempLine = file.readline()
                    if not tempLine:
                        break
                    if len(tempLine)<5:
                        continue
                    tempLine = re.sub('\n$','',tempLine)

                    if re.match(r'ID=', tempLine) != None:
                        dummy, OSName = re.split(r'ID=', tempLine)

                        ### remove double quote around the value
                        OSName = re.sub('"','',OSName)

                    elif re.match(r'VERSION_ID',tempLine) != None:
                        dummy,tempOSVersion = re.split(r'VERSION_ID=', tempLine)
                file.close()
        except:
            print("ERROR JAGetOSInfo() Can't read file: /etc/os-release")
            tempOSReease = ''

    elif OSType == 'Windows' :
        if pythonVersion >= (3,7) :
            tempOSVersion = platform.version()
        OSName = OSType

    ### extract major release id from string like x.y.z
    ### windows 10.0.19042
    ### RH7.x - 3.10.z, RH8.x - 4.18.z
    ### Ubuntu - 5.10.z
    OSVersion = re.search(r'\d+', tempOSVersion).group()
    if debugLevel > 0 :
        print("DEBUG-1 JAGetOSInfo() OSType:{0}, OSName:{1}, OSVersion:{2}".format(OSType, OSName, OSVersion) )

    return OSType, OSName, OSVersion
     

def JAGetOSType():
    """
        Returns values like Linux, Windows
    """
    return platform.system()

def JAWriteCPUUsageHistory( CPUUsage, logFileName=None, debugLevel=0):
    """
    Write CPU usage data to given file name
    Keep 10 sample values

    First line has the average value of max 10 samples 
    Rest of the lines have values of 10 samples, current CPUUsage passed as last line

    Returns True up on success, False if file could not be opened
    """
    historyCPUUsage, average = JAReadCPUUsageHistory() 
    if historyCPUUsage == None:
        ### first time, start with empty list
        historyCPUUsage = []
    else:
        if len( historyCPUUsage ) == 10:
            ### history has 10 samples, drop the oldest sample
            historyCPUUsage.pop(0)

    ### append current CPU Usage to the list
    historyCPUUsage.append( float(CPUUsage) )
    average = sum(historyCPUUsage) / len( historyCPUUsage)

    try:
        with open( JACPUUsageFileName, "w") as file:
            file.write( '{:.2f}\n'.format( average) )
            for value in historyCPUUsage:
                file.write('{:.2f}\n'.format( value ))
            file.close()
            return True

    except OSError as err:
        errorMsg = 'ERROR - JAWriteCPUUsageStats() Can not open file: {0} to save CPU usage info, error:{1}\n'.format( JACPUUsageFileName, err)
        print(errorMsg)
        if logFileName != None:
            LogMsg( errorMsg, logFileName, True)
        return False

def JAReadCPUUsageHistory( logFileName=None, debugLevel=0):
    """
    Read CPU usage data from a file
    Return CPUUsage values in list form, return avarge value separtely
    Return None if file could not be read

    """
    try:
        if os.path.exists( JACPUUsageFileName ) == False:
            return [0], 0
        with open( JACPUUsageFileName, "r") as file:
            tempLine = file.readline().strip()
            if len(tempLine) > 0 :
                average = float( tempLine )
                CPUUsage = []
                while True:
                    tempLine = file.readline()
                    if not tempLine:
                        break
                    CPUUsage.append( float( tempLine.strip() ) )
                file.close()
                return CPUUsage, average 
            else:
                return [0], 0
    except OSError as err:
        errorMsg = 'ERROR - JAReadCPUUsageStats() Can not open file: {0} to read CPU usage info, error:{1}\n'.format( JACPUUsageFileName, err)
        print(errorMsg)
        if logFileName != None:
            LogMsg( errorMsg, logFileName, True)
        return [0], 0

def JAGetAverageCPUUsage( ):
    tempCPUUsage, average = JAReadCPUUsageHistory()
    return average

def JAWriteTimeStamp(fileName, currentTime=None):
    """
    This function writes current time to given filename
    If currentTime is not passed, current time is taken and written to the file
    """
    import time
    if currentTime == None:
        currentTime = time.time()
    
    try:
        with open (fileName, "w") as file:
            file.write( '{:.2f}\n'.format( currentTime) )
            file.close()
            return True

    except OSError as err:
        errorMsg = 'ERROR - JAWriteTimeStamp() Can not open file: {0} to save current time, error:{1}\n'.format( fileName, err)
        print(errorMsg)
        return False

def JAReadTimeStamp( fileName):
    """
    This function reads the time stamp from a given file
    """
    try:
        if os.path.exists(fileName) == False:
            return 0
        with open (fileName, "r") as file:
            prevTime = float( file.readline().strip() )
            file.close()
            return prevTime

    except OSError as err:
        errorMsg = 'INFO - JAReadTimeStamp() Can not open file: {0} to save current time, error:{1}\n'.format( fileName, err)
        print(errorMsg)
        return 0

def JAGetUptime(OSType):
    """
    returns uptime in number of seconds
    if can't be computed, returns 0
    """
    if OSType == 'Linux':
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
    elif OSType == 'Windows':
        uptime_seconds = 0
    else:
         uptime_seconds = 0
    return uptime_seconds