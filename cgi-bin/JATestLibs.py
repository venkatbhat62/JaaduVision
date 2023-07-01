"""
 This script tests library functions 

"""
import JAGlobalLib, sys

print( JAGlobalLib.UTCDateTime() )

print ( JAGlobalLib.JAYamlLoad( 'JAGlobalVars.yml' ) )
print ( JAGlobalLib.JAYamlLoad( '../client/JAGatherLogStats.yml' ) )

import time
currentTimeInSec = time.time() - 36000
print ( JAGlobalLib.JAFindModifiedFiles( "/var/log/apache2/access*", currentTimeInSec, 3, "hostname", "Linux" ))
OSType, OSName, OSRelease = JAGlobalLib.JAGetOSInfo( sys.version_info, 3)
print("OSType:{0}, OSName:{1}, OSRelease:{2}".format( OSType, OSName, OSRelease ) )

print("current time:{0}, one min back time:{1}".format( JAGlobalLib.JAGetTime(0), JAGlobalLib.JAGetTime(60)))

print("day of month:{0}".format( JAGlobalLib.JAGetDayOfMonth(0)))

print("epochTime:{0}, tzinfo:{1}".format(time.gmtime(0), time.tzname))
print( "time:{0}".format(JAGlobalLib.JAConvertStringTimeToTimeInMicrosec("1970-01-01 00:00:00.500000", "%Y-%m-%d %H:%M:%S.%f" ) ) )
print( "timeZ:{0}".format(JAGlobalLib.JAConvertStringTimeToTimeInMicrosec("2022-06-04 00:00:00.500", "%Y-%m-%d %H:%M:%S.%f" ) ) )
print( "time:{0}".format(JAGlobalLib.JAConvertStringTimeToTimeInMicrosec("1970-01-02T00:00:00.500000", "%Y-%m-%dT%H:%M:%S.%f" ) ) )

print( "time no fraction:{0}".format(JAGlobalLib.JAConvertStringTimeToTimeInMicrosec("1970-01-02T00:00:00", "%Y-%m-%dT%H:%M:%S" ) ) )
print( "time in YYYYMMDD hh:mm:ss.mmmmmm:{0}".format(JAGlobalLib.JAConvertStringTimeToTimeInMicrosec("19700102 00:00:00.500000", "%Y%m%d %H:%M:%S.%f" ) ) )

timeFormat="%Y-%m-%dT%H:%M:%S.%f"
if (timeFormat == '%Y-%m-%dT%H:%M:%S.%f' or timeFormat == '%Y-%m-%d %H:%M:%S.%f'):
    print("match")
else:
    print("nomatch")
