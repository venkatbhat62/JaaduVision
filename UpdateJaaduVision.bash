#!/usr/bin/bash

### this script gets project artifacts from github
### use this if git is not available on your server
### it creates cgi-bin, client sub-directories and gets all files from github
### Author: havembha@gmail.com 2021-08-07

mkdir cgi-bin client
wget https://github.com/venkatbhat62/JaaduVision/Installation.txt
wget https://github.com/venkatbhat62/JaaduVision/LICENSE
wget https://github.com/venkatbhat62/JaaduVision/README.md
cd cgi-bin
wget https://github.com/venkatbhat62/JaaduVision/blob/main/cgi-bin/JADataMaskSpec.yml
wget https://github.com/venkatbhat62/JaaduVision/blob/main/cgi-bin/JAGlobalLib.py
wget https://github.com/venkatbhat62/JaaduVision/blob/main/cgi-bin/JAGlobalVars.yml
wget https://github.com/venkatbhat62/JaaduVision/blob/main/cgi-bin/JASaveStats.py
wget https://github.com/venkatbhat62/JaaduVision/blob/main/cgi-bin/JATestLibs.py
wget https://github.com/venkatbhat62/JaaduVision/blob/main/cgi-bin/JAUploadFile.py
# https://github.com/venkatbhat62/JaaduVision/blob/main/cgi-bin/

cd ../client
wget https://github.com/venkatbhat62/JaaduVision/blob/main/client/JAGatherLogStats.py
wget https://github.com/venkatbhat62/JaaduVision/blob/main/client/JAGatherLogStats.yml
wget https://github.com/venkatbhat62/JaaduVision/blob/main/client/JAGatherOSStats.py
wget https://github.com/venkatbhat62/JaaduVision/blob/main/client/JAGatherOSStats.yml
wget https://github.com/venkatbhat62/JaaduVision/blob/main/client/JAGlobalLib.py
wget https://github.com/venkatbhat62/JaaduVision/blob/main/client/JATest.py
# wget https://github.com/venkatbhat62/JaaduVision/blob/main/client/

