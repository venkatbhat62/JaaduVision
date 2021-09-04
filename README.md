# JaaduVision
 monitor network/site/host performance

Setup on target host whose performance is to be monitored
- Python script to collect OS stats and post to web server – OS stats to be collected can be customed via yml file per component or hosttype.  
- Python script to collect application stats/alarm stats and post to web server. Log file scraping is customized using yml file. One can specify log file name, pass/fail/count patterns to search in regular expression format for each service type. Multiple service types can be specified for single log file. Stats of each service type are posted separately to web server so that further analysis or visualization can be done per service type or combination of service types.
- Stat sampling interval, post interval, web server to post can be customized per environment (like DEV, test, staging, prod each can have separate setup)
- Log Stats collection can be  SKIPed when CPU usage average exceeds max limit over 10 sampling intervals. This is to avoid overloading the host at high CPU usage levels with monitoring tools
- Both OS Stats collection and Log Stats collection scripts run at lowest priority (nice 19) level, thus, using system resources when available. 

<br><br>Server side setup
- Python script to receive stats, store it in CSV format on file system per client host who posted the data and post the data to Prometheus gateway. Plan is to use this CSV data later to derive host to host (or client/server/service) relationship using AI/ML scripts, provide root cause for alarms/failures and automate recovery actions. (This will take more time to develop).
- Prometheus gateway (https://www.metricfire.com/blog/what-is-prometheus-pushgateway/) to receive data from any client, pass that data to Prometheus (https://prometheus.io/docs/introduction/overview/)
- Apache web server to allow execution of cgi-scripts, allow interaction with Grafana, Prometheus, and Prometheus gateway.
- Grafana (https://grafana.com/) to visualize data in time series, histogram format using Prometheus as data source.
- Diagram plugin (https://grafana.com/grafana/plugins/jdbranham-diagram-panel/) to visualize data in network or node view

Preferred Prerequisites
     Python3.8+
<br>Preferred - Import modules in addition to base python 3.8 
  yaml
  requests

cgi-bin/JAGlobalLib.py, client/JAGatherOSStats.py, client/JAGatherLogStats.py were tested on 
   - Ubuntu 20+ with python 3.9 and with yaml, requests modules
   - RedHat 7.x with python 2.7 and without yaml and requests modules

<br><br>Yet to be tested 
   - Windows 10 with python TBD
   - Android tablet Linux TBD
   - Raspberry pi Linux TBD
