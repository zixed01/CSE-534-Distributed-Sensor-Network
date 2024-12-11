import time
import socket
import statistics
import threading
import queue

SINK_IP = "10.133.137.3"
SINK_COMMAND_PORT = 10000
CLUSTER_COMMAND_PORT = 10001
NODE_DATA_PORT = 10002
SINK_RESPONSE_PORT = 10003
LATENCY_PROBE_COUNT = 5
DATA_INTERVAL = 30
HOSTNAME = ""
AGGREGATED_DATA = []
KNOWN_SENSORS = set()
SENSOR_DATA_RECEIVED = set()
NODE_IP_MAP = {}
SINK_OFFSET = 0
SENT_DATA_STATUS = False
SENSOR_LOCATION = {}
DATASET_FILE = []
listeners_ready = threading.Event()
stop_listening_flag = threading.Event()
CURRENT_CLUSTER_HEAD_IP = ""
command_queue = queue.Queue()
AVG_RTT = 0


# node setup functions
# function to identify the cluster (not very scalable at this instance)
def identify_cluster():
    global HOSTNAME

    HOSTNAME = socket.gethostname()
    if HOSTNAME.startswith("NE"):
        cluster_id = 1
        print(f"Cluster: {cluster_id}")
    elif HOSTNAME.startswith("SE"):
        cluster_id = 2
        print(f"Cluster: {cluster_id}")
    elif HOSTNAME.startswith("SW"):
        cluster_id = 3
        print(f"Cluster: {cluster_id}")
    else:
        print("Sensor node not in scope")
        quit()

    return cluster_id

# opens the dataset file for each node and grabs the first 240 lines
# this was chosen so the program does not have to keep the entire file open
# for the runtime of the program
def get_dataset_file():
    global DATASET_FILE

    if not DATASET_FILE:
        dataset_file = f"dataset-{HOSTNAME}.txt"
        print(f"Using dataset file: {dataset_file}")
        try:
            with open(dataset_file, 'r') as file:
                dataset_entries = file.readlines()[:240]
            print(f"Loaded {len(dataset_entries)}"
                f" entries from the dataset file.")

        except FileNotFoundError:
            print(f"Error: {dataset_file} not found.")

        except Exception as e:
            print(f"Error opening dataset: {e}")

    return dataset_entries

# sends five latency probes to the sink to calculate the average round-trip
# time (RTT)
def calculate_latency():
    global AVG_RTT

    rtts = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(2)
        for _ in range(LATENCY_PROBE_COUNT):
            try:
                start_time = time.time()
                sock.sendto(b"LATENCY_PROBE", (SINK_IP, SINK_COMMAND_PORT))
                sock.recvfrom(1024)
                rtts.append(time.time() - start_time)

            except socket.timeout:
                print("Latency probe timed out")

        if rtts:
            AVG_RTT = statistics.mean(rtts)

        else:
            AVG_RTT = float('inf')

# sends the average RTT from node to sink to the sink to select each cluster's
# cluster head
def send_latency_report():

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        latency_report = f"{CLUSTER_ID}:{HOSTNAME}:{AVG_RTT}"
        sock.sendto(latency_report.encode(), (SINK_IP, SINK_COMMAND_PORT))
        print("Reported latency to sink")

# after the sink selects the cluster heads and transmits the cluster head info
# this function checks the cluster head info and returns the hostname of the CH
def handle_cluster_head_message(message):
    global CURRENT_CLUSTER_HEAD_IP

    try:
        parts = message.split(":")
        if len(parts) == 4 and parts[0] == "HEAD":
            cluster_head_hostname = parts[2]
            CURRENT_CLUSTER_HEAD_IP = parts[3].split(",")[-1].strip(" ')")
            print(f"Cluster head info: Hostname={cluster_head_hostname},"
                f"IP={CURRENT_CLUSTER_HEAD_IP}")
        else:
            raise ValueError(f"Error with cluster head info: {head_info}")

        return cluster_head_hostname

    except Exception as e:
        print(f"Error: cluster head info: {e}")
        return None, None

