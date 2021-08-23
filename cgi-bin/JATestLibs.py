"""
 This script tests library functions 

"""
import JAGlobalLib, sys

print( JAGlobalLib.UTCDateTime() )

print ( JAGlobalLib.JAYamlLoad( 'JAGlobalVars.yml' ) )
print ( JAGlobalLib.JAYamlLoad( '../client/JAGatherLogStats.yml' ) )

import time
currentTimeInSec = time.time() - 36000
print ( JAGlobalLib.JAFindModifiedFiles( "/var/log/apache2/access*", currentTimeInSec, 3 ))
OSType, OSName, OSRelease = JAGlobalLib.JAGetOSInfo( sys.version_info, 3)
print("OSType:{0}, OSName:{1}, OSRelease:{2}".format( OSType, OSName, OSRelease ) )

print("current time:{0}, one min back time:{1}".format( JAGlobalLib.JAGetTime(0), JAGlobalLib.JAGetTime(60)))

print("day of month:{0}".format( JAGlobalLib.JAGetDayOfMonth(0)))

