#!/usr/bin/python3

""" This script saves the file posted in desired directory under main upload directory.
If the datamasking is opted, it will replace string tokens with replace definitions.
Logs a line per file uploaded along with clientIP, hostName, directoryName, fileSize, and
  fileName on the server

Parameters passed are:
    fileName - mandatory - save the file with this name on web server
    platform - optional - save the file under this sub-directory under main directory
        JAUpload: LocalHostDir[12]/<platformName>
        default - "Unknown" 

    hostName - optional - save the file under this sub-directory under main directory 
        JAUpload: LocalHostDir[12]/[<platformName>]/<hostName>
        default - "Unknown" 

    storeType - local,  replicate,  both, remote
        if local or both, file is stored under JAUploadDirLocal/[<platformName>]/<hostName>
        if replicate or both, file stored under JAUploadDirReplicate/[<platformName>]/<hostName>
        if remote, file is only stored under JAUploadRemoteHost@JAUploadDirRemote/
            platformName and hostName are not used on remote host
        defaults to local

    datamaskFileName - optional - apply this datamask spec on uploaded file contents
        before saving on web servers in replicate area. 
        This comes in to play when storeType is replicate or both. 
        When storeType is local, this parameter has no effect.
        This is used to mask any sensitive data in uploaded file.
        defaults to none (no datamasking done)

  Checks
        if filename has space or special characters, return Error
        if already a file exists with that name on server, 
            and hostName is passed, overwrite the file
            and hostName is NOT passed, return Error
        if file size is greater than JAUploadMaxFileSize, return Error
        if datamaskFileName is passed, and is not present on server, return Error

  returnResult
    Upon successful save, print the fileName, file locations where the file is saved

    Author: havembha@gmail.com, 2021/06/28

"""

import cgi, cgitb, os, sys, re, tempfile
from os import path
import datetime
import yaml
import JAGlobalLib

# 0 - none, 1 to 3 levels, 3 highest
JADebugLevel = 0

# dictionary to store datamask spec 
JADatamaskSpec = {}

### Read datamask config file
### expected format:
### ---
### DMSpec:
###    - Name: Replace Password
###      search: <password>\w+</password>
###      replace: <password>xxxxxxxx</password>
###
def JADatamaskReadConfig(fileName,JADebugLevel):
    returnStatus = False
    global JADatamaskSpec
    tempDatamaskSpec = {}
    try:
        with open(fileName,'r') as file:
            tempDatamaskSpec = yaml.load(file, Loader=yaml.FullLoader)
            # print (tempDatamaskSpec)
            for element in tempDatamaskSpec['DMSpec']:
                name = element.pop('Name')
                JADatamaskSpec[name] = element
                
        returnStatus = True
    except OSError as err:
        JAUploadError( f'ERROR - Can not open datamask file:|{fileName}|' + "OS error: {0}".format(err) + '\n')
    return returnStatus

### if curent line has any of the search string defined in datamask spec,
### replace those strings withe replace strings defined in datamask spec
### return line
def JADatamaskMaskLine(line, JADebugLevel):
    global JADatamaskSpec
    for key, spec in JADatamaskSpec.items():
        search = spec['Search']
        replace = spec['Replace']

        if JADebugLevel > 2:
            print(f'DEBUG - JADatamaskMaskLine() input:|{line}|, search:|{search}|, replace:{replace}|\n')
        line = re.sub(r'{}'.format(search), r'{}'.format(replace),line )

        if JADebugLevel > 2:
            print(f'DEBUG - JADatamaskMaskLine() output:|{line}\n') 
    return line

### start HTML response page
cgitb.enable()
print("Content-Type: text/html;charset=utf-8")
print()

JAUploadStartTime = datetime.datetime.now()

## common function to exit
def JAUploadFileExit(reason):
    print (f'{reason}\n')

    JAUploadEndTime = datetime.datetime.now()
    JAUploadDuration = JAUploadEndTime - JAUploadStartTime
    JAUploadDurationInSec = JAUploadDuration.total_seconds()
    JAGlobalLib.LogMsg(f'{reason}, upload duration:{JAUploadDurationInSec} sec\n', JAUploadLogFileName, True)
    sys.exit()

def JAUploadError(reason):
    print (f'ERROR Could not save the file: {reason}')
    JAUploadFileExit(reason)


