#!/bin/bash

# when you run the shell script you need to set the interface and datarate 
INTERFACE=$1       
RATE=$2            

if [ -z "$INTERFACE" ] || [ -z "$RATE" ]; then
    echo "Usage: $0 <interface> <rate>"
    echo "Example: $0 eth0 100mbit"
    exit 1
fi

# clears any existing traffic control policies in place (usually I interrupt the script before running a new one)
clear_tc() {
    tc qdisc del dev "$INTERFACE" root 2>/dev/null
}


clear_tc
tc qdisc add dev "$INTERFACE" root handle 1: tbf rate "$RATE" burst 32kbit latency 400ms
tc qdisc add dev "$INTERFACE" parent 1:1 handle 10: netem delay 100ms

echo "Initial rate limit of $RATE set on $INTERFACE with baseline latency of 100ms."


END_TIME=$((SECONDS + 5400))
while [ $SECONDS -lt $END_TIME ]; do
    # Generate random latency between 10 and 200 ms
    RANDOM_LATENCY=$((10 + RANDOM % 191))
    
    tc qdisc change dev "$INTERFACE" parent 1:1 handle 10: netem delay ${RANDOM_LATENCY}ms
    
    echo "$(date): Applied random latency of ${RANDOM_LATENCY}ms to $INTERFACE"
    
    sleep 30
done

clear_tc
echo "Traffic control settings cleared for $INTERFACE after an hour and a half."

