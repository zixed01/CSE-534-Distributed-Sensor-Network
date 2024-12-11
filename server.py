import socket
import threading
import time
import queue
import csv

SINK_COMMAND_PORT = 10000
CLUSTER_COMMAND_PORT = 10001
NODE_DATA_PORT = 10002
SINK_RESPONSE_PORT = 10003
latency_reports = {}
cluster_heads = {}
message_queue = queue.Queue()

node_data = {}
all_nodes = {}
NODE_IP_MAP = {}

# setup phase functions
# function for listening for latency probes or rerun setup requests on the sink
def packet_listener():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', SINK_COMMAND_PORT))
            print(f"Sink listening on port {SINK_COMMAND_PORT}")
            while True:
                data, addr = sock.recvfrom(1024)
                sock.sendto(b"ACK", addr)
                message_queue.put((data, addr))

    except Exception as e:
        print(f"Error while binding or receiving: {e}")

# function for adding latency probes or rerun setup requests to the queue
# for handle_message to process
def packet_processor():
    while True:
        if not message_queue.empty():
            data, addr = message_queue.get()
            handle_message(data, addr)

# handle requests from the nodes (not sensor data)
def handle_message(data, addr):
    message = data.decode()

    if message == "LATENCY_PROBE":
        print(f"Received LATENCY_PROBE from {addr}")
    else:
        try:
            cluster_id, hostname, latency = message.split(":")
            cluster_id = int(cluster_id)

            if cluster_id not in latency_reports:
                latency_reports[cluster_id] = {}

            latency_reports[cluster_id][hostname] = (float(latency),
                addr[0])
            all_nodes[hostname] = addr[0]
            print(f"Received latency report: Cluster {cluster_id}, {hostname}"
                f"-> {float(latency)*1000:.2f}ms")

        except ValueError:
            print(f"Error: receiving latency report from: {addr}: {message}")

# selects cluster heads for each cluster based on latency metrics
def select_cluster_heads():
    for cluster_id, reports in latency_reports.items():
        if reports:
                cluster_heads[cluster_id] = min(reports.items(), key=lambda x:
                    x[1][0])

    return cluster_heads

# report cluster head selection to all nodes
def inform_cluster_heads(cluster_heads):
    print(f"Cluster heads selected: {cluster_heads}")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for cluster_id, cluster_head_info in cluster_heads.items():
            cluster_head_hostname = cluster_head_info[0]
            cluster_head_ip = cluster_head_info[1]
            for hostname, (_, ip) in latency_reports[cluster_id].items():
                message = f"HEAD:{cluster_id}:{cluster_head_hostname}:" \
                    f"{cluster_head_ip}"
                sock.sendto(message.encode(), (ip, CLUSTER_COMMAND_PORT))

# after a RERUN_SETUP is completed, this function informs all nodes of the new
# cluster heads
def inform_nodes_of_new_cluster_heads(cluster_heads):
    print(f"Cluster heads selected: {cluster_heads}")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for cluster_id, cluster_head_info in cluster_heads.items():
            cluster_head_hostname = cluster_head_info[0]
            cluster_head_ip = cluster_head_info[1]
            for hostname, (_, ip) in latency_reports[cluster_id].items():
                message = f"HEAD:{cluster_id}:{cluster_head_hostname}:" \
                    f"{cluster_head_ip}"
                try:
                    sock.sendto(message.encode(), (ip, SINK_RESPONSE_PORT))
                    print(f"Sent cluster head info to {hostname}"
                        f" ({ip}): {message}")
                except Exception as e:
                    print(f"Error: sending cluster head info to"
                        f"{hostname} ({ip}): {e}")

# periodic cluster head selection (hourly for this instance)
def periodic_cluster_head_selection(interval=3600):

    while True:
        time.sleep(interval)
        notify_nodes_to_rerun_setup()
        time.sleep(30)

        print("Reevaluating cluster heads")
        cluster_heads = select_cluster_heads()
        inform_nodes_of_new_cluster_heads(cluster_heads)
        print("Cluster head reevaluation and notification complete.")



# function to notify all nodes to rerun setup
def notify_nodes_to_rerun_setup():
    print("Notifying all nodes to rerun the setup process...")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for hostname, ip in all_nodes.items():
            setup_message = "RERUN_SETUP"
            sock.sendto(setup_message.encode(), (ip, SINK_COMMAND_PORT))
            print(f"Notified {hostname} at {ip} to rerun setup.")