### read global parameters 
with open('JAGlobalVars.yml','r') as file:
    JAGlobalVars = yaml.load(file, Loader=yaml.FullLoader)
    JALogDir = JAGlobalVars['JALogDir']
    JAUploadLogFileName = JALogDir + "/" + JAGlobalVars['JAUpload']['LogFileName']
    JAUploadMaxFileSize = int( JAGlobalVars['JAUpload']['MaxFileSize'])
    JAUploadDirLocal = JAGlobalVars['JAUpload']['DirLocal']
    JAUploadDirReplicate = JAGlobalVars['JAUpload']['DirReplicate']
    JAUploadDirRemote = JAGlobalVars['JAUpload']['DirRemote']
    JAUploadRemoteHost = JAGlobalVars['JAUpload']['RemoteHost']
    JAUploadDefaultDatamaskFileName = JAGlobalVars['JAUpload']['DefaultDatamaskFileName']

## start with empty error string
errorString = ''

## parse arguments passed, assign default value if param not passed
arguments =  cgi.FieldStorage()
if 'fileName' not in arguments:
    errorString = 'file name not passed' 
    JAUploadError( errorString )
else:
    fileName = arguments['fileName'].value
    # Allow letters, digits, periods, underscores, dashes
    # Convert anything else to an underscore
    fileName = re.sub(r'[^\w.-]', '_', fileName)

if 'platform' in arguments:
    platform = arguments['platform'].value
else:
    platform = 'Unknown'

if 'hostName' in arguments:
    hostName = arguments['hostName'].value
else:
    hostName = 'Unknown'

if 'storeType' in arguments:
    storeType = arguments['storeType'].value
else:
    storeType = 'local'

if 'datamaskFileName' in arguments:
    datamaskFileName = arguments['datamaskFileName'].value

    if datamaskFileName == 'NONE':
        datamaskFileName = ''
    else:
        if not path.exists( datamaskFileName ):
            errorString = 'datamaskFileName:' + datamaskFileName + " does not exist"
            JAUploadError( errorString )
else:
    datamaskFileName = ''

if 'JADebugLevel' in arguments:
    JADebugLevel = int(arguments['JADebugLevel'].value)

if JADebugLevel > 0 :
    print (f'Parameters passed:fileName:{fileName}, platform:{platform}, hostName:{hostName}, datamaskFileName:{datamaskFileName}, storeType:{storeType}')

### make platformHostName with platform and hostName
# this will be added to filename later
if platform != '':
    platformHostName = platform + "/"
if hostName != '':
    platformHostName = platformHostName + hostName 

serverFileNameLocal = serverFileNameReplicate = serverFileNameRemote = uploadDirLocal = uploadDirReplicate = uploadDirRemote = ''

### if directory is not present, create it
if storeType == 'local' or storeType == 'both':
    uploadDirLocal = JAUploadDirLocal + "/" + platformHostName
    serverFileNameLocal = uploadDirLocal + "/" + fileName
    if platform != '':
        if not path.exists( JAUploadDirLocal + "/" + platform ): 
            os.mkdir( JAUploadDirLocal + "/" + platform )
    if platformHostName != '':
        if not path.exists( JAUploadDirLocal + "/" + platformHostName ):
            os.mkdir( JAUploadDirLocal + "/" + platformHostName)

if storeType == 'replicate' or storeType == 'both':
    if JAUploadDirReplicate == 'NONE':
        JAUploadError(f'ERROR - DirReplicate is not defined in JAGlobalVars.yml, "replication" option not supported')

    uploadDirReplicate = JAUploadDirReplicate + "/" + platformHostName
    serverFileNameReplicate = uploadDirReplicate + "/" + fileName
    if platform != '':
        if not path.exists( JAUploadDirReplicate + "/" + platform ): 
            os.mkdir( JAUploadDirReplicate + "/" + platform )
    if platformHostName != '':
        if not path.exists( JAUploadDirReplicate + "/" + platformHostName ):
            os.mkdir( JAUploadDirReplicate + "/" + platformHostName)

if storeType == 'remote':
    if JAUploadDirRemote == 'NONE':
        JAUploadError(f'ERROR - DirRemote is not defined in JAGlobalVars.yml, "remote" option not supported')

    uploadDirRemote = JAUploadDirRemote + "/" 
    serverFileNameRemote = uploadDirRemote + "/" + fileName

if JADebugLevel > 0:
    print (f'serverFileNameLocal:|{serverFileNameLocal}|, serverFileNameReplicate:|{serverFileNameReplicate}|, serverFileNameRemote:|{serverFileNameRemote}\n')

