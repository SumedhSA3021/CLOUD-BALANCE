# Complete Beginner's Guide: Hosting CloudBalance on Google Cloud Platform (GCP)
**Purpose:** Zero-prerequisite, step-by-step tutorial explaining how CloudBalance is hosted and deployed on the cloud.  
**Audience:** Beginners, students, and engineers looking for complete clarity without confusing unexplained jargon.

---

## CHAPTER 1: Plain-English Cloud Glossary
Before touching any commands, let's make sure every single technical word makes intuitive sense.

### 1. What is "The Cloud" and what is "GCP"?
* **The Cloud:** "The Cloud" is simply someone else's computer. Instead of buying physical, noisy server computers and keeping them in your room, companies like Google, Amazon, and Microsoft maintain massive warehouses full of supercomputers (called Data Centers). You rent small slices of these computers over the internet.
* **GCP (Google Cloud Platform):** Google's cloud service. It gives you access to the same global computing infrastructure that powers Google Search, YouTube, and Gmail.

### 2. What is a "Virtual Machine" (VM)?
* A physical computer has a CPU, RAM (memory), and a hard drive.
* A **Virtual Machine (VM)** is a software-based computer that runs inside a huge physical computer. You can choose how many CPU cores and how much RAM it has (e.g., 2 vCPUs and 4 GB RAM). To you, it behaves exactly like a real physical laptop running in Google's data center.
* In GCP, Virtual Machines are provided by a service called **Compute Engine**.

### 3. What is an Operating System & Ubuntu Linux?
* An **Operating System (OS)** is the master software that manages the computer's hardware (like Windows, macOS, or Linux).
* **Ubuntu Linux:** Most servers on the internet do not use Windows; they use Ubuntu Linux. It does not usually have a graphical desktop with icons to click; instead, you interact with it entirely by typing text commands into a terminal (command prompt).