# this function calls the calculate_latency and send_latency_report functions
# as part of the setup, once the cluster head info is received by the node
# this function calls the appropriate listeners based on its role
def run_setup():
    global IS_CLUSTER_HEAD

    calculate_latency()
    print(f"RTT to sink: {float(AVG_RTT)*1000:.2f}ms")

    send_latency_report()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('', CLUSTER_COMMAND_PORT))
        print("Waiting to receive cluster head info")
        data, _ = sock.recvfrom(1024)
        cluster_head_hostname = handle_cluster_head_message(data.decode())
        print(f"Cluster head is {cluster_head_hostname}: "
            f"{CURRENT_CLUSTER_HEAD_IP}")

    SENT_DATA_STATUS = False

    if HOSTNAME == cluster_head_hostname:
        print("This node is the cluster head.")
        start_sink_listening()
        cluster_head_main()

    else:
        print("This node is a regular sensor.")
        start_sink_listening()
        start_listening_node()
        send_dataset_lines()

# this function joins any running thread on the node when a RERUN_SETUP
# notification is received. Then it calls the calculate_latency and
# send_latency_report functions as part of the rerun setup, once the new cluster
# head info is received by the node this function calls the appropriate
# listeners based on its role
def rerun_setup():
    global IS_CLUSTER_HEAD, SENT_DATA_STATUS, DATASET_FILE
    global AGGREGATED_DATA, SENSOR_DATA_RECEIVED, stop_listening_flag

    print("RERUN_SETUP notification received")
    stop_listening_flag.set()
    listeners_ready.clear()
    time.sleep(1)

    for thread in threading.enumerate():
        if thread.name in {"cluster_listener_thread",
            "node_data_listener_thread", "sink_listener_thread"}:
                thread.join()

    print("All listener threads stopped, now clearing state.")

    AGGREGATED_DATA.clear()
    SENSOR_DATA_RECEIVED.clear()
    SENT_DATA_STATUS = False
    stop_listening_flag.clear()

    calculate_latency()
    print(f"RTT to sink: {float(AVG_RTT)*1000:.2f}ms")
    send_latency_report()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('', SINK_RESPONSE_PORT))

        print("Waiting for new cluster head info")
        data, _ = sock.recvfrom(1024)
        cluster_head_hostname = handle_cluster_head_message(data.decode())
        print(f"New cluster head: {cluster_head_hostname}: "
            f" {CURRENT_CLUSTER_HEAD_IP}")

    if HOSTNAME == cluster_head_hostname:
        print("This node is now the cluster head.")
        start_sink_listening()
        cluster_head_main()
    else:
        print("This node is now a regular sensor.")
        start_sink_listening()
        start_listening_node()
        send_dataset_lines()

# spins up the sink_listener_thread to listen for commands from the sink
# (all nodes)
def start_sink_listening():
    print("Starting sink listener")

    if not any(thread.name == "sink_listener_thread" for thread
        in threading.enumerate()):
        sink_listener_thread = threading.Thread(target=listen_for_sink_commands,
            daemon=True, name="sink_listener_thread")
        sink_listener_thread.start()
        listeners_ready.set()

    else:
        print("Sink listener is already running")

# spins up the cluster_listener_thread to listen for commands from the CH
# (regular nodes)
def start_listening_node():

    cluster_listener_thread = \
        threading.Thread(target=listen_for_cluster_commands, daemon=True,
        name="cluster_listener_thread")
    cluster_listener_thread.start()

    listeners_ready.wait()

# spins up the node_data_listener_thread to listen to data from the sensor
# nodes in the cluster (cluster head)
def cluster_head_main():
    print("Starting cluster head processes")
    listener_thread = threading.Thread(target=listen_for_node_data,
        daemon=True, name="node_data_listener_thread")
    listener_thread.start()

    send_aggregated_data_to_sink()

# Execute phase steps for nodes
# send weather data to cluster head
def send_data_to_cluster_head(data):
    global SENT_DATA_STATUS

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.sendto(data.encode(), (CURRENT_CLUSTER_HEAD_IP, NODE_DATA_PORT))
        print(f"Sent data to cluster head {CURRENT_CLUSTER_HEAD_IP}")
        SENT_DATA_STATUS = True