if path.exists( serverFileNameLocal ) :
    ### current file name already exists.
    if hostName == '' : 
        ## since directory name was not passed and file is being stored at top level
        ## return Error, don't want to overwrite existing file
        JAUploadError( f'ERROR - {serverFileNameLocal} exists on server, pass hostName along with fileName so that file can be saved under specific directory and avoid overwriting file at global level\n')
    else:
        ### since directory name is passed, it is OK to overwrite the file
        ### remove old file so that new file can be stored 
        os.remove(serverFileNameLocal) 
        if JADebugLevel > 0 : 
            print (f'Removed existing file |{serverFileNameLocal}| on server\n')

if path.exists( serverFileNameReplicate ) :
    ### current file name already exists.
    if hostName == '' : 
        ## since directory name was not passed and file is being stored at top level
        ## return Error, don't want to overwrite existing file
        JAUploadError( f'ERROR - {serverFileNameReplicate} exists on server, pass hostName along with fileName so that file can be saved under specific directory and avoid overwriting file at global level\n')
    else:
        ### since directory name is passed, it is OK to overwrite the file
        ### remove old file so that new file can be stored 
        os.remove(serverFileNameReplicate) 
        if JADebugLevel > 0 : 
            print (f'Removed existing file |{serverFileNameReplicate}| on server\n')
# get REMOTE_ADDR
clientIP = os.environ['REMOTE_ADDR']
contentType = os.environ['CONTENT_TYPE']

# get file size posted
contentLength = int(os.environ['CONTENT_LENGTH'])
if contentLength > JAUploadMaxFileSize :
    JAUploadError( f'ERROR - File size {contentLength} is greater than max size {JAUploadMaxFileSize} supported')

# make a temp file name to save the content
tempFileName1 = tempfile._get_default_tempdir() + "/" + next(tempfile._get_candidate_names()) + "_" + fileName

fileItem = arguments['file']
try:
    fpTemp1 = open(tempFileName1, "wb")
    while True:
        chunk = fileItem.file.read(100000)
        if not chunk:
            break
        fpTemp1.write(chunk)
    fpTemp1.close()
except OSError:
    JAUploadError( f'ERROR - Can not write to a temp file {tempFileName1}\n')

### fileName is not of binary type, apply data mask
searchResult = re.search( '.tar|.gz|.exe|.zip|.gzip', fileName)

if (searchResult == None) and ( datamaskFileName != '') :
    tempFileName2 = tempfile._get_default_tempdir() + "/" + next(tempfile._get_candidate_names()) + "_" + fileName
    try:
        fpTemp1 = open(tempFileName1, "r")
        fpTemp2 = open(tempFileName2, "w")
        JADatamaskReadConfig( datamaskFileName, JADebugLevel)
        if JADebugLevel > 1:
            print(f'DEBUG Creating datamasked file:|{tempFileName2}|\n')

        while True:
            line = fpTemp1.readline()
            if not line:
                break
            ### NOW apply datamask for current line
            fpTemp2.write( JADatamaskMaskLine( line, JADebugLevel))

        fpTemp1.close()
        fpTemp2.close()

        ### now make tempFileName2 as tempFileName1 so that all future file copy is
        ###   done with masked file
        tempFileName1 = tempFileName2

    except OSError as err:
        JAUploadError( f'ERROR - Could not apply datamask on file {tempFileName1}\n')

returnResult = f'INFO - Saved {fileName} uploaded from clientIP: {clientIP} hostName: {hostName} at '

import shutil
### now copy tempFileName as other file names 
if serverFileNameLocal != '':
    try:
        shutil.copyfile(tempFileName1, serverFileNameLocal )
        returnResult += serverFileNameLocal + " "
    except:
        JAUploadError( f'ERROR - Can not write to a file {serverFileNameLocal}\n')

if serverFileNameReplicate != '':
    try:
        shutil.copyfile(tempFileName1, serverFileNameReplicate )
        returnResult += serverFileNameReplicate + " "
    except:
        JAUploadError( f'ERROR - Can not write to a file {serverFileNameReplicate}\n')

if serverFileNameRemote != '':
    try:
        os.system(f'scp {tempFileName1} {JAUploadRemoteHost}@{serverFileNameRemote}' )
        returnResult += serverFileNameRemote
    except:
        JAUploadError( f'ERROR - Can not scp file {serverFileNameRemote} to {JAUploadRemoteHost}\n')

JAUploadFileExit(returnResult )