# execute phase functions
# function to receive, print, and store all data received from cluster heads
def handle_aggregated_data(print_interval=30):

    cluster_windows = {}
    cluster_head_ips = {}

    while True:
        cluster_data = {}
        last_print_time = time.time()


        timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
        output_file = f"aggregated_data_{timestamp}.csv"

        with open(output_file, mode='w', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([
                "Cluster", "Node", "DTG", "Latitude", "Longitude", "Air Temp",
                "Precipitation", "Status"
            ])

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('', CLUSTER_COMMAND_PORT))
            print(f"Sink listening for aggregated data on port"
                f" {CLUSTER_COMMAND_PORT}")

            while True:
                sock.settimeout(1)
                try:
                    data, addr = sock.recvfrom(1024)
                    message = data.decode()

                    try:
                        entries = message.split(";")
                        for entry in entries:
                            parts = entry.split(":")

                            if len(parts) < 4:
                                print(f"Error in data from: {addr}: {entry}")
                                continue

                            if parts[0] == "CLUSTER_HEAD":
                                cluster_id = parts[1]
                                cluster_data.setdefault(cluster_id, {})
                                cluster_head_ip = addr[0]
                                cluster_head_ips[cluster_id] = cluster_head_ip
                            elif parts[0] == "DATA":
                                cluster_id = parts[1]
                                node_id = parts[2]
                                timestamp = parts[3]


                                if cluster_id not in cluster_windows:
                                    cycle_start_time = time.strptime(timestamp,
                                        "%Y%m%d%H%M%S")
                                    cluster_windows[cluster_id] = \
                                        cycle_start_time
                                    print(f"Cycle window for cluster"
                                        f" {cluster_id} started at {timestamp}")

                                cycle_start_time = cluster_windows[cluster_id]

                                data_time = time.strptime(timestamp,
                                    "%Y%m%d%H%M%S")


                                data_time_epoch = time.mktime(data_time)
                                cycle_start_epoch = \
                                    time.mktime(cycle_start_time)
                                cycle_end_epoch = cycle_start_epoch + 30 + 5

                                if data_time_epoch < cycle_start_epoch:
                                    print(f"Data for {node_id} from"
                                        f" {cluster_id} dropped due to lateness"
                                        f" (timestamp: {timestamp}).")

                                    if cluster_id in cluster_head_ips:
                                        cluster_head_ip = \
                                            cluster_head_ips[cluster_id]
                                        late_message = f"LATE_DATA:" \
                                            f"{cluster_id}:{node_id}:" \
                                            f"{timestamp}"

                                        sock.sendto(late_message.encode(),
                                            (cluster_head_ip,
                                                CLUSTER_COMMAND_PORT))


                                    cluster_data.setdefault(cluster_id,
                                        {})[node_id] = {
                                        "Status": "Data dropped due to lateness"
                                    }
                                    continue

                                if len(parts) > 4:
                                    data_values = parts[4]
                                else:
                                    data_values = "No data received"

                                if data_values == "No data received":
                                    cluster_data.setdefault(cluster_id,
                                        {})[node_id] = {
                                        "Time": timestamp,
                                        "Status": "Data not received"
                                    }
                                else:
                                    lat, lon, air_temp, precip = \
                                        data_values.split()
                                    cluster_data.setdefault(cluster_id,
                                        {})[node_id] = {
                                        "Time": timestamp,
                                        "Latitude": lat,
                                        "Longitude": lon,
                                        "Air Temp": air_temp,
                                        "Precipitation": precip,
                                        "Status": "Data received"
                                    }
                    except Exception as e:
                        print(f"Malformed entry from {addr}: {message} - {e}")

                except socket.timeout:
                    pass

                current_time = time.time()
                if current_time - last_print_time >= print_interval:
                    current_time_str = time.strftime('%Y-%m-%d %H:%M:%S',
                        time.gmtime())
                    print(f"\nAggregated Data for all Clusters at"
                        f" {current_time_str}:")


                    with open(output_file, mode='a', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)

                        for cluster_id, nodes in cluster_data.items():
                            print(f"\nCluster {cluster_id}")
                            for node_id, data in nodes.items():
                                if data.get("Status") == "Data not received":
                                    print(f"Data for {node_id}:\n"
                                        f"  DTG: {data['Time']}\n"
                                        f"  Data not received")

                                    csv_writer.writerow([
                                        cluster_id, node_id, data["Time"],
                                        "", "", "", "", "Data not received"
                                    ])
                                    continue
                                elif data.get("Status") == \
                                    "Data dropped due to lateness":
                                    print(f"Data for {node_id}:\n"
                                        f"  DTG: {data['Time']}\n"
                                        f"  Data dropped due to lateness")
                                    csv_writer.writerow([
                                        cluster_id, node_id, data["Time"],
                                        "", "", "", "",
                                        "Data dropped due to lateness"
                                    ])
                                    continue
                                else:
                                    print(f"Data for {node_id}:")
                                    print(f"  DTG: {data['Time']}")
                                    print(f"  Lat: {data['Latitude']}"
                                        f" degrees North")
                                    print(f"  Long: {data['Longitude']}"
                                        f" degrees East")
                                    print(f"  Air Temp: {data['Air Temp']}"
                                        f" degrees C")
                                    print(f"  Precipitation: "
                                        f"{data['Precipitation']} mm")

                                    csv_writer.writerow([
                                        cluster_id, node_id, data["Time"],
                                        data["Latitude"], data["Longitude"],
                                        data["Air Temp"], data["Precipitation"],
                                        "Data received"
                                    ])

                    cluster_data.clear()
                    last_print_time = current_time

def main():
    threading.Thread(target=packet_listener, daemon=True).start()
    threading.Thread(target=packet_processor, daemon=True).start()
    time.sleep(30)

    cluster_heads = select_cluster_heads()
    inform_cluster_heads(cluster_heads)

    threading.Thread(target=periodic_cluster_head_selection, args=(3600,),
        daemon=True).start()

    threading.Thread(target=handle_aggregated_data, daemon=True).start()



    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