# grabs next line of weather data from the dataset
def send_dataset_lines():
    global SENT_DATA_STATUS, DATASET_FILE

    while True:
        start_time = time.time()
        while time.time() - start_time < DATA_INTERVAL:
            try:
                command = command_queue.get(timeout=0.5)

                if command == "RERUN_SETUP":
                    print("RERUN_SETUP command received from the sink")
                    rerun_setup()
                    return

            except queue.Empty:
                pass

            time.sleep(0.1)

        try:
            if not SENT_DATA_STATUS:
                for line in DATASET_FILE:
                    line = line.strip()
                    if line:
                        timestamp_str = time.strftime("%Y%m%d%H%M%S",
                            time.gmtime(time.time()))
                        timestamped_data = f'DATA:{CLUSTER_ID}:' \
                            f'{HOSTNAME}:{timestamp_str}:{line}'
                        send_data_to_cluster_head(timestamped_data)
                        SENT_DATA_STATUS = True
                    break

            else:
                print(f"{HOSTNAME}: data already sent this cycle")

        except Exception as e:
            print(f"Error: sending data: {e}")

        SENT_DATA_STATUS = False

# when a late data message is received, identified sensor strips and sends the
# next line of data to the CH
def send_next_line():
    global DATASET_FILE, SENT_DATA_STATUS

    if DATASET_FILE:
        line = DATASET_FILE.pop(0).strip()
        if line:
            timestamp_str = time.strftime("%Y%m%d%H%M%S",
                time.gmtime(time.time()))
            timestamped_data = f'DATA:{CLUSTER_ID}:' \
                f'{HOSTNAME}:{timestamp_str}:{line}'
            send_data_to_cluster_head(timestamped_data)
            SENT_DATA_STATUS = True

# listener for commands from the sink
def listen_for_sink_commands():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', SINK_COMMAND_PORT))
        print("Listening for commands from the sink")

        listeners_ready.set()

        while not stop_listening_flag.is_set():
            try:
                sock.settimeout(0.1)
                data, addr = sock.recvfrom(1024)
                command = data.decode()

                if command == "RERUN_SETUP":
                    command_queue.put("RERUN_SETUP")
                    return

            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error: receiving data on sink port: {e}")

# listener for late data messages from the cluster head
def listen_for_cluster_commands():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        sock.bind(('', CLUSTER_COMMAND_PORT))
        print("Listening for commands from the cluster head")

        listeners_ready.set()

        while not stop_listening_flag.is_set():
            try:
                data, addr = sock.recvfrom(1024)
                decoded_data = data.decode('utf-8')

                if decoded_data.startswith("LATE_DATA"):
                    handle_late_data_notification(decoded_data)
                    continue

            except socket.timeout:
                continue

            except Exception as e:
                print(f"Error: receiving data on cluster port: {e}")

            if stop_listening_flag.is_set():
                break

# listener for the cluster head to receive sensor data from the nodes
# the cluster head will then strip and process the data before appending it
# to the data to send to the sink
def listen_for_node_data():
    global AGGREGATED_DATA, KNOWN_SENSORS, SENSOR_DATA_RECEIVED
    global SENSOR_LOCATION

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('', NODE_DATA_PORT))
        print("Cluster head listening for data from the nodes")

        while not stop_listening_flag.is_set():
            try:
                sock.settimeout(0.1)
                data, addr = sock.recvfrom(1024)
                decoded_data = data.decode('utf-8')

                if decoded_data.startswith("LATE_DATA"):
                    handle_late_data_notification(decoded_data)
                    continue

                parts = decoded_data.split(":")
                if len(parts) < 5:
                    print(f"Invalid data format: {decoded_data}")
                    continue

                sensor_id = parts[2]
                print(f"Received data: {sensor_id}")

                NODE_IP_MAP[sensor_id] = addr[0]

                payload = parts[4]
                split_payload = payload.split()
                (split_payload[6], split_payload[7]) = (
                    split_payload[7], split_payload[6]
                )

                new_payload = " ".join(split_payload[6:10])
                parts[4] = new_payload
                new_data = ":".join(parts[:5])
                AGGREGATED_DATA.append(new_data)
                SENSOR_DATA_RECEIVED.add(sensor_id)
                KNOWN_SENSORS.add(sensor_id)

            except socket.timeout:
                continue

            except Exception as e:
                print(f"Error: receiving data: {e}")

            if stop_listening_flag.is_set():
                break

