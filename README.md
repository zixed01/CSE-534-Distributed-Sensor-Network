# CSE-534-Distributed-Sensor

## Environment Setup
<p> Upload all the Jupyter Notebook, python files, shell scripts, and datasets into your Jupyter Hub environment. Reserve resources and setup your slice with Project.ipynb </p>

<p> Once your Jupyter environment is setup, transfer client.py, client-dynamic.py, random_latency.sh, along with the specific dataset for your node to all 12 nodes </p>

<p> Dataset files are organized as follows: </p>

> dataset-XX#.txt

<p> where XX# corresponds to the hostname of your node (i.e. NE1). These datasets were pulled from the NOAA USCRN (https://journals.ametsoc.org/view/journals/bams/94/4/bams-d-12-00170.1.xml) (Link to the datasets themselves: https://www.ncei.noaa.gov/access/crn/qcdatasets.html) </p>

<p> Transfer server.py, server-5min.py, server-dynamic.py, and random_latency_sink.sh to your sink node </p>

## Experiment Run

<p> Prior to running the experiment, run the shell scripts for induced additional latency on the nodes by using the following command </p>

<p> Sink </p>

> sudo bash random_latency_sink.sh enp7s0 5mbit

<p> nodes </p>
> sudo bash random_latency.sh enp7s0 1mbit

<p> where the first argument (i.e. enp7s0) is the interface you want to invoke tc on and the second argument (i.e. 1mbit) is the datarate you want to set. The interface may be different for your environment. Additionally, I used tmux to run the shell script in a separate session to then run the python files on my main SSH session </p>

<p> Then for the first experiment: </p>

<p> Sink </p>
> python3 server.py

<p> nodes </p>
> python3 client.py

<p> Second experiment: </p>

<p> Sink </p>
> python3 server-5min.py

<p> nodes </p>
> python3 client.py

<p> Third experiment: </p>

<p> Sink </p>
> python3 server-dynamic.py

<p> nodes </p>
> python3 client-dynamic.py

<p> Results (recorded output of the sink) will be stored in the /home/ubuntu directory with the following naming convention: </p>

> aggregated_data_YYYYMMDDHHmmSS.csv

<p> And for the dynamic iteration, the sink will also record the cluster head elections in the file: </p>

> ch_releection_YYYYMMDDHHmmSS.csv