### 4. What is an "IP Address" (External vs. Internal)?
* An **IP (Internet Protocol) Address** is the digital phone number of a computer.
* **External (Public) IP Address:** An address that anyone on the public internet can reach (like a store's public street address). We need an external IP on our Controller VM so our laptop can view the React Dashboard in a web browser and send traffic to the API.
* **Internal (Private) IP Address:** An address that is only accessible inside a private local network (like room numbers inside a private house). Worker VMs use internal IPs to talk securely to the Controller without exposing themselves to hackers on the public internet.

### 5. What is a "VPC Network" (Virtual Private Cloud)?
* A **VPC Network** is your own private, fenced-off digital network inside Google Cloud.
* All your VMs sit inside this fence. They can talk to each other very quickly and securely, isolated from all other Google Cloud customers. In our project, our private fence is named `cloudbalance-net`.

### 6. What is a "Port"?
* If an IP address is like the street address of an apartment building, a **Port number** is the apartment number.
* A single computer can run multiple programs at the same time. Ports tell the computer which program an incoming message belongs to:
  * Port `22`: Reserved for **SSH** (secure remote terminal login).
  * Port `80`: Standard unencrypted web traffic (HTTP).
  * Port `3000`: Used by our **React Web Dashboard**.
  * Port `8000`: Used by our **FastAPI Central Backend**.
  * Port `8001`: Used by our **Worker Execution Server**.
  * Port `6379`: Used by our **Redis In-Memory Database**.

### 7. What is a "Firewall Rule"?
* A digital security guard at the gate of your network.
* By default, Google Cloud blocks all incoming traffic from the outside world. A **Firewall Rule** explicitly tells Google: *"Allow incoming traffic on Port 8000 and Port 3000 so the user can see the dashboard."*

### 8. What is "SSH" (Secure Shell)?
* A secure, encrypted way to open a terminal inside a remote Linux computer across the internet. When you type commands into an SSH terminal, they execute directly inside the Google Cloud VM.

### 9. What is "Redis"?
* A database that stores data completely in the computer's ultra-fast RAM instead of writing it to a slow hard drive.
* Member 1's monitoring agents push CPU and RAM metrics into Redis every 2 seconds. When Member 2's optimizer needs to decide where to send a task, reading from Redis takes less than 1 millisecond.

### 10. What is `nohup` and `&`?
* Normally, if you run a Python script inside an SSH terminal and close your laptop, the script stops immediately.
* Adding `nohup` (No Hangup) and `&` tells Linux: *"Keep this program running forever in the background, even if I log out and disconnect."*

---

## CHAPTER 2: CloudBalance Infrastructure Blueprint

Our system consists of **3 Virtual Machines on Google Cloud** and **1 Local Client Computer**:

```
+---------------------------------------------------------------------------------------------------+
| YOUR LOCAL LAPTOP (Client PC - Member 2)                                                          |
| • Runs: python simulate_traffic.py --target-url http://34.x.x.x:8000                              |
| • Generates Poisson traffic across the public internet                                            |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  │ Public HTTP Requests
                                                  ▼
=====================================================================================================
GOOGLE CLOUD PLATFORM (GCP) — Custom VPC Network: `cloudbalance-net`
=====================================================================================================

  ┌───────────────────────────────────────────────────────────────────────────────────────────────┐
  │ 1. CONTROLLER VM: `cloudbalance-controller`                                                   │
  │ • Machine Type: e2-standard-2 (2 vCPUs, 8 GB RAM)                                             │
  │ • External Public IP: 34.x.x.x (Accessible via browser)                                       │
  │ • Internal Private IP: 10.128.0.10                                                            │
  │                                                                                               │
  │ Programs Running Inside:                                                                      │
  │ 1. Redis Server (Port 6379) — Stores live worker metrics                                      │
  │ 2. FastAPI Central Backend (Port 8000) — Ingests tasks, runs Member 2's OR-Tools optimizer     │
  │ 3. React Dashboard (Port 3000) — Renders live visual graphs in your web browser               │
  └───────────────────────────────┬───────────────────────────────┬───────────────────────────────┘
                                  │                               │
                 Internal VPC Call│POST :8001/execute             │POST :8001/execute
                                  ▼                               ▼
  ┌───────────────────────────────────────────────┐   ┌───────────────────────────────────────────────┐
  │ 2. WORKER VM 1: `cb-worker-1`                 │   │ 3. WORKER VM 2: `cb-worker-2`                 │
  │ • Machine Type: e2-medium (2 vCPUs, 4 GB RAM) │   │ • Machine Type: e2-medium (2 vCPUs, 4 GB RAM) │
  │ • Internal IP: 10.128.0.11                    │   │ • Internal IP: 10.128.0.12                    │
  │                                               │   │                                               │
  │ Programs Running Inside:                      │   │ Programs Running Inside:                      │
  │ 1. Execution Server (Port 8001)               │   │ 1. Execution Server (Port 8001)               │
  │    Runs physical NumPy matrix multiplications │   │    Runs physical NumPy matrix multiplications │
  │ 2. psutil Telemetry Agent                     │   │ 2. psutil Telemetry Agent                     │
  │    Samples CPU/RAM and sends to Controller    │   │    Samples CPU/RAM and sends to Controller    │
  └───────────────────────────────────────────────┘   └───────────────────────────────────────────────┘
```

---

## CHAPTER 3: Step-by-Step GCP Deployment Guide

### STEP 1: Log in to Google Cloud Console
1. Open your web browser and go to: **[https://console.cloud.google.com/](https://console.cloud.google.com/)**.
2. Sign in with your Google account. (If you are new, Google provides $300 in free credits).
3. In the top navigation bar, click the project dropdown and click **"New Project"**.
4. Name your project: `cloudbalance-project` and click **Create**.
5. Make sure your new project is selected in the top bar.

---

### STEP 2: Open Google Cloud Shell
Google Cloud provides a built-in terminal directly in your web browser that comes pre-installed with all necessary Google Cloud management tools (`gcloud`).
1. In the top-right corner of the Google Cloud Console, click the **Activate Cloud Shell** icon (it looks like a small terminal box `[ >_ ]`).
2. A black terminal panel will open at the bottom of your screen. Click **Continue** if prompted.

---

### STEP 3: Create the Private Network & Open Firewall Gates
In Cloud Shell, copy and paste the following commands one by one. These create your private VPC network and open the necessary security gates:

#### 1. Create the Custom VPC Network
```bash
gcloud compute networks create cloudbalance-net --subnet-mode=auto
```
* **What this does:** Creates your private digital network named `cloudbalance-net`.

#### 2. Open Port 22 (SSH Remote Access)
```bash
gcloud compute firewall-rules create allow-cloudbalance-ssh \
    --network=cloudbalance-net \
    --allow=tcp:22 \
    --source-ranges=0.0.0.0/0 \
    --description="Allow SSH terminal access from anywhere"
```
* **What this does:** Lets you securely log into your VMs from anywhere.

#### 3. Open Ports 8000 and 3000 (Public Access for Dashboard & API)
```bash
gcloud compute firewall-rules create allow-cloudbalance-public \
    --network=cloudbalance-net \
    --allow=tcp:8000,tcp:3000 \
    --source-ranges=0.0.0.0/0 \
    --description="Allow public web access to React UI and FastAPI"
```
* **What this does:** Allows your laptop's browser to open the React dashboard on port 3000 and send traffic to FastAPI on port 8000.

#### 4. Allow Internal Communication Between VMs
```bash
gcloud compute firewall-rules create allow-cloudbalance-internal \
    --network=cloudbalance-net \
    --allow=tcp:6379,tcp:8000,tcp:8001,icmp \
    --source-ranges=10.128.0.0/9 \
    --description="Allow VMs inside the VPC to talk to each other"
```
* **What this does:** Allows the Controller to talk to Redis (6379), workers to report telemetry (8000), and the Controller to dispatch jobs to workers (8001).

---

### STEP 4: Create the 3 Virtual Machines
Still inside Cloud Shell, run these commands to instantiate the 3 servers:

#### 1. Create the Controller VM
```bash
gcloud compute instances create cloudbalance-controller \
    --zone=us-central1-a \
    --machine-type=e2-standard-2 \
    --network=cloudbalance-net \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB \
    --tags=controller-node
```
* **Explanation:** Creates an Ubuntu 22.04 LTS server with 2 vCPUs and 8 GB RAM. This host will run Redis, FastAPI, and React.

#### 2. Create Worker VM 1
```bash
gcloud compute instances create cb-worker-1 \
    --zone=us-central1-a \
    --machine-type=e2-medium \
    --network=cloudbalance-net \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --tags=worker-node
```

#### 3. Create Worker VM 2
```bash
gcloud compute instances create cb-worker-2 \
    --zone=us-central1-a \
    --machine-type=e2-medium \
    --network=cloudbalance-net \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --tags=worker-node
```

#### 4. Find Your VM IP Addresses
Run this command to print out the IP addresses:
```bash
gcloud compute instances list
```
You will see output like this:
```
NAME                    ZONE           MACHINE_TYPE   INTERNAL_IP  EXTERNAL_IP     STATUS
cloudbalance-controller us-central1-a  e2-standard-2  10.128.0.10  34.123.45.67    RUNNING
cb-worker-1             us-central1-a  e2-medium      10.128.0.11  34.123.45.68    RUNNING
cb-worker-2             us-central1-a  e2-medium      10.128.0.12  34.123.45.69    RUNNING
```
> **IMPORTANT:** Note down the **EXTERNAL_IP** of `cloudbalance-controller`. You will need this to access the dashboard and stream traffic!

---

### STEP 5: Configure the Worker VMs (Member 1's Role)
Now we log into each worker VM and launch the execution server and the monitoring agent.

#### On Worker 1 (`cb-worker-1`):
1. In Cloud Shell, connect via SSH:
   ```bash
   gcloud compute ssh cb-worker-1 --zone=us-central1-a
   ```
2. Install Python and dependencies:
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git
   python3 -m venv venv
   source venv/bin/activate
   pip install psutil httpx uvicorn fastapi numpy
   ```
3. Run the Execution Server on Port 8001 (runs Member 2's physical NumPy matrix code):
   ```bash
   nohup uvicorn executor:app --host 0.0.0.0 --port 8001 > executor.log 2>&1 &
   ```
4. Run the Telemetry Monitoring Agent (reports to Controller at `10.128.0.10`):
   ```bash
   nohup python3 agent.py --worker-id worker-1 --backend-url http://10.128.0.10:8000 > agent.log 2>&1 &
   ```
5. Type `exit` to disconnect from `cb-worker-1`.

#### On Worker 2 (`cb-worker-2`):
Repeat the exact same steps, changing the worker ID to `worker-2`:
```bash
gcloud compute ssh cb-worker-2 --zone=us-central1-a
sudo apt update && sudo apt install -y python3-pip python3-venv git
python3 -m venv venv && source venv/bin/activate
pip install psutil httpx uvicorn fastapi numpy
nohup uvicorn executor:app --host 0.0.0.0 --port 8001 > executor.log 2>&1 &
nohup python3 agent.py --worker-id worker-2 --backend-url http://10.128.0.10:8000 > agent.log 2>&1 &
exit
```

---

### STEP 6: Configure the Controller VM (Member 3 & 4's Roles)
Now we configure the main coordinator computer.

1. In Cloud Shell, connect to the Controller via SSH:
   ```bash
   gcloud compute ssh cloudbalance-controller --zone=us-central1-a
   ```

2. Install Redis, Python, and Node.js:
   ```bash
   sudo apt update && sudo apt install -y redis-server python3-pip python3-venv git nodejs npm
   sudo systemctl enable redis-server
   sudo systemctl start redis-server
   ```
   * *Verify Redis is running:* Type `redis-cli ping`. It should reply `PONG`.

3. Deploy and Start the FastAPI Central Backend (with Member 2's Google OR-Tools Optimizer):
   ```bash
   cd CloudBalance/backend
   python3 -m venv venv && source venv/bin/activate
   pip install fastapi uvicorn redis pymongo ortools numpy httpx pydantic
   nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
   ```

4. Build and Start the React Dashboard:
   ```bash
   cd ../frontend
   npm install
   npm run build
   nohup npx serve -s dist -l 3000 > frontend.log 2>&1 &
   ```
5. Type `exit` to disconnect from the Controller.

---

### STEP 7: Verify Everything from Your Web Browser!
Open Google Chrome on your personal laptop and navigate to:
```
http://<CONTROLLER_EXTERNAL_IP>:3000
```
*(Replace `<CONTROLLER_EXTERNAL_IP>` with the actual IP address you noted down in Step 4, e.g. `http://34.123.45.67:3000`).*

* **What you will see:** The **CloudBalance Live Operations Dashboard**!
* Both `Worker 1` and `Worker 2` will be displayed as **Green (Healthy)** cards showing ~2% CPU and ~15% RAM.
* This proves that Member 1's agents are actively sampling the worker VMs, pushing data into Redis on the Controller, and Member 4's React UI is displaying it in real time over WebSockets!

---

### STEP 8: Member 2's Grand Finale — Injecting Real-Time Traffic!
Now you take the stage! On your personal laptop terminal:

1. Open your project folder:
   ```powershell
   cd "C:\Users\sumed\Desktop\Minor Project\06_Prototype_Implementation"
   ```
2. Run your traffic generator pointing directly to your Google Cloud Controller:
   ```powershell
   python optimizer/simulate_traffic.py --target-url http://<CONTROLLER_EXTERNAL_IP>:8000 --lambda 1.5 --max-tasks 30
   ```

* **What happens live before your mentor's eyes:**
  1. Your laptop calculates Poisson inter-arrival delays and streams tasks across the internet.
  2. The Google OR-Tools solver on the Controller assigns tasks to Worker 1 and Worker 2.
  3. The workers execute real NumPy matrix math; their CPU gauges on the React dashboard climb to 45%–65% and turn **Yellow (Moderate)**.
  4. The time-series graphs show the two VM workloads balancing out evenly without any spikes over 85%!

---

### STEP 9: Clean Up & Cost Management (Don't Get Charged!)
When your viva or presentation is finished, you must turn off your VMs so you don't use up your cloud credits:

#### Option A: Temporarily Stop the VMs (Keeps files intact, zero CPU billing)
Run in Cloud Shell:
```bash
gcloud compute instances stop cloudbalance-controller cb-worker-1 cb-worker-2 --zone=us-central1-a
```
*(You can restart them anytime with `gcloud compute instances start ...`)*

#### Option B: Permanently Delete Everything (Complete Cleanup)
```bash
gcloud compute instances delete cloudbalance-controller cb-worker-1 cb-worker-2 --zone=us-central1-a --quiet
gcloud compute firewall-rules delete allow-cloudbalance-ssh allow-cloudbalance-public allow-cloudbalance-internal --quiet
gcloud compute networks delete cloudbalance-net --quiet
```