# cluster head to handle late data notifications from the sink
def handle_late_data_notification(decoded_data):
    global AGGREGATED_DATA, NODE_IP_MAP

    try:
        _, cluster_id, node_id, timestamp = decoded_data.split(":")
        print(f"Late data notification: Cluster {cluster_id}: Node {node_id}")

        if node_id == HOSTNAME:
            print(f"Cluster Head: Late Data - Remediating")

            AGGREGATED_DATA.clear()
            print("Cleared AGGREGATED_DATA.")

            for sensor_id, sensor_ip in NODE_IP_MAP.items():
                notify_sensor_to_resend(sensor_ip, sensor_id)

        else:
            node_ip = NODE_IP_MAP.get(node_id)
            if not node_ip:
                print(f"Error: IP address not found for Node {node_id}")
                return

            AGGREGATED_DATA = [
                entry for entry in AGGREGATED_DATA
                if not entry.startswith(f"DATA:{cluster_id}:{node_id}:")
            ]

            notify_sensor_to_resend(node_ip, node_id)

    except ValueError as e:
        print(f"Error: LATE_DATA notification: {decoded_data} - {e}")

# once a late data message is received, the cluster head notifies the late
# sensor to send its next weather reading
def notify_sensor_to_resend(node_ip, node_id):

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        next_data_message = f"NEXT_DATA:{CLUSTER_ID}:{node_id}"
        sock.sendto(next_data_message.encode(), (node_ip, CLUSTER_COMMAND_PORT))
        print(f"Notified Node {node_id} to send new data")

# sends all data for the cluster for the current cycle to the sink
def send_aggregated_data_to_sink():
    global AGGREGATED_DATA, KNOWN_SENSORS, SENSOR_DATA_RECEIVED, SENSOR_LOCATION
    global DATASET_FILE

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        while True:
            start_time = time.time()
            while time.time() - start_time < DATA_INTERVAL:
                try:
                    command = command_queue.get(timeout=0.1)

                    if command == "RERUN_SETUP":
                        print("RERUN_SETUP command received from the sink")
                        rerun_setup()
                        return

                except queue.Empty:
                    pass

                time.sleep(0.1)

            try:
                for line in DATASET_FILE:
                    line = line.strip()
                    if line:
                        timestamp_str = time.strftime("%Y%m%d%H%M%S",
                            time.gmtime(time.time()))
                        timestamped_data = f'DATA:{CLUSTER_ID}:' \
                            f'{HOSTNAME}:' \
                            f'{timestamp_str}:{line}'

                        parts = timestamped_data.split(":")

                        payload = parts[4]
                        print(f"Full payload is {payload}")
                        split_payload = payload.split()
                        (split_payload[6], split_payload[7]) = (
                            split_payload[7], split_payload[6]
                        )

                        new_payload = " ".join(split_payload[6:10])
                        parts[4] = new_payload
                        new_data = ":".join(parts[:5])
                        AGGREGATED_DATA.append(new_data)

                    else:
                        timestamp_str = time.strftime("%Y%m%d%H%M%S",
                            time.gmtime(time.time()))
                        timestamped_data = f'DATA:{CLUSTER_ID}:' \
                            f'{HOSTNAME}:' \
                            f'{timestamp_strg}:No data received'
                        AGGREGATED_DATA.append(timestamped_data)
                    break


            except Exception as e:
                print(f"Error: Cluster Head Sensor Data: {e}")

            for sensor in KNOWN_SENSORS:
                if sensor not in SENSOR_DATA_RECEIVED:
                    timestamp_str = time.strftime("%Y%m%d%H%M%S",
                        time.gmtime(time.time()))
                    aggregated_message = f'DATA:{CLUSTER_ID}:{sensor}:' \
                        f'{timestamp_str}:No data received'
                    AGGREGATED_DATA.append(aggregated_message)

            SENSOR_DATA_RECEIVED.clear()

            if AGGREGATED_DATA:
                aggregated_message = ";".join(AGGREGATED_DATA)
                AGGREGATED_DATA = []
            else:
                aggregated_message = "No new data received"

            timestamp_str = time.strftime("%Y%m%d%H%M%S",
                time.gmtime(time.time()))
            cluster_head_data = f'CLUSTER_HEAD:{CLUSTER_ID}:'\
                f'{HOSTNAME}:{timestamp_str}'
            full_message = f"{cluster_head_data};{aggregated_message}"

            try:
                sock.sendto(full_message.encode('utf-8'), (SINK_IP,
                    CLUSTER_COMMAND_PORT))
                print(f"Aggregated Data: sent to sink - {full_message}")

            except Exception as e:
                print(f"Error: sending data to sink: {e}")

def main():
    global CLUSTER_ID, DATASET_FILE
    CLUSTER_ID = identify_cluster()
    time.sleep(10)

    DATASET_FILE = get_dataset_file()

    run_setup()

if __name__ == "__main__":
    main()
